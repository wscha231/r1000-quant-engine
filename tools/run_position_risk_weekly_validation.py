#!/usr/bin/env python3
"""Validate position-risk proxy performance on daily/weekly price paths.

The monthly position-risk replays are useful discovery tools, but they can be
too optimistic because they cap month-end losses without proving that an exit
was observable before the month closed. This runner keeps the same monthly
holding books, then walks daily closes between rebalance dates to test whether
hard stops, trailing stops, relative-underperformance exits, and soft trims are
plausible with cached prices.

It remains research-only: it does not create true weekly scored portfolios or
broker orders. It is a stricter promotion gate between monthly proxy evidence
and production activation.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "tools"))

from historical_replay_lib import blocked_payload, calc_metrics, equity_curve_rows, write_json, write_rows, write_text
from run_position_aware_risk_replay import is_long_hold_protected
from run_weekly_evaluation import load_price_series, price_on_or_after


CASH_TICKERS = {"CASH", "__CASH__"}
DEFAULT_OUT_DIR = "outputs/position_risk_weekly_validation"
CONCENTRATED_CHAMPION_FILTERS = {
    "target_stock_names": "3",
    "weighting_mode": "score_power",
    "active_rebalance_interval_months": "1",
}
MAX_REASONABLE_WEIGHT_SUM = 1.05


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        if not math.isfinite(out):
            return default
        return out
    except (TypeError, ValueError):
        return default


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def filter_concentrated_champion(frame: pd.DataFrame, portfolio_kind: str) -> pd.DataFrame:
    if portfolio_kind != "concentrated" or frame.empty:
        return frame
    out = frame.copy()
    for col, expected in CONCENTRATED_CHAMPION_FILTERS.items():
        if col not in out.columns:
            continue
        values = out[col].astype(str).str.strip()
        mask = values.eq(expected)
        if mask.any():
            out = out[mask].copy()
    return out


def normalize_holdings(frame: pd.DataFrame, portfolio_kind: str) -> pd.DataFrame:
    if frame.empty or "rebalance_date" not in frame.columns or "ticker" not in frame.columns or "weight" not in frame.columns:
        return pd.DataFrame()
    out = filter_concentrated_champion(frame.copy(), portfolio_kind)
    out["rebalance_date"] = pd.to_datetime(out["rebalance_date"], errors="coerce")
    out["ticker"] = out["ticker"].astype(str).str.upper().str.strip()
    out["weight"] = pd.to_numeric(out["weight"], errors="coerce").fillna(0.0)
    out = out.dropna(subset=["rebalance_date"])
    out = out[(out["ticker"] != "") & (out["weight"] > 1e-12)]
    out["portfolio_kind"] = portfolio_kind
    return out.sort_values(["rebalance_date", "weight"], ascending=[True, False]).reset_index(drop=True)


def weight_book_diagnostics(holdings: pd.DataFrame) -> dict[str, Any]:
    if holdings.empty:
        return {"max_total_weight": None, "invalid_weight_dates": []}
    rows: list[dict[str, Any]] = []
    tmp = holdings.copy()
    tmp["rebalance_date"] = pd.to_datetime(tmp["rebalance_date"], errors="coerce").dt.normalize()
    for dt, period in tmp.dropna(subset=["rebalance_date"]).groupby("rebalance_date"):
        stock_weight = float(period.loc[~period["ticker"].isin(CASH_TICKERS), "weight"].sum())
        cash_weight = float(period.loc[period["ticker"].isin(CASH_TICKERS), "weight"].sum())
        rows.append(
            {
                "rebalance_date": pd.Timestamp(dt).date().isoformat(),
                "stock_weight": stock_weight,
                "cash_weight": cash_weight,
                "total_weight": stock_weight + cash_weight,
            }
        )
    invalid = [row for row in rows if row["total_weight"] > MAX_REASONABLE_WEIGHT_SUM]
    return {
        "max_total_weight": max((row["total_weight"] for row in rows), default=None),
        "max_stock_weight": max((row["stock_weight"] for row in rows), default=None),
        "invalid_weight_dates": invalid[:10],
        "invalid_weight_date_count": len(invalid),
    }


def period_end_map(path: Path) -> dict[pd.Timestamp, pd.Timestamp]:
    frame = read_csv(path)
    if frame.empty or "rebalance_date" not in frame.columns:
        return {}
    if "next_rebalance_date" not in frame.columns:
        return {}
    d = frame.copy()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce")
    d["next_rebalance_date"] = pd.to_datetime(d["next_rebalance_date"], errors="coerce")
    d = d.dropna(subset=["rebalance_date", "next_rebalance_date"])
    return {
        pd.Timestamp(row.rebalance_date).normalize(): pd.Timestamp(row.next_rebalance_date).normalize()
        for row in d.drop_duplicates("rebalance_date", keep="last").itertuples(index=False)
    }


def should_check_relative(date: pd.Timestamp, final_date: pd.Timestamp) -> bool:
    return pd.Timestamp(date).weekday() == 4 or pd.Timestamp(date).normalize() >= pd.Timestamp(final_date).normalize()


def price_path_between(px: pd.DataFrame, start_dt: pd.Timestamp, end_dt: pd.Timestamp) -> pd.DataFrame:
    if px.empty or "close" not in px.columns:
        return pd.DataFrame()
    idx = pd.DatetimeIndex(px.index).tz_localize(None)
    out = px.copy()
    out.index = idx
    return out[(out.index >= start_dt) & (out.index <= end_dt)].sort_index()


def benchmark_return_on(bench_path: pd.DataFrame, entry_price: float | None, date: pd.Timestamp) -> float:
    if bench_path.empty or entry_price is None or entry_price <= 0:
        return 0.0
    upto = bench_path[bench_path.index <= pd.Timestamp(date)]
    if upto.empty:
        return 0.0
    price = safe_float(upto["close"].iloc[-1], entry_price)
    return price / entry_price - 1.0 if entry_price > 0 else 0.0


def simulate_position(
    row: dict[str, Any],
    px: pd.DataFrame,
    bench_px: pd.DataFrame,
    entry_dt: pd.Timestamp,
    end_dt: pd.Timestamp,
    *,
    hard_stop: float,
    trailing_stop: float,
    trailing_activation: float,
    relative_trim_threshold: float,
    relative_exit_threshold: float,
    trim_weight: float,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    ticker = str(row.get("ticker") or "").upper()
    entry_actual, entry_price = price_on_or_after(px, entry_dt, "open")
    bench_entry_actual, bench_entry_price = price_on_or_after(bench_px, entry_dt, "open")
    if entry_actual is None or entry_price is None:
        return (
            {
                "ticker": ticker,
                "contribution_rel": 1.0,
                "sold_multiplier": 0.0,
                "exit_action": "missing_price_hold_cash_proxy",
                "exit_reason": "missing_entry_price",
                "entry_date": "",
                "exit_date": "",
                "entry_price": "",
                "exit_price": "",
                "final_return": 0.0,
            },
            [],
        )
    path = price_path_between(px, pd.Timestamp(entry_actual), end_dt)
    if path.empty:
        return (
            {
                "ticker": ticker,
                "contribution_rel": 1.0,
                "sold_multiplier": 0.0,
                "exit_action": "missing_price_hold_cash_proxy",
                "exit_reason": "missing_path",
                "entry_date": pd.Timestamp(entry_actual).date().isoformat(),
                "exit_date": "",
                "entry_price": entry_price,
                "exit_price": "",
                "final_return": 0.0,
            },
            [],
        )

    bench_path = price_path_between(bench_px, pd.Timestamp(bench_entry_actual or entry_actual), end_dt)
    active = 1.0
    cash_locked_rel = 0.0
    peak_rel = 1.0
    trim_done = False
    sold_multiplier = 0.0
    action = "hold"
    reason = "hold"
    action_rows: list[dict[str, Any]] = []
    last_rel = 1.0
    last_date = pd.Timestamp(entry_actual)
    for ts, px_row in path.iterrows():
        close = safe_float(px_row.get("close"), entry_price)
        if close <= 0:
            continue
        rel = close / entry_price
        last_rel = rel
        last_date = pd.Timestamp(ts)
        peak_rel = max(peak_rel, rel)
        total_return = rel - 1.0
        drawdown_from_peak = rel / max(peak_rel, 1e-12) - 1.0
        bench_return = benchmark_return_on(bench_path, bench_entry_price, pd.Timestamp(ts))
        relative_return = (1.0 + total_return) / max(1.0 + bench_return, 1e-8) - 1.0
        cumulative_return_before = total_return
        protected = is_long_hold_protected(row, cumulative_return_before, relative_return)

        trigger_action = ""
        trigger_reason = ""
        if total_return <= hard_stop:
            trigger_action = "daily_hard_stop_exit"
            trigger_reason = "daily_close_breached_hard_stop"
        elif peak_rel - 1.0 >= trailing_activation and drawdown_from_peak <= trailing_stop:
            trigger_action = "daily_trailing_stop_exit"
            trigger_reason = "daily_close_breached_trailing_stop"
        elif should_check_relative(pd.Timestamp(ts), end_dt):
            exit_risk = max(
                safe_float(row.get("explosion_exit_score"), 0.0),
                safe_float(row.get("stage2_overext_penalty"), 0.0),
                safe_float(row.get("risk_penalty"), 0.0),
            )
            rs_accel = safe_float(row.get("rs_acceleration_score"), 0.0)
            if exit_risk >= 0.85 and rs_accel < 0.0 and total_return < -0.02:
                trigger_action = "weekly_distribution_exit"
                trigger_reason = "distribution_risk_decay"
            elif relative_return <= relative_exit_threshold and not protected:
                trigger_action = "weekly_relative_exit"
                trigger_reason = "relative_underperformance_exit"
            elif relative_return <= relative_trim_threshold and not trim_done:
                trigger_action = "weekly_relative_trim"
                trigger_reason = "relative_underperformance_trim50" + ("_protected" if protected else "")

        if trigger_action == "weekly_relative_trim":
            new_active = active * min(max(trim_weight, 0.0), 1.0)
            sold = max(active - new_active, 0.0)
            cash_locked_rel += sold * rel
            sold_multiplier += sold
            active = new_active
            trim_done = True
            action = trigger_action
            reason = trigger_reason
            action_rows.append(
                {
                    "ticker": ticker,
                    "action_date": pd.Timestamp(ts).date().isoformat(),
                    "action": trigger_action,
                    "reason": trigger_reason,
                    "price_return": total_return,
                    "benchmark_return": bench_return,
                    "relative_return": relative_return,
                    "action_price": close,
                    "sold_multiplier": sold,
                    "active_multiplier_after": active,
                }
            )
            continue
        if trigger_action:
            cash_locked_rel += active * rel
            sold_multiplier += active
            active = 0.0
            action = trigger_action
            reason = trigger_reason
            action_rows.append(
                {
                    "ticker": ticker,
                    "action_date": pd.Timestamp(ts).date().isoformat(),
                    "action": trigger_action,
                    "reason": trigger_reason,
                    "price_return": total_return,
                    "benchmark_return": bench_return,
                    "relative_return": relative_return,
                    "action_price": close,
                    "sold_multiplier": sold_multiplier,
                    "active_multiplier_after": active,
                }
            )
            break

    contribution_rel = cash_locked_rel + active * last_rel
    if active <= 1e-12 and action_rows:
        exit_date = action_rows[-1]["action_date"]
    else:
        exit_date = ""
    return (
        {
            "ticker": ticker,
            "contribution_rel": float(contribution_rel),
            "sold_multiplier": float(min(max(sold_multiplier, 0.0), 1.0)),
            "exit_action": action,
            "exit_reason": reason,
            "entry_date": pd.Timestamp(entry_actual).date().isoformat(),
            "exit_date": exit_date,
            "final_date": pd.Timestamp(last_date).date().isoformat(),
            "entry_price": float(entry_price),
            "exit_price": float(action_rows[-1]["action_price"]) if action_rows and active <= 1e-12 else "",
            "final_price": float(last_rel * entry_price),
            "final_return": float(contribution_rel - 1.0),
            "raw_final_return": float(last_rel - 1.0),
        },
        action_rows,
    )


def rolling_rows(monthly_rows: list[dict[str, Any]], window_months: int = 36) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if len(monthly_rows) < window_months:
        return out
    for idx in range(window_months - 1, len(monthly_rows)):
        window = monthly_rows[idx - window_months + 1 : idx + 1]
        metrics = calc_metrics([safe_float(row.get("net_return")) for row in window])
        out.append(
            {
                "start_date": window[0].get("rebalance_date"),
                "end_date": window[-1].get("rebalance_date"),
                "months": window_months,
                "cagr": metrics.get("cagr"),
                "sharpe": metrics.get("sharpe"),
                "max_dd": metrics.get("max_dd"),
                "ending_equity": metrics.get("ending_equity"),
            }
        )
    return out


def replay(
    *,
    holdings_path: Path,
    period_map_path: Path,
    price_cache: Path,
    output_dir: Path,
    portfolio_kind: str,
    benchmark_ticker: str = "SPY",
    hard_stop: float = -0.08,
    trailing_stop: float = -0.15,
    trailing_activation: float = 0.15,
    relative_trim_threshold: float = -0.06,
    relative_exit_threshold: float = -0.12,
    trim_weight: float = 0.50,
    cost_bps: float = 25.0,
) -> dict[str, Any]:
    raw = read_csv(holdings_path)
    holdings = normalize_holdings(raw, portfolio_kind)
    if holdings.empty:
        return blocked_payload("holdings input is empty or missing", holdings_path, output_dir, "position_risk_weekly_validation")
    weight_diag = weight_book_diagnostics(holdings)
    if int(weight_diag.get("invalid_weight_date_count") or 0) > 0:
        payload = blocked_payload("holdings weight sum exceeds 105%; refusing contaminated replay", holdings_path, output_dir, "position_risk_weekly_validation")
        payload.update(weight_diag)
        payload["research_only"] = True
        payload["production_activation_allowed"] = False
        payload["valid_for_production"] = False
        output_dir.mkdir(parents=True, exist_ok=True)
        write_json(output_dir / "metrics.json", payload)
        write_text(
            output_dir / "validation_report.md",
            "# Position Risk Weekly Validation\n\n"
            "Status: blocked\n\n"
            "Reason: holdings weight sum exceeds 105%; refusing contaminated replay.\n",
        )
        return payload
    if not price_cache.exists():
        return blocked_payload("price cache is missing", price_cache, output_dir, "position_risk_weekly_validation")
    next_dates = period_end_map(period_map_path)
    prices: dict[str, pd.DataFrame] = {}
    tickers = sorted(set(holdings["ticker"].astype(str)) - CASH_TICKERS)
    for ticker in tickers + [benchmark_ticker.upper()]:
        prices[ticker] = load_price_series(price_cache, ticker)

    monthly_rows: list[dict[str, Any]] = []
    action_rows: list[dict[str, Any]] = []
    position_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    rebal_dates = sorted(pd.to_datetime(holdings["rebalance_date"], errors="coerce").dropna().unique())
    for idx, raw_dt in enumerate(rebal_dates):
        dt = pd.Timestamp(raw_dt).normalize()
        if dt in next_dates:
            end_dt = next_dates[dt]
        elif idx + 1 < len(rebal_dates):
            end_dt = pd.Timestamp(rebal_dates[idx + 1]).normalize()
        else:
            continue
        period = holdings[pd.to_datetime(holdings["rebalance_date"], errors="coerce").dt.normalize().eq(dt)].copy()
        if period.empty:
            continue
        entry_dt = dt + pd.Timedelta(days=1)
        explicit_cash = float(period.loc[period["ticker"].isin(CASH_TICKERS), "weight"].sum())
        stock_weight = float(period.loc[~period["ticker"].isin(CASH_TICKERS), "weight"].sum())
        cash_weight = float(np.clip(explicit_cash + max(0.0, 1.0 - stock_weight - explicit_cash), 0.0, 1.0))
        period_rel = cash_weight
        exit_turnover = 0.0
        exit_count = 0
        trim_count = 0
        missing_count = 0
        for row_obj in period.itertuples(index=False):
            row = row_obj._asdict()
            ticker = str(row.get("ticker") or "").upper()
            if ticker in CASH_TICKERS:
                continue
            weight = safe_float(row.get("weight"), 0.0)
            result, actions = simulate_position(
                row,
                prices.get(ticker, pd.DataFrame()),
                prices.get(benchmark_ticker.upper(), pd.DataFrame()),
                entry_dt,
                end_dt,
                hard_stop=hard_stop,
                trailing_stop=trailing_stop,
                trailing_activation=trailing_activation,
                relative_trim_threshold=relative_trim_threshold,
                relative_exit_threshold=relative_exit_threshold,
                trim_weight=trim_weight,
            )
            contribution_rel = safe_float(result.get("contribution_rel"), 1.0)
            sold_multiplier = safe_float(result.get("sold_multiplier"), 0.0)
            period_rel += weight * contribution_rel
            exit_turnover += weight * sold_multiplier
            action = str(result.get("exit_action") or "hold")
            if "exit" in action:
                exit_count += 1
            if "trim" in action:
                trim_count += 1
            if action == "missing_price_hold_cash_proxy":
                missing_count += 1
            position_payload = {
                "rebalance_date": dt.date().isoformat(),
                "period_end_date": end_dt.date().isoformat(),
                "ticker": ticker,
                "weight": weight,
                **result,
                "sector": row.get("sector", ""),
                "portfolio_monster_early_score": row.get("portfolio_monster_early_score", ""),
                "portfolio_stale_mega_leader_score": row.get("portfolio_stale_mega_leader_score", ""),
                "rs_acceleration_score": row.get("rs_acceleration_score", ""),
                "risk_penalty": row.get("risk_penalty", ""),
                "stage2_overext_penalty": row.get("stage2_overext_penalty", ""),
                "explosion_exit_score": row.get("explosion_exit_score", ""),
            }
            position_rows.append(position_payload)
            if result.get("entry_date"):
                trade_rows.append(
                    {
                        "portfolio_kind": portfolio_kind,
                        "rebalance_date": dt.date().isoformat(),
                        "period_end_date": end_dt.date().isoformat(),
                        "trade_date": result.get("entry_date"),
                        "ticker": ticker,
                        "side": "BUY",
                        "action": "monthly_entry_open",
                        "reason": "monthly_holding_book_entry",
                        "target_weight": weight,
                        "trade_weight": weight,
                        "active_multiplier_after": 1.0,
                        "price": result.get("entry_price", ""),
                        "is_risk_exit": False,
                        "is_relative_trim": False,
                    }
                )
            for action_row in actions:
                action_rows.append(
                    {
                        "rebalance_date": dt.date().isoformat(),
                        "period_end_date": end_dt.date().isoformat(),
                        "portfolio_kind": portfolio_kind,
                        "weight": weight,
                        **action_row,
                    }
                )
                sold_multiplier = safe_float(action_row.get("sold_multiplier"), 0.0)
                action_name = str(action_row.get("action") or "")
                trade_rows.append(
                    {
                        "portfolio_kind": portfolio_kind,
                        "rebalance_date": dt.date().isoformat(),
                        "period_end_date": end_dt.date().isoformat(),
                        "trade_date": action_row.get("action_date"),
                        "ticker": ticker,
                        "side": "SELL" if "exit" in action_name else "TRIM",
                        "action": action_name,
                        "reason": action_row.get("reason", ""),
                        "target_weight": weight,
                        "trade_weight": weight * sold_multiplier,
                        "active_multiplier_after": action_row.get("active_multiplier_after", ""),
                        "price": action_row.get("action_price", ""),
                        "price_return": action_row.get("price_return", ""),
                        "benchmark_return": action_row.get("benchmark_return", ""),
                        "relative_return": action_row.get("relative_return", ""),
                        "is_risk_exit": "exit" in action_name,
                        "is_relative_trim": "trim" in action_name,
                    }
                )
        cost = exit_turnover * (cost_bps / 10000.0)
        monthly_rows.append(
            {
                "rebalance_date": dt.date().isoformat(),
                "period_end_date": end_dt.date().isoformat(),
                "gross_return": period_rel - 1.0,
                "exit_turnover": exit_turnover,
                "cost": cost,
                "net_return": period_rel - 1.0 - cost,
                "cash_weight_start": cash_weight,
                "stock_weight_start": stock_weight,
                "exit_count": exit_count,
                "trim_count": trim_count,
                "missing_price_count": missing_count,
                "position_count": int((~period["ticker"].isin(CASH_TICKERS)).sum()),
            }
        )

    metrics = calc_metrics([safe_float(row.get("net_return")) for row in monthly_rows])
    curve = equity_curve_rows(monthly_rows)
    rolling = rolling_rows(monthly_rows, 36)
    price_coverage = 1.0
    total_positions = len(position_rows)
    if total_positions:
        price_coverage = 1.0 - sum(1 for row in position_rows if row.get("exit_action") == "missing_price_hold_cash_proxy") / total_positions
    payload = {
        "experiment_id": "position_risk_weekly_validation",
        "portfolio_kind": portfolio_kind,
        "status": "completed" if monthly_rows else "blocked",
        "data_mode": "daily_price_path_validation_from_monthly_holdings",
        "metric_mode": "position_risk_weekly_validation",
        "validation_granularity": "daily_stop_checks_weekly_relative_checks",
        "input": str(holdings_path),
        "period_map": str(period_map_path),
        "price_cache": str(price_cache),
        "benchmark_ticker": benchmark_ticker.upper(),
        "hard_stop": hard_stop,
        "trailing_stop": trailing_stop,
        "trailing_activation": trailing_activation,
        "relative_trim_threshold": relative_trim_threshold,
        "relative_exit_threshold": relative_exit_threshold,
        "relative_trim_weight": trim_weight,
        "cost_bps": cost_bps,
        "months": metrics.get("months"),
        "cagr": metrics.get("cagr"),
        "sharpe": metrics.get("sharpe"),
        "max_dd": metrics.get("max_dd"),
        "calmar": metrics.get("calmar"),
        "vol_ann": metrics.get("vol_ann"),
        "ending_equity": metrics.get("ending_equity"),
        "price_coverage": price_coverage,
        "avg_cash_weight": float(np.mean([safe_float(row.get("cash_weight_start")) for row in monthly_rows])) if monthly_rows else None,
        "exit_count": sum(int(safe_float(row.get("exit_count"))) for row in monthly_rows),
        "trim_count": sum(int(safe_float(row.get("trim_count"))) for row in monthly_rows),
        "research_only": True,
        "production_activation_allowed": False,
        "valid_for_production": False,
        "promotion_note": "Stricter than monthly proxy, but still uses monthly holding books. True production requires order ticket simulation and weekly/daily scored snapshots.",
        **weight_diag,
        "monthly_path": str(output_dir / "monthly.csv"),
        "actions_path": str(output_dir / "actions.csv"),
        "trade_log_path": str(output_dir / "trade_log.csv"),
        "position_path": str(output_dir / "positions.csv"),
        "equity_curve_path": str(output_dir / "equity_curve.csv"),
        "rolling_3y_path": str(output_dir / "rolling_3y.csv"),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "metrics.json", payload)
    write_rows(output_dir / "monthly.csv", monthly_rows)
    write_rows(output_dir / "actions.csv", action_rows)
    write_rows(output_dir / "trade_log.csv", trade_rows)
    write_rows(output_dir / "positions.csv", position_rows)
    write_rows(output_dir / "equity_curve.csv", curve)
    write_rows(output_dir / "rolling_3y.csv", rolling)
    write_text(output_dir / "validation_report.md", render_report(payload))
    return payload


def render_report(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Position-Risk Weekly Validation",
            "",
            "Daily stop checks and weekly relative-performance checks on monthly holding books.",
            "",
            f"- Portfolio: `{payload.get('portfolio_kind')}`",
            f"- CAGR: {safe_float(payload.get('cagr')):.2%}",
            f"- Sharpe: {safe_float(payload.get('sharpe')):.3f}",
            f"- MaxDD: {safe_float(payload.get('max_dd')):.2%}",
            f"- Price coverage: {safe_float(payload.get('price_coverage')):.2%}",
            f"- Exits: {int(safe_float(payload.get('exit_count')))}",
            f"- Trims: {int(safe_float(payload.get('trim_count')))}",
            f"- Trade log: `{payload.get('trade_log_path')}`",
            "",
            "This validates whether monthly proxy exits are observable on cached daily prices. "
            "It is stricter than a month-end cap, but still not live execution evidence.",
            "",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--holdings", required=True)
    parser.add_argument("--period-map", required=True)
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--portfolio-kind", default="main")
    parser.add_argument("--benchmark-ticker", default="SPY")
    parser.add_argument("--hard-stop", type=float, default=-0.08)
    parser.add_argument("--trailing-stop", type=float, default=-0.15)
    parser.add_argument("--trailing-activation", type=float, default=0.15)
    parser.add_argument("--relative-trim-threshold", type=float, default=-0.06)
    parser.add_argument("--relative-exit-threshold", type=float, default=-0.12)
    parser.add_argument("--relative-trim-weight", type=float, default=0.50)
    parser.add_argument("--cost-bps", type=float, default=25.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = replay(
        holdings_path=repo_path(args.holdings),
        period_map_path=repo_path(args.period_map),
        price_cache=repo_path(args.price_cache),
        output_dir=repo_path(args.output_dir),
        portfolio_kind=args.portfolio_kind,
        benchmark_ticker=args.benchmark_ticker,
        hard_stop=args.hard_stop,
        trailing_stop=args.trailing_stop,
        trailing_activation=args.trailing_activation,
        relative_trim_threshold=args.relative_trim_threshold,
        relative_exit_threshold=args.relative_exit_threshold,
        trim_weight=args.relative_trim_weight,
        cost_bps=args.cost_bps,
    )
    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
