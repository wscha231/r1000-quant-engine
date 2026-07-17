#!/usr/bin/env python3
"""Describe semiconductor factor damage and security residual shocks.

This diagnostic is intentionally non-executable.  It measures whether a broad
SOXX selloff historically persisted or rebounded and distinguishes factor-
aligned held-name losses from unusually bad SOXX-relative residuals.  Results
cannot authorize a stop, sector cap, cash override, or portfolio rotation.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.build_run287_holding_risk_watch import classify, price_features, read_json  # noqa: E402
from tools.run_weekly_evaluation import load_price_series  # noqa: E402


FACTOR = "SOXX"
BENCHMARK = "SPY"
LOOKBACK = 756
MINIMUM = 252
TAIL_QUANTILE = 0.025
SEMI_TICKERS = ("WDC", "SNDK", "MU", "AMAT", "LRCX", "TER", "ON", "NXPI", "AMD", "MRVL", "NVDA", "AVGO", "ARM", "ASML", "TSM")
BASKETS = {
    "memory": ("WDC", "MU", "SNDK"),
    "equipment": ("AMAT", "LRCX", "TER"),
    "semi_leaders": ("NVDA", "AVGO", "TSM", "ASML"),
    "rotation_bigtech": ("AAPL", "GOOG", "META"),
    "broad_semis": ("SOXX",),
}
HORIZONS = (1, 5, 21, 63)


def load_prices(cache: Path, tickers: set[str]) -> pd.DataFrame:
    frames = {ticker: load_price_series(cache, ticker).get("close", pd.Series(dtype=float)) for ticker in sorted(tickers)}
    return pd.concat(frames, axis=1).sort_index()


def build_factor_state(prices: pd.DataFrame) -> pd.DataFrame:
    factor = prices[FACTOR]
    benchmark = prices[BENCHMARK]
    factor_return = factor.pct_change()
    benchmark_return = benchmark.pct_change()
    excess_21d = factor.pct_change(21) - benchmark.pct_change(21)
    drawdown_63d = factor / factor.rolling(63, min_periods=21).max() - 1.0
    tail_threshold = factor_return.shift(1).rolling(LOOKBACK, min_periods=MINIMUM).quantile(TAIL_QUANTILE)
    trend_threshold = excess_21d.shift(1).rolling(LOOKBACK, min_periods=MINIMUM).quantile(0.10)
    drawdown_threshold = drawdown_63d.shift(1).rolling(LOOKBACK, min_periods=MINIMUM).quantile(0.10)
    below_ma20 = factor.lt(factor.rolling(20, min_periods=20).mean())
    below_ma50 = factor.lt(factor.rolling(50, min_periods=50).mean())
    state = pd.DataFrame(index=prices.index)
    state["factor_return_1d"] = factor_return
    state["benchmark_return_1d"] = benchmark_return
    state["factor_spy_excess_21d"] = excess_21d
    state["factor_drawdown_63d"] = drawdown_63d
    state["tail_threshold"] = tail_threshold
    state["trend_threshold"] = trend_threshold
    state["drawdown_threshold"] = drawdown_threshold
    state["tail_shock"] = factor_return.le(tail_threshold)
    state["trend_damage"] = below_ma20 & below_ma50 & excess_21d.le(trend_threshold)
    state["drawdown_damage"] = below_ma50 & drawdown_63d.le(drawdown_threshold)
    state["joint_damage"] = state["trend_damage"] & state["drawdown_damage"]
    state["joint_damage_transition"] = state["joint_damage"] & ~state["joint_damage"].shift(1, fill_value=False).astype(bool)
    state["tail_shock_count_21d"] = state["tail_shock"].rolling(21, min_periods=1).sum()
    state["recurrent_tail_state"] = state["tail_shock_count_21d"].ge(2)
    state["recurrent_tail_transition"] = state["recurrent_tail_state"] & ~state["recurrent_tail_state"].shift(1, fill_value=False).astype(bool)
    return state


def basket_return(prices: pd.DataFrame, members: tuple[str, ...], start: int, end: int) -> float:
    values: list[float] = []
    for ticker in members:
        if ticker not in prices or start < 0 or end >= len(prices):
            continue
        first, last = prices[ticker].iloc[start], prices[ticker].iloc[end]
        if pd.notna(first) and pd.notna(last) and float(first) > 0:
            values.append(float(last / first - 1.0))
    return float(np.mean(values)) if values else np.nan


def event_outcomes(prices: pd.DataFrame, state: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for event_type, column in (
        ("tail_shock", "tail_shock"),
        ("joint_damage_transition", "joint_damage_transition"),
        ("recurrent_tail_transition", "recurrent_tail_transition"),
    ):
        for position, (date, fired) in enumerate(state[column].items()):
            if not bool(fired):
                continue
            entry = position + 1
            row: dict[str, Any] = {"event_type": event_type, "signal_date": date.date().isoformat(), "entry_date": ""}
            if entry < len(prices):
                row["entry_date"] = prices.index[entry].date().isoformat()
            for basket, members in BASKETS.items():
                for horizon in HORIZONS:
                    value = basket_return(prices, members, entry, entry + horizon)
                    benchmark = basket_return(prices, (BENCHMARK,), entry, entry + horizon)
                    row[f"{basket}_{horizon}d_return"] = value
                    row[f"{basket}_{horizon}d_spy_excess"] = value - benchmark if np.isfinite(value) and np.isfinite(benchmark) else np.nan
            rows.append(row)
    return pd.DataFrame(rows)


def outcome_summary(events: pd.DataFrame) -> dict[str, Any]:
    result: dict[str, Any] = {}
    signal_dates = pd.to_datetime(events["signal_date"], errors="coerce")
    for event_type in sorted(events["event_type"].unique()):
        result[event_type] = {}
        for segment, mask in (
            ("full", signal_dates.ge(pd.Timestamp("2019-06-03"))),
            ("oos2", signal_dates.ge(pd.Timestamp("2023-01-01"))),
            ("oos", signal_dates.ge(pd.Timestamp("2024-07-01"))),
        ):
            scoped = events[events["event_type"].eq(event_type) & mask].copy()
            payload: dict[str, Any] = {"event_count": int(len(scoped))}
            for basket in BASKETS:
                for horizon in HORIZONS:
                    column = f"{basket}_{horizon}d_spy_excess"
                    values = pd.to_numeric(scoped[column], errors="coerce").dropna()
                    payload[column] = {
                        "count": int(len(values)),
                        "mean": float(values.mean()) if not values.empty else None,
                        "median": float(values.median()) if not values.empty else None,
                        "positive_rate": float(values.gt(0).mean()) if not values.empty else None,
                    }
            result[event_type][segment] = payload
    return result


def current_residuals(prices: pd.DataFrame, asof: pd.Timestamp) -> pd.DataFrame:
    factor_returns = prices[FACTOR].pct_change()
    rows: list[dict[str, Any]] = []
    for ticker in SEMI_TICKERS:
        if ticker not in prices or asof not in prices.index:
            continue
        returns = prices[ticker].pct_change()
        residual = returns - factor_returns
        history = residual.loc[residual.index < asof].dropna().tail(LOOKBACK)
        current = residual.get(asof, np.nan)
        threshold = history.quantile(TAIL_QUANTILE) if len(history) >= MINIMUM else np.nan
        percentile = float(history.le(current).mean()) if len(history) >= MINIMUM and np.isfinite(current) else np.nan
        rows.append(
            {
                "as_of_date": asof.date().isoformat(),
                "ticker": ticker,
                "return_1d": returns.get(asof, np.nan),
                "soxx_return_1d": factor_returns.get(asof, np.nan),
                "soxx_residual_1d": current,
                "past_residual_q025": threshold,
                "past_residual_percentile": percentile,
                "history_observations": int(len(history)),
                "sector_residual_alert": bool(np.isfinite(current) and np.isfinite(threshold) and current <= threshold),
                "advisory_action": "FREEZE_INCREMENTAL_BUY_AND_MANUAL_REVIEW" if np.isfinite(current) and np.isfinite(threshold) and current <= threshold else "NO_SECTOR_RESIDUAL_ALERT",
            }
        )
    return pd.DataFrame(rows)


def portfolio_exposure(risk_watch: pd.DataFrame) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for portfolio, group in risk_watch.groupby("portfolio_kind", sort=False):
        semi = group[group["ticker"].isin(SEMI_TICKERS)]
        hardware = group[group["ticker"].isin(set(SEMI_TICKERS) | {"CIEN", "GLW", "VRT"})]
        result[str(portfolio)] = {
            "semi_weight": float(pd.to_numeric(semi["current_weight"], errors="coerce").sum()),
            "hardware_weight": float(pd.to_numeric(hardware["current_weight"], errors="coerce").sum()),
            "alert_tickers": sorted(group.loc[group["risk_state"].eq("ALERT"), "ticker"].astype(str).tolist()),
            "watch_tickers": sorted(group.loc[group["risk_state"].eq("WATCH"), "ticker"].astype(str).tolist()),
        }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--price-cache", default="outputs/run287_semiconductor_shock_price_cache_20260717")
    parser.add_argument("--risk-watch", default="outputs/run287_holding_risk_watch_full_20260717_close_20260716/holding_risk_watch.csv")
    parser.add_argument("--risk-contract", default="docs/run287_holding_risk_watch_contract.json")
    parser.add_argument("--as-of-date", default="2026-07-16")
    parser.add_argument("--output-dir", default="outputs/run287_semiconductor_damage_20260717_close_20260716")
    args = parser.parse_args()
    cache = Path(args.price_cache) if Path(args.price_cache).is_absolute() else REPO_ROOT / args.price_cache
    risk_path = Path(args.risk_watch) if Path(args.risk_watch).is_absolute() else REPO_ROOT / args.risk_watch
    contract_path = Path(args.risk_contract) if Path(args.risk_contract).is_absolute() else REPO_ROOT / args.risk_contract
    asof = pd.Timestamp(args.as_of_date).normalize()
    prices = load_prices(cache, set(SEMI_TICKERS) | {BENCHMARK, FACTOR, "SMH", "QQQ", *sum((list(v) for v in BASKETS.values()), [])})
    state = build_factor_state(prices)
    if asof not in state.index:
        raise ValueError(f"exact factor close missing for {asof.date()}")
    events = event_outcomes(prices, state)
    residuals = current_residuals(prices, asof)
    risk_watch = pd.read_csv(risk_path, low_memory=False)
    contract = read_json(contract_path)
    spy_returns = prices[BENCHMARK].pct_change()
    factor_features = price_features(ticker=FACTOR, price_cache=cache, benchmark_returns=spy_returns, asof=asof, contract=contract)
    factor_state, factor_action, factor_reasons = classify(factor_features)
    current = state.loc[asof]
    summary = {
        "status": "READY_REVIEW_ONLY",
        "as_of_date": asof.date().isoformat(),
        "factor": FACTOR,
        "factor_risk_state": factor_state,
        "factor_advisory_action": factor_action,
        "factor_reason_codes": factor_reasons,
        "factor_return_1d": current["factor_return_1d"],
        "factor_spy_excess_21d": current["factor_spy_excess_21d"],
        "factor_drawdown_63d": current["factor_drawdown_63d"],
        "factor_tail_shock": bool(current["tail_shock"]),
        "factor_tail_threshold": current["tail_threshold"],
        "factor_tail_shock_count_21d": current["tail_shock_count_21d"],
        "joint_damage": bool(current["joint_damage"]),
        "sector_residual_alerts": sorted(residuals.loc[residuals["sector_residual_alert"], "ticker"].tolist()),
        "portfolio_exposure": portfolio_exposure(risk_watch),
        "historical_outcomes": outcome_summary(events),
        "promotion_verdict": "UNDERPOWERED_NO_PORTFOLIO_ACTION",
        "reason": "OOS joint-damage and recurrent-shock transition samples are below 12 and resolved history generally rebounds after shocks",
        "post_outcome_inspected_diagnostic": True,
        "orders_generated": False,
        "target_weights_changed": False,
        "cash_policy_changed": False,
        "fullrun_dispatched": False,
        "production_or_live_enabled": False,
    }
    output = Path(args.output_dir) if Path(args.output_dir).is_absolute() else REPO_ROOT / args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    events.to_csv(output / "historical_factor_event_outcomes.csv", index=False)
    residuals.to_csv(output / "current_sector_residuals.csv", index=False)
    state.reset_index(names="date").to_csv(output / "factor_state_history.csv", index=False)
    (output / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
