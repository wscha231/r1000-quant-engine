#!/usr/bin/env python3
"""Replay position-risk proxy rules through a broker-style daily ledger.

Monthly position-risk proxy results can be too optimistic because they know the
period's forward return. This runner converts the proxy idea into observable
rules:

- monthly target books are filled with next-close account-ledger orders;
- daily close data triggers hard/trailing/relative-risk signals;
- risk signals are also filled at the next available close;
- shares, cash, fees, no leverage, and daily equity are tracked.

The output is production-compatible evidence for the execution assumptions, but
it still depends on monthly target books. It does not call a broker API.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "tools"))

from run_broker_ledger_replay import (  # noqa: E402
    CASH_TICKERS,
    LedgerState,
    account_equity,
    calc_metrics,
    execute_order,
    fill_price,
    latest_account_state,
    mark_dates_for_period,
    normalize_targets,
    price_at_or_before,
    read_csv,
    resolve_concentrated_champion_filters,
    target_period_ends,
    weight_book_diagnostics,
)
from run_position_aware_risk_replay import is_long_hold_protected  # noqa: E402
from run_weekly_evaluation import load_price_series  # noqa: E402


DEFAULT_OUT_DIR = "outputs/broker_position_risk_replay"
DEFAULT_HARD_STOP = -0.12
DEFAULT_TRAILING_STOP = -0.20
DEFAULT_TRAILING_ACTIVATION = 0.25
DEFAULT_RELATIVE_TRIM_THRESHOLD = -0.10
DEFAULT_RELATIVE_EXIT_THRESHOLD = -0.20


@dataclass
class RiskMeta:
    entry_price: float
    entry_date: pd.Timestamp
    peak_price: float
    bench_entry_price: float
    trim_done: bool
    row: dict[str, Any]


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


def render_report(metrics: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Broker Position-Risk Replay",
            "",
            "Account-ledger conversion of monthly proxy risk rules.",
            "",
            f"- Portfolio: `{metrics.get('portfolio_kind')}`",
            f"- Status: `{metrics.get('status')}`",
            f"- Metric mode: `{metrics.get('metric_mode')}`",
            f"- CAGR: {safe_float(metrics.get('cagr')):.2%}",
            f"- Sharpe: {safe_float(metrics.get('sharpe')):.3f}",
            f"- MaxDD: {safe_float(metrics.get('max_dd')):.2%}",
            f"- Avg cash: {safe_float(metrics.get('avg_cash_weight')):.2%}",
            f"- Risk exits: {int(safe_float(metrics.get('risk_exit_count')))}",
            f"- Risk trims: {int(safe_float(metrics.get('risk_trim_count')))}",
            f"- Total trades: {int(safe_float(metrics.get('trade_count')))}",
            f"- Valid for production evidence: `{str(metrics.get('valid_for_production')).lower()}`",
            "",
            "No forward-return labels are used for exit timing. Signals are detected from daily closes and filled at the next close.",
            "",
        ]
    )


def benchmark_return(prices: dict[str, pd.DataFrame], benchmark_ticker: str, entry_price: float, date: pd.Timestamp) -> float:
    if entry_price <= 0:
        return 0.0
    px = price_at_or_before(prices, benchmark_ticker, date)
    if px is None or px <= 0:
        return 0.0
    return float(px) / float(entry_price) - 1.0


def should_check_relative(date: pd.Timestamp, period_end: pd.Timestamp) -> bool:
    return pd.Timestamp(date).weekday() == 4 or pd.Timestamp(date).normalize() >= pd.Timestamp(period_end).normalize()


def risk_signal(
    *,
    ticker: str,
    date: pd.Timestamp,
    close_price: float,
    meta: RiskMeta,
    prices: dict[str, pd.DataFrame],
    benchmark_ticker: str,
    period_end: pd.Timestamp,
    hard_stop: float,
    trailing_stop: float,
    trailing_activation: float,
    relative_trim_threshold: float,
    relative_exit_threshold: float,
    enable_distribution_exit: bool = True,
) -> tuple[str, str, float, dict[str, Any]] | None:
    if close_price <= 0 or meta.entry_price <= 0:
        return None
    meta.peak_price = max(meta.peak_price, close_price)
    total_return = close_price / meta.entry_price - 1.0
    drawdown_from_peak = close_price / max(meta.peak_price, 1e-12) - 1.0
    bench_return = benchmark_return(prices, benchmark_ticker, meta.bench_entry_price, date)
    relative_return = (1.0 + total_return) / max(1.0 + bench_return, 1e-8) - 1.0
    protected = is_long_hold_protected(meta.row, total_return, relative_return)
    context = {
        "price_return": total_return,
        "drawdown_from_peak": drawdown_from_peak,
        "benchmark_return": bench_return,
        "relative_return": relative_return,
        "protected": protected,
    }
    if total_return <= hard_stop:
        return "SELL", "daily_hard_stop_exit", 1.0, context
    if total_return >= trailing_activation and drawdown_from_peak <= trailing_stop:
        return "SELL", "daily_trailing_stop_exit", 1.0, context
    if should_check_relative(date, period_end):
        exit_risk = max(
            safe_float(meta.row.get("explosion_exit_score"), 0.0),
            safe_float(meta.row.get("stage2_overext_penalty"), 0.0),
            safe_float(meta.row.get("risk_penalty"), 0.0),
        )
        rs_accel = safe_float(meta.row.get("rs_acceleration_score"), 0.0)
        if enable_distribution_exit and exit_risk >= 0.85 and rs_accel < 0.0 and total_return < -0.02:
            return "SELL", "weekly_distribution_exit", 1.0, context
        if relative_return <= relative_exit_threshold and not protected:
            return "SELL", "weekly_relative_exit", 1.0, context
        if relative_return <= relative_trim_threshold and not meta.trim_done:
            return "SELL", "weekly_relative_trim", 0.5, context
    return None


def metadata_for_targets(
    target: pd.DataFrame,
    state: LedgerState,
    prices: dict[str, pd.DataFrame],
    benchmark_ticker: str,
    fill_dt: pd.Timestamp,
    existing: dict[str, RiskMeta],
) -> dict[str, RiskMeta]:
    out = {ticker: meta for ticker, meta in existing.items() if ticker in state.shares}
    bench_px = price_at_or_before(prices, benchmark_ticker, fill_dt) or 0.0
    for row in target.itertuples(index=False):
        ticker = str(row.ticker).upper()
        if ticker in CASH_TICKERS or ticker not in state.shares:
            continue
        px = price_at_or_before(prices, ticker, fill_dt)
        if px is None or px <= 0:
            continue
        row_dict = row._asdict()
        prior = out.get(ticker)
        entry_price = safe_float(state.cost_basis.get(ticker), px)
        out[ticker] = RiskMeta(
            entry_price=entry_price,
            entry_date=fill_dt,
            peak_price=max(px, prior.peak_price if prior else px),
            bench_entry_price=prior.bench_entry_price if prior else bench_px,
            trim_done=prior.trim_done if prior else False,
            row=row_dict,
        )
    return out


def execute_rebalance(
    *,
    state: LedgerState,
    target: pd.DataFrame,
    prices: dict[str, pd.DataFrame],
    signal_dt: pd.Timestamp,
    fill_mode: str,
    cost_bps: float,
    integer_shares: bool,
    max_fill_lag_days: int,
) -> tuple[pd.Timestamp | None, list[dict[str, Any]], dict[str, float]]:
    fill_dt_by_ticker: dict[str, pd.Timestamp] = {}
    fill_px_by_ticker: dict[str, float] = {}
    target_tickers = set(target["ticker"].astype(str).str.upper())
    for ticker in sorted((target_tickers | set(state.shares.keys())) - CASH_TICKERS):
        actual_dt, px = fill_price(prices, ticker, signal_dt, fill_mode, max_fill_lag_days)
        if actual_dt is not None and px is not None:
            fill_dt_by_ticker[ticker] = pd.Timestamp(actual_dt).normalize()
            fill_px_by_ticker[ticker] = float(px)
    if not fill_dt_by_ticker:
        return None, [], {}
    fill_dt = min(fill_dt_by_ticker.values())
    trade_rows: list[dict[str, Any]] = []
    target_weights = {
        str(row.ticker).upper(): safe_float(row.weight)
        for row in target.itertuples(index=False)
        if str(row.ticker).upper() not in CASH_TICKERS
    }
    for ticker in sorted(set(state.shares.keys()) - set(target_weights.keys())):
        px = fill_px_by_ticker.get(ticker)
        if px is None:
            continue
        order = execute_order(
            state=state,
            ticker=ticker,
            side="SELL",
            desired_qty=float(state.shares.get(ticker, 0.0)),
            price=px,
            cost_bps=cost_bps,
            integer_shares=integer_shares,
        )
        if order:
            order.update({"date": fill_dt.date().isoformat(), "signal_date": signal_dt.date().isoformat(), "reason": "target_exit", "fill_mode": fill_mode})
            trade_rows.append(order)
    current_equity, _ = account_equity(state, prices, fill_dt)
    adjustments: list[tuple[str, float, float, float]] = []
    for ticker, target_weight in target_weights.items():
        px = fill_px_by_ticker.get(ticker)
        if px is None:
            continue
        current_qty = float(state.shares.get(ticker, 0.0))
        current_value = current_qty * px
        target_value = max(0.0, float(target_weight) * current_equity)
        diff_value = target_value - current_value
        if abs(diff_value) < max(25.0, current_equity * 0.0005):
            continue
        adjustments.append((ticker, float(target_weight), float(diff_value), float(px)))
    adjustments = sorted(adjustments, key=lambda row: (row[2] > 0, abs(row[2])))
    for ticker, target_weight, diff_value, px in adjustments:
        side = "BUY" if diff_value > 0 else "SELL"
        order = execute_order(
            state=state,
            ticker=ticker,
            side=side,
            desired_qty=abs(diff_value) / px,
            price=px,
            cost_bps=cost_bps,
            integer_shares=integer_shares,
        )
        if order:
            order.update({"date": fill_dt.date().isoformat(), "signal_date": signal_dt.date().isoformat(), "reason": "target_rebalance", "target_weight": target_weight, "fill_mode": fill_mode})
            trade_rows.append(order)
    return fill_dt, trade_rows, target_weights


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
    max_reasonable_weight_sum: float = 1.05,
    max_fill_lag_days: int = 7,
    benchmark_ticker: str = "SPY",
    hard_stop: float = DEFAULT_HARD_STOP,
    trailing_stop: float = DEFAULT_TRAILING_STOP,
    trailing_activation: float = DEFAULT_TRAILING_ACTIVATION,
    relative_trim_threshold: float = DEFAULT_RELATIVE_TRIM_THRESHOLD,
    relative_exit_threshold: float = DEFAULT_RELATIVE_EXIT_THRESHOLD,
    enable_distribution_exit: bool = True,
    candidate_id: str | None = None,
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
            "valid_for_production": False,
            "target_book_filter": champion_filters,
            "target_book_filter_source": champion_filter_source,
            "target_book_filter_warning": champion_filter_warning,
            **weight_diag,
        }
        write_json(output_dir / "metrics.json", payload)
        return payload

    tickers = sorted({str(x).upper() for x in targets["ticker"].unique() if str(x).upper() not in CASH_TICKERS})
    benchmark_ticker = benchmark_ticker.upper()
    prices = {ticker: load_price_series(price_cache, ticker) for ticker in sorted(set(tickers + [benchmark_ticker]))}
    prices = {ticker: px for ticker, px in prices.items() if not px.empty}
    periods = target_period_ends(targets, price_cache)
    state = LedgerState(cash=float(starting_capital))
    risk_meta: dict[str, RiskMeta] = {}
    pending: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    risk_action_rows: list[dict[str, Any]] = []
    equity_rows: list[dict[str, Any]] = []
    holdings_rows: list[dict[str, Any]] = []
    cash_rows: list[dict[str, Any]] = []

    for signal_dt in sorted(periods.keys()):
        target = targets[targets["rebalance_date"].eq(signal_dt)].copy()
        if target.empty:
            continue
        fill_dt, rebalance_trades, target_weights = execute_rebalance(
            state=state,
            target=target,
            prices=prices,
            signal_dt=signal_dt,
            fill_mode=fill_mode,
            cost_bps=cost_bps,
            integer_shares=integer_shares,
            max_fill_lag_days=max_fill_lag_days,
        )
        if fill_dt is None:
            continue
        trade_rows.extend(rebalance_trades)
        risk_meta = metadata_for_targets(target, state, prices, benchmark_ticker, fill_dt, risk_meta)
        period_end = periods.get(signal_dt, fill_dt)
        active_tickers = set(state.shares.keys()) | set(target_weights.keys())
        period_marks = mark_dates_for_period(active_tickers, prices, fill_dt, period_end)
        if not period_marks:
            period_marks = [fill_dt]
        pending_keys: set[str] = {str(row.get("ticker")) for row in pending}
        for date in period_marks:
            date = pd.Timestamp(date).normalize()
            due = [row for row in pending if pd.Timestamp(row["fill_date"]).normalize() <= date]
            pending = [row for row in pending if pd.Timestamp(row["fill_date"]).normalize() > date]
            for action in due:
                ticker = str(action["ticker"]).upper()
                held = float(state.shares.get(ticker, 0.0))
                if held <= 1e-12:
                    pending_keys.discard(ticker)
                    continue
                qty = held * safe_float(action.get("sell_fraction"), 1.0)
                order = execute_order(
                    state=state,
                    ticker=ticker,
                    side="SELL",
                    desired_qty=qty,
                    price=safe_float(action.get("fill_price")),
                    cost_bps=cost_bps,
                    integer_shares=integer_shares,
                )
                pending_keys.discard(ticker)
                if order:
                    order.update(
                        {
                            "date": pd.Timestamp(action["fill_date"]).date().isoformat(),
                            "signal_date": pd.Timestamp(action["signal_date"]).date().isoformat(),
                            "reason": action.get("reason"),
                            "risk_rule_action": action.get("risk_rule_action"),
                            "fill_mode": fill_mode,
                        }
                    )
                    trade_rows.append(order)
                    risk_action_rows.append({**action, **{k: order.get(k) for k in ["quantity", "gross_value", "fee_usd", "cash_after", "shares_after"]}})
                    if order.get("shares_after", 0.0) <= 1e-12:
                        risk_meta.pop(ticker, None)
                    elif ticker in risk_meta and action.get("risk_rule_action") == "weekly_relative_trim":
                        risk_meta[ticker].trim_done = True

            equity, values = account_equity(state, prices, date)
            equity_rows.append(
                {
                    "date": date.date().isoformat(),
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
                        "date": date.date().isoformat(),
                        "ticker": ticker,
                        "shares": float(state.shares.get(ticker, 0.0)),
                        "price": px if px is not None else np.nan,
                        "market_value_usd": float(value),
                        "weight": float(value / equity) if equity > 0 else np.nan,
                        "cost_basis": float(state.cost_basis.get(ticker, np.nan)),
                        "unrealized_pnl_usd": float(value - state.shares.get(ticker, 0.0) * state.cost_basis.get(ticker, 0.0)),
                    }
                )

            for ticker in sorted(list(state.shares.keys())):
                if ticker in pending_keys:
                    continue
                meta = risk_meta.get(ticker)
                px = price_at_or_before(prices, ticker, date)
                if meta is None or px is None:
                    continue
                signal = risk_signal(
                    ticker=ticker,
                    date=date,
                    close_price=px,
                    meta=meta,
                    prices=prices,
                    benchmark_ticker=benchmark_ticker,
                    period_end=period_end,
                    hard_stop=hard_stop,
                    trailing_stop=trailing_stop,
                    trailing_activation=trailing_activation,
                    relative_trim_threshold=relative_trim_threshold,
                    relative_exit_threshold=relative_exit_threshold,
                    enable_distribution_exit=enable_distribution_exit,
                )
                if signal is None:
                    continue
                side, reason, sell_fraction, context = signal
                risk_fill_dt, risk_px = fill_price(prices, ticker, date, fill_mode, max_fill_lag_days)
                if risk_fill_dt is None or risk_px is None or pd.Timestamp(risk_fill_dt).normalize() > pd.Timestamp(period_end).normalize():
                    continue
                pending.append(
                    {
                        "ticker": ticker,
                        "side": side,
                        "reason": reason,
                        "risk_rule_action": reason,
                        "signal_date": date,
                        "fill_date": pd.Timestamp(risk_fill_dt).normalize(),
                        "fill_price": float(risk_px),
                        "sell_fraction": float(sell_fraction),
                        "portfolio_kind": portfolio_kind,
                        **context,
                    }
                )
                pending_keys.add(ticker)

            equity, _values = account_equity(state, prices, date)
            cash_rows.append({"date": date.date().isoformat(), "cash_usd": float(state.cash), "equity_usd": float(equity), "cash_weight": float(state.cash / equity) if equity > 0 else np.nan})

    equity_df = pd.DataFrame(equity_rows).drop_duplicates("date", keep="last").sort_values("date")
    trades_df = pd.DataFrame(trade_rows)
    holdings_df = pd.DataFrame(holdings_rows)
    cash_df = pd.DataFrame(cash_rows)
    risk_actions_df = pd.DataFrame(risk_action_rows)
    metrics = calc_metrics(equity_df, trades_df, starting_capital)
    metrics.update(
        {
            "portfolio_kind": portfolio_kind,
            "candidate_id": candidate_id or f"{portfolio_kind}_broker_position_risk_replay",
            "metric_mode": "broker_ledger_position_risk_next_close",
            "data_mode": "daily_price_path_account_ledger",
            "fill_mode": fill_mode,
            "price_mode": "adjusted_close",
            "integer_shares": bool(integer_shares),
            "cost_bps_per_side": float(cost_bps),
            "target_book": str(target_book),
            "target_book_filter": champion_filters,
            "target_book_filter_source": champion_filter_source,
            "target_book_filter_warning": champion_filter_warning,
            "price_cache": str(price_cache),
            "benchmark_ticker": benchmark_ticker,
            "hard_stop": hard_stop,
            "trailing_stop": trailing_stop,
            "trailing_activation": trailing_activation,
            "relative_trim_threshold": relative_trim_threshold,
            "relative_exit_threshold": relative_exit_threshold,
            "enable_distribution_exit": bool(enable_distribution_exit),
            "risk_exit_count": int(sum(1 for row in risk_action_rows if "exit" in str(row.get("reason", "")))),
            "risk_trim_count": int(sum(1 for row in risk_action_rows if "trim" in str(row.get("reason", "")))),
            "valid_for_production": bool(metrics.get("status") == "completed" and fill_mode == "next_close" and integer_shares),
            "promotion_note": "Account-ledger conversion of proxy risk rules. Promotion still requires target gates, stress review, and human approval.",
            "max_fill_lag_days": int(max_fill_lag_days),
            **weight_diag,
        }
    )
    equity_df.to_csv(output_dir / "equity_curve.csv", index=False)
    trades_df.to_csv(output_dir / "trades.csv", index=False)
    holdings_df.to_csv(output_dir / "holdings_daily.csv", index=False)
    cash_df.to_csv(output_dir / "cash_ledger.csv", index=False)
    risk_actions_df.to_csv(output_dir / "risk_actions.csv", index=False)
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
    parser.add_argument("--benchmark-ticker", default="SPY")
    parser.add_argument("--hard-stop", type=float, default=DEFAULT_HARD_STOP)
    parser.add_argument("--trailing-stop", type=float, default=DEFAULT_TRAILING_STOP)
    parser.add_argument("--trailing-activation", type=float, default=DEFAULT_TRAILING_ACTIVATION)
    parser.add_argument("--relative-trim-threshold", type=float, default=DEFAULT_RELATIVE_TRIM_THRESHOLD)
    parser.add_argument("--relative-exit-threshold", type=float, default=DEFAULT_RELATIVE_EXIT_THRESHOLD)
    parser.add_argument("--disable-distribution-exit", action="store_true", help="Disable weekly distribution exits so only hard/trailing/relative rules can fire.")
    parser.add_argument("--candidate-id", default="", help="Optional candidate_id to record in metrics for variant sidecars.")
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
        benchmark_ticker=args.benchmark_ticker,
        hard_stop=args.hard_stop,
        trailing_stop=args.trailing_stop,
        trailing_activation=args.trailing_activation,
        relative_trim_threshold=args.relative_trim_threshold,
        relative_exit_threshold=args.relative_exit_threshold,
        enable_distribution_exit=not args.disable_distribution_exit,
        candidate_id=args.candidate_id or None,
    )
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
