#!/usr/bin/env python3
"""Replay monthly targets through a less churny account-aware execution policy.

The current broker-ledger replay follows target weights mechanically. This
research sidecar tests whether the same alpha target books perform better when
execution rules are closer to a real operator:

- small target-weight changes are ignored
- recent positions are not forced out immediately unless they are losing
- profitable winners can drift above target before being trimmed
- new entries can be staged instead of bought at full target immediately

Defaults are intentionally conservative and production defaults are unchanged.
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

from tools.run_broker_ledger_replay import (
    CASH_TICKERS,
    LedgerState,
    account_equity,
    calc_metrics,
    execute_order,
    fill_price,
    latest_account_state,
    load_price_series,
    mark_dates_for_period,
    normalize_targets,
    price_at_or_before,
    read_csv,
    resolve_concentrated_champion_filters,
    target_period_ends,
    weight_book_diagnostics,
)


DEFAULT_OUT_DIR = "outputs/broker_execution_policy_replay"


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


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def held_days(holding_since: dict[str, pd.Timestamp], ticker: str, date: pd.Timestamp) -> int:
    start = holding_since.get(ticker)
    if start is None:
        return 0
    return max(0, int((pd.Timestamp(date).normalize() - pd.Timestamp(start).normalize()).days))


def unrealized_return(state: LedgerState, ticker: str, price: float) -> float:
    basis = safe_float(state.cost_basis.get(ticker), price)
    if basis <= 0:
        return 0.0
    return float(price / basis - 1.0)


def execute_policy_order(
    *,
    state: LedgerState,
    ticker: str,
    side: str,
    desired_qty: float,
    price: float,
    cost_bps: float,
    integer_shares: bool,
    fill_dt: pd.Timestamp,
    signal_dt: pd.Timestamp,
    reason: str,
    target_weight: float | None,
    holding_since: dict[str, pd.Timestamp],
) -> dict[str, Any] | None:
    before_qty = float(state.shares.get(ticker, 0.0))
    order = execute_order(
        state=state,
        ticker=ticker,
        side=side,
        desired_qty=desired_qty,
        price=price,
        cost_bps=cost_bps,
        integer_shares=integer_shares,
    )
    if not order:
        return None
    after_qty = float(state.shares.get(ticker, 0.0))
    if before_qty <= 1e-12 and after_qty > 1e-12:
        holding_since[ticker] = pd.Timestamp(fill_dt).normalize()
    if after_qty <= 1e-12:
        holding_since.pop(ticker, None)
    order.update(
        {
            "date": pd.Timestamp(fill_dt).date().isoformat(),
            "signal_date": pd.Timestamp(signal_dt).date().isoformat(),
            "reason": reason,
            "target_weight": "" if target_weight is None else float(target_weight),
            "fill_mode": "next_close",
        }
    )
    return order


def maybe_exit_missing_target(
    *,
    state: LedgerState,
    ticker: str,
    price: float,
    current_weight: float,
    fill_dt: pd.Timestamp,
    holding_since: dict[str, pd.Timestamp],
    min_holding_days: int,
    early_exit_loss_tolerance: float,
    stale_exit_weight: float,
) -> tuple[bool, str]:
    ret = unrealized_return(state, ticker, price)
    age = held_days(holding_since, ticker, fill_dt)
    if age < int(min_holding_days) and ret >= float(early_exit_loss_tolerance):
        return False, "defer_target_exit_min_holding"
    if current_weight <= float(stale_exit_weight) and ret >= float(early_exit_loss_tolerance):
        return False, "defer_tiny_stale_position"
    return True, "target_exit_policy"


def replay(
    *,
    target_book: Path,
    price_cache: Path,
    output_dir: Path,
    portfolio_kind: str,
    starting_capital: float = 100000.0,
    fill_mode: str = "next_close",
    cost_bps: float = 25.0,
    integer_shares: bool = True,
    max_fill_lag_days: int = 7,
    buy_band: float = 0.02,
    sell_band: float = 0.03,
    min_holding_days: int = 63,
    early_exit_loss_tolerance: float = -0.08,
    winner_return_threshold: float = 0.20,
    winner_overweight_band: float = 0.08,
    new_entry_scale: float = 0.70,
    max_reasonable_weight_sum: float = 1.50,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    raw = read_csv(target_book)
    champion_filters, champion_filter_source, champion_filter_warning = resolve_concentrated_champion_filters(
        target_book=target_book,
        raw_targets=raw,
        portfolio_kind=portfolio_kind,
    )
    targets = normalize_targets(raw, portfolio_kind, champion_filters)
    if targets.empty:
        payload = {
            "status": "blocked",
            "reason": "target book is empty or invalid",
            "target_book": str(target_book),
            "target_book_filter": champion_filters,
            "target_book_filter_source": champion_filter_source,
            "target_book_filter_warning": champion_filter_warning,
        }
        write_json(output_dir / "metrics.json", payload)
        return payload
    weight_diag = weight_book_diagnostics(targets, max_reasonable_weight_sum)
    if int(weight_diag.get("invalid_weight_date_count") or 0) > 0:
        payload = {
            "status": "blocked",
            "reason": "target weight sum exceeds maximum reasonable exposure",
            "target_book": str(target_book),
            "target_book_filter": champion_filters,
            "target_book_filter_source": champion_filter_source,
            "target_book_filter_warning": champion_filter_warning,
            **weight_diag,
        }
        write_json(output_dir / "metrics.json", payload)
        return payload

    tickers = sorted({str(x).upper() for x in targets["ticker"].unique() if str(x).upper() not in CASH_TICKERS})
    prices = {ticker: load_price_series(price_cache, ticker) for ticker in tickers}
    prices = {ticker: frame for ticker, frame in prices.items() if not frame.empty}
    periods = target_period_ends(targets, price_cache)
    state = LedgerState(cash=float(starting_capital))
    holding_since: dict[str, pd.Timestamp] = {}
    trade_rows: list[dict[str, Any]] = []
    equity_rows: list[dict[str, Any]] = []
    holdings_rows: list[dict[str, Any]] = []
    cash_rows: list[dict[str, Any]] = []
    policy_rows: list[dict[str, Any]] = []

    for signal_dt in sorted(periods.keys()):
        signal_dt = pd.Timestamp(signal_dt).normalize()
        target = targets[targets["rebalance_date"].eq(signal_dt)].copy()
        if target.empty:
            continue
        fill_dt_by_ticker: dict[str, pd.Timestamp] = {}
        fill_px_by_ticker: dict[str, float] = {}
        all_relevant = set(target["ticker"].astype(str).str.upper()) | set(state.shares.keys())
        for ticker in sorted(all_relevant):
            if ticker in CASH_TICKERS:
                continue
            actual_dt, px = fill_price(prices, ticker, signal_dt, fill_mode, max_fill_lag_days)
            if actual_dt is not None and px is not None:
                fill_dt_by_ticker[ticker] = pd.Timestamp(actual_dt).normalize()
                fill_px_by_ticker[ticker] = float(px)
        if not fill_dt_by_ticker:
            continue
        fill_dt = min(fill_dt_by_ticker.values())
        current_equity, current_values = account_equity(state, prices, fill_dt)
        if current_equity <= 0:
            continue
        target_weights = {
            str(row.ticker).upper(): max(0.0, safe_float(row.weight))
            for row in target.itertuples(index=False)
            if str(row.ticker).upper() not in CASH_TICKERS
        }

        sell_adjustments: list[tuple[str, float, float, str, float | None]] = []
        buy_adjustments: list[tuple[str, float, float, str, float | None]] = []

        for ticker in sorted(set(state.shares.keys()) - set(target_weights.keys())):
            px = fill_px_by_ticker.get(ticker)
            if px is None:
                continue
            current_value = float(state.shares.get(ticker, 0.0)) * px
            current_weight = current_value / current_equity if current_equity > 0 else 0.0
            should_exit, reason = maybe_exit_missing_target(
                state=state,
                ticker=ticker,
                price=px,
                current_weight=current_weight,
                fill_dt=fill_dt,
                holding_since=holding_since,
                min_holding_days=min_holding_days,
                early_exit_loss_tolerance=early_exit_loss_tolerance,
                stale_exit_weight=sell_band,
            )
            policy_rows.append(
                {
                    "date": fill_dt.date().isoformat(),
                    "signal_date": signal_dt.date().isoformat(),
                    "ticker": ticker,
                    "decision": "sell" if should_exit else "hold",
                    "reason": reason,
                    "current_weight": current_weight,
                    "target_weight": 0.0,
                    "unrealized_return": unrealized_return(state, ticker, px),
                    "held_days": held_days(holding_since, ticker, fill_dt),
                }
            )
            if should_exit:
                sell_adjustments.append((ticker, float(state.shares.get(ticker, 0.0)), px, reason, 0.0))

        current_equity, current_values = account_equity(state, prices, fill_dt)
        for ticker, target_weight in target_weights.items():
            px = fill_px_by_ticker.get(ticker)
            if px is None:
                continue
            current_qty = float(state.shares.get(ticker, 0.0))
            current_value = current_qty * px
            current_weight = current_value / current_equity if current_equity > 0 else 0.0
            target_value = target_weight * current_equity
            diff_weight = target_weight - current_weight
            ret = unrealized_return(state, ticker, px)
            age = held_days(holding_since, ticker, fill_dt)
            if current_qty <= 1e-12:
                scaled_value = target_value * max(0.0, min(1.0, float(new_entry_scale)))
                if scaled_value < max(25.0, current_equity * 0.0005):
                    continue
                buy_adjustments.append((ticker, scaled_value / px, px, "staged_new_entry", target_weight))
                policy_rows.append(
                    {
                        "date": fill_dt.date().isoformat(),
                        "signal_date": signal_dt.date().isoformat(),
                        "ticker": ticker,
                        "decision": "buy",
                        "reason": "staged_new_entry",
                        "current_weight": current_weight,
                        "target_weight": target_weight,
                        "unrealized_return": ret,
                        "held_days": age,
                    }
                )
                continue
            diff_value = target_value - current_value
            if diff_value > 0:
                if diff_weight < float(buy_band):
                    reason = "skip_buy_inside_band"
                    policy_rows.append(
                        {
                            "date": fill_dt.date().isoformat(),
                            "signal_date": signal_dt.date().isoformat(),
                            "ticker": ticker,
                            "decision": "hold",
                            "reason": reason,
                            "current_weight": current_weight,
                            "target_weight": target_weight,
                            "unrealized_return": ret,
                            "held_days": age,
                        }
                    )
                    continue
                buy_adjustments.append((ticker, diff_value / px, px, "target_buy_above_band", target_weight))
            elif diff_value < 0:
                if abs(diff_weight) < float(sell_band):
                    reason = "skip_sell_inside_band"
                    policy_rows.append(
                        {
                            "date": fill_dt.date().isoformat(),
                            "signal_date": signal_dt.date().isoformat(),
                            "ticker": ticker,
                            "decision": "hold",
                            "reason": reason,
                            "current_weight": current_weight,
                            "target_weight": target_weight,
                            "unrealized_return": ret,
                            "held_days": age,
                        }
                    )
                    continue
                if ret >= float(winner_return_threshold) and current_weight <= target_weight + float(winner_overweight_band):
                    reason = "skip_winner_trim"
                    policy_rows.append(
                        {
                            "date": fill_dt.date().isoformat(),
                            "signal_date": signal_dt.date().isoformat(),
                            "ticker": ticker,
                            "decision": "hold",
                            "reason": reason,
                            "current_weight": current_weight,
                            "target_weight": target_weight,
                            "unrealized_return": ret,
                            "held_days": age,
                        }
                    )
                    continue
                sell_adjustments.append((ticker, abs(diff_value) / px, px, "target_sell_above_band", target_weight))

        for ticker, qty, px, reason, target_weight in sorted(sell_adjustments, key=lambda row: row[1] * row[2], reverse=True):
            order = execute_policy_order(
                state=state,
                ticker=ticker,
                side="SELL",
                desired_qty=qty,
                price=px,
                cost_bps=cost_bps,
                integer_shares=integer_shares,
                fill_dt=fill_dt,
                signal_dt=signal_dt,
                reason=reason,
                target_weight=target_weight,
                holding_since=holding_since,
            )
            if order:
                trade_rows.append(order)

        current_equity, _ = account_equity(state, prices, fill_dt)
        for ticker, qty, px, reason, target_weight in sorted(buy_adjustments, key=lambda row: row[1] * row[2], reverse=True):
            if state.cash <= 25.0:
                break
            order = execute_policy_order(
                state=state,
                ticker=ticker,
                side="BUY",
                desired_qty=qty,
                price=px,
                cost_bps=cost_bps,
                integer_shares=integer_shares,
                fill_dt=fill_dt,
                signal_dt=signal_dt,
                reason=reason,
                target_weight=target_weight,
                holding_since=holding_since,
            )
            if order:
                trade_rows.append(order)

        equity_after, _values_after = account_equity(state, prices, fill_dt)
        cash_rows.append(
            {
                "date": fill_dt.date().isoformat(),
                "cash_usd": float(state.cash),
                "equity_usd": float(equity_after),
                "cash_weight": float(state.cash / equity_after) if equity_after > 0 else np.nan,
            }
        )
        period_end = periods.get(signal_dt, fill_dt)
        active_tickers = set(state.shares.keys()) | set(target_weights.keys())
        period_marks = mark_dates_for_period(active_tickers, prices, fill_dt, period_end)
        if not period_marks:
            period_marks = [fill_dt]
        for date in period_marks:
            equity, values = account_equity(state, prices, date)
            equity_rows.append(
                {
                    "date": pd.Timestamp(date).date().isoformat(),
                    "equity_usd": float(equity),
                    "cash_usd": float(state.cash),
                    "cash_weight": float(state.cash / equity) if equity > 0 else np.nan,
                    "stock_value_usd": float(sum(values.values())),
                    "position_count": int(sum(1 for qty in state.shares.values() if abs(qty) > 1e-12)),
                    "fill_mode": fill_mode,
                }
            )
            for ticker, value in values.items():
                px = price_at_or_before(prices, ticker, date)
                holdings_rows.append(
                    {
                        "date": pd.Timestamp(date).date().isoformat(),
                        "ticker": ticker,
                        "shares": float(state.shares.get(ticker, 0.0)),
                        "price": px if px is not None else np.nan,
                        "market_value_usd": float(value),
                        "weight": float(value / equity) if equity > 0 else np.nan,
                        "cost_basis": float(state.cost_basis.get(ticker, np.nan)),
                        "unrealized_pnl_usd": float(value - state.shares.get(ticker, 0.0) * state.cost_basis.get(ticker, 0.0)),
                        "held_days": held_days(holding_since, ticker, pd.Timestamp(date)),
                    }
                )

    if not equity_rows:
        payload = {
            "status": "blocked",
            "reason": "no account equity rows generated; price cache may be missing target tickers",
            "target_book": str(target_book),
            "price_cache": str(price_cache),
            "portfolio_kind": portfolio_kind,
            "valid_for_production": False,
            "target_book_filter": champion_filters,
            "target_book_filter_source": champion_filter_source,
            "target_book_filter_warning": champion_filter_warning,
            **weight_diag,
        }
        write_json(output_dir / "metrics.json", payload)
        return payload

    equity_df = pd.DataFrame(equity_rows).drop_duplicates("date", keep="last").sort_values("date")
    trades_df = pd.DataFrame(trade_rows)
    holdings_df = pd.DataFrame(holdings_rows)
    cash_df = pd.DataFrame(cash_rows)
    policy_df = pd.DataFrame(policy_rows)
    metrics = calc_metrics(equity_df, trades_df, starting_capital)
    metrics.update(
        {
            "portfolio_kind": portfolio_kind,
            "candidate_id": f"{portfolio_kind}_broker_execution_policy_replay",
            "metric_mode": "broker_ledger_execution_policy_next_close",
            "data_mode": "monthly_targets_account_aware_execution",
            "fill_mode": fill_mode,
            "price_mode": "adjusted_close",
            "integer_shares": bool(integer_shares),
            "cost_bps_per_side": float(cost_bps),
            "target_book": str(target_book),
            "target_book_filter": champion_filters,
            "target_book_filter_source": champion_filter_source,
            "target_book_filter_warning": champion_filter_warning,
            "price_cache": str(price_cache),
            "buy_band": float(buy_band),
            "sell_band": float(sell_band),
            "min_holding_days": int(min_holding_days),
            "early_exit_loss_tolerance": float(early_exit_loss_tolerance),
            "winner_return_threshold": float(winner_return_threshold),
            "winner_overweight_band": float(winner_overweight_band),
            "new_entry_scale": float(new_entry_scale),
            "policy_decision_count": int(len(policy_df)),
            "broker_ledger_valid": bool(metrics.get("status") == "completed" and fill_mode == "next_close" and integer_shares),
            "valid_for_production": False,
            "research_only": True,
            "promotion_note": "Research-only account-aware execution challenger; promotion requires official broker-ledger target gates, stress review, and human approval.",
            "max_fill_lag_days": int(max_fill_lag_days),
            **weight_diag,
        }
    )
    equity_df.to_csv(output_dir / "equity_curve.csv", index=False)
    trades_df.to_csv(output_dir / "trades.csv", index=False)
    holdings_df.to_csv(output_dir / "holdings_daily.csv", index=False)
    cash_df.to_csv(output_dir / "cash_ledger.csv", index=False)
    policy_df.to_csv(output_dir / "policy_decisions.csv", index=False)
    if not equity_df.empty:
        latest_date = pd.Timestamp(pd.to_datetime(equity_df["date"], errors="coerce").dropna().max()).normalize()
        account_state, latest_positions = latest_account_state(
            state=state,
            prices=prices,
            as_of_date=latest_date,
            metrics=metrics,
            trades=trades_df,
            portfolio_kind=portfolio_kind,
            starting_capital=starting_capital,
            fill_mode=fill_mode,
            cost_bps=cost_bps,
            integer_shares=integer_shares,
        )
        latest_positions.to_csv(output_dir / "positions_latest.csv", index=False)
        write_json(output_dir / "account_state_latest.json", account_state)
    write_json(output_dir / "metrics.json", metrics)
    (output_dir / "replay_report.md").write_text(render_report(metrics), encoding="utf-8")
    return metrics


def render_report(metrics: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Broker Execution-Policy Replay",
            "",
            "Account-aware replay of monthly target books with churn controls.",
            "",
            f"- Portfolio: `{metrics.get('portfolio_kind')}`",
            f"- Status: `{metrics.get('status')}`",
            f"- Metric mode: `{metrics.get('metric_mode')}`",
            f"- CAGR: {safe_float(metrics.get('cagr')):.2%}",
            f"- Sharpe: {safe_float(metrics.get('sharpe')):.3f}",
            f"- MaxDD: {safe_float(metrics.get('max_dd')):.2%}",
            f"- Avg cash: {safe_float(metrics.get('avg_cash_weight')):.2%}",
            f"- Total trades: {int(safe_float(metrics.get('trade_count'), 0))}",
            f"- Broker-ledger valid: `{str(metrics.get('broker_ledger_valid')).lower()}`",
            f"- Valid for production evidence: `{str(metrics.get('valid_for_production')).lower()}`",
            "",
            "This is not a production policy by itself. It is a broker-ledger challenger for reducing churn and preserving winners.",
            "",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-book", required=True)
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--portfolio-kind", default="main")
    parser.add_argument("--starting-capital", type=float, default=100000.0)
    parser.add_argument("--fill-mode", choices=["next_close", "next_open", "same_close"], default="next_close")
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--no-integer-shares", action="store_true")
    parser.add_argument("--max-fill-lag-days", type=int, default=7)
    parser.add_argument("--buy-band", type=float, default=0.02)
    parser.add_argument("--sell-band", type=float, default=0.03)
    parser.add_argument("--min-holding-days", type=int, default=63)
    parser.add_argument("--early-exit-loss-tolerance", type=float, default=-0.08)
    parser.add_argument("--winner-return-threshold", type=float, default=0.20)
    parser.add_argument("--winner-overweight-band", type=float, default=0.08)
    parser.add_argument("--new-entry-scale", type=float, default=0.70)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = replay(
        target_book=repo_path(args.target_book),
        price_cache=repo_path(args.price_cache),
        output_dir=repo_path(args.output_dir),
        portfolio_kind=args.portfolio_kind,
        starting_capital=args.starting_capital,
        fill_mode=args.fill_mode,
        cost_bps=args.cost_bps,
        integer_shares=not args.no_integer_shares,
        max_fill_lag_days=args.max_fill_lag_days,
        buy_band=args.buy_band,
        sell_band=args.sell_band,
        min_holding_days=args.min_holding_days,
        early_exit_loss_tolerance=args.early_exit_loss_tolerance,
        winner_return_threshold=args.winner_return_threshold,
        winner_overweight_band=args.winner_overweight_band,
        new_entry_scale=args.new_entry_scale,
    )
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
