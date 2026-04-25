"""r1000_rule_backtester - Empirical validation of hardcoded rules.

User mandate (2026-04-24):
  "이런 룰들이 실제로 얼마나 성과가 좋은지 분석. 하드코딩으로 잡는 것보다
   너가 데이터와 주가의 움직임을 정밀 분석해서 새로운 규칙을 찾아내는 게 어때?"

Phase 1: Backtest existing tiers (T1-T5) to measure their actual alpha.
  - Walk forward through 2020-2026
  - For each month-end, run rule on each R1000 ticker (PIT)
  - Track 30/60/90/180 day forward returns of fired vs not-fired
  - Compute hit rate, avg return, sharpe vs SPY benchmark

Output: backtest_results/{tier_name}.csv with per-fire metrics
        backtest_summary.csv with aggregate stats per tier

Usage:
    py -3 r1000_rule_backtester.py --tier T1
    py -3 r1000_rule_backtester.py --tier all --years 5
    py -3 r1000_rule_backtester.py --quick        # 1 year only
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

sys.path.insert(0, str(Path(__file__).parent))

import numpy as np
import pandas as pd

from aggressive.data_alpaca import fetch_daily_bars, fetch_spy_benchmark
from aggressive.signals_technical import (
    tier1_stage2_breakout,
    tier2_vcp_breakout,
    tier3_earnings_gap,
    tier4_rs_acceleration,
    tier5_stage_transition,
)
from aggressive.universe import load_universe


# Tier function registry
TIERS = {
    "T1": (lambda df, spy: tier1_stage2_breakout(df), "Stage 2 Breakout"),
    "T2": (lambda df, spy: tier2_vcp_breakout(df), "VCP Breakout"),
    "T3": (lambda df, spy: tier3_earnings_gap(df), "Earnings Gap"),
    "T4": (lambda df, spy: tier4_rs_acceleration(df, spy), "RS Acceleration"),
    "T5": (lambda df, spy: tier5_stage_transition(df, spy), "Stage 1->2 Turnaround"),
}


@dataclass
class FireRecord:
    ticker: str
    date: str
    tier: str
    score: float
    fired: bool
    fwd_30d: Optional[float] = None
    fwd_60d: Optional[float] = None
    fwd_90d: Optional[float] = None
    fwd_180d: Optional[float] = None
    spy_30d: Optional[float] = None
    spy_60d: Optional[float] = None
    spy_90d: Optional[float] = None
    spy_180d: Optional[float] = None


# --- Helpers ---------------------------------------------------------------

def month_ends(start: str, end: str) -> list[pd.Timestamp]:
    """Generate trading-month-end dates between start and end."""
    return list(pd.date_range(start, end, freq="ME"))


def forward_return(close_series: pd.Series, base_idx: int, days: int) -> Optional[float]:
    """Pct return from base_idx to base_idx+days. None if out of bounds."""
    if base_idx + days >= len(close_series):
        return None
    p0 = float(close_series.iloc[base_idx])
    p1 = float(close_series.iloc[base_idx + days])
    if p0 <= 0 or pd.isna(p0) or pd.isna(p1):
        return None
    return (p1 / p0 - 1.0) * 100.0


# --- Core backtest ---------------------------------------------------------

def backtest_tier(
    tier_name: str,
    rule_func: Callable,
    universe: list[str],
    spy_full: pd.DataFrame,
    rebalance_dates: list[pd.Timestamp],
    bars_lookback_days: int = 400,
    verbose: bool = True,
) -> list[FireRecord]:
    """For each rebalance date, evaluate rule on all universe tickers (PIT).

    Records forward returns at 30/60/90/180 days for each ticker.
    """
    records: list[FireRecord] = []
    bar_cache: dict[str, pd.DataFrame] = {}
    spy_close = spy_full["close"]

    for d_idx, date in enumerate(rebalance_dates):
        if verbose:
            print(f"[{tier_name}] {date.date()} ({d_idx+1}/{len(rebalance_dates)})...")
        n_fired = 0
        for ticker in universe:
            # Get bars (cached across iterations)
            if ticker not in bar_cache:
                df = fetch_daily_bars(ticker, days=bars_lookback_days * 2)
                if df.empty:
                    bar_cache[ticker] = pd.DataFrame()
                    continue
                bar_cache[ticker] = df
            df = bar_cache[ticker]
            if df.empty:
                continue

            # PIT slice: bars up to (but not including) date+1
            cutoff = pd.Timestamp(date).tz_localize(df.index.tz)
            past = df[df.index <= cutoff]
            if len(past) < 252:
                continue

            # Run rule
            try:
                signal = rule_func(past, spy_full)
            except Exception:
                continue

            # Compute forward returns
            fwd_idx = past.index[-1]
            try:
                base_idx_in_full = df.index.get_loc(fwd_idx)
                if isinstance(base_idx_in_full, slice):
                    base_idx_in_full = base_idx_in_full.stop - 1
            except KeyError:
                continue
            close_full = df["close"]
            fwd_30 = forward_return(close_full, base_idx_in_full, 21)
            fwd_60 = forward_return(close_full, base_idx_in_full, 42)
            fwd_90 = forward_return(close_full, base_idx_in_full, 63)
            fwd_180 = forward_return(close_full, base_idx_in_full, 126)

            # SPY same-period return
            spy_dates = spy_close.index
            try:
                spy_base = spy_dates.get_indexer([cutoff], method="ffill")[0]
                if spy_base < 0:
                    continue
            except Exception:
                continue
            spy_30 = forward_return(spy_close, spy_base, 21)
            spy_60 = forward_return(spy_close, spy_base, 42)
            spy_90 = forward_return(spy_close, spy_base, 63)
            spy_180 = forward_return(spy_close, spy_base, 126)

            records.append(FireRecord(
                ticker=ticker, date=str(date.date()),
                tier=tier_name, score=signal.score, fired=signal.fired,
                fwd_30d=fwd_30, fwd_60d=fwd_60, fwd_90d=fwd_90, fwd_180d=fwd_180,
                spy_30d=spy_30, spy_60d=spy_60, spy_90d=spy_90, spy_180d=spy_180,
            ))
            if signal.fired:
                n_fired += 1

        if verbose:
            print(f"  fired: {n_fired}")

    return records


# --- Aggregate stats -------------------------------------------------------

def summarize(records: list[FireRecord]) -> pd.DataFrame:
    """Aggregate per-tier statistics."""
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame([asdict(r) for r in records])
    fired = df[df["fired"]]

    rows = []
    for window in [30, 60, 90, 180]:
        col = f"fwd_{window}d"
        spy_col = f"spy_{window}d"
        if col not in df.columns:
            continue
        valid = fired.dropna(subset=[col, spy_col])
        if valid.empty:
            continue
        alpha = valid[col] - valid[spy_col]
        rows.append({
            "window_days": window,
            "n_fires": len(valid),
            "avg_return_pct": float(valid[col].mean()),
            "median_return_pct": float(valid[col].median()),
            "spy_return_pct": float(valid[spy_col].mean()),
            "alpha_pct": float(alpha.mean()),
            "alpha_std": float(alpha.std()),
            "alpha_sharpe": float(alpha.mean() / alpha.std()) if alpha.std() > 0 else 0,
            "hit_rate_positive": float((valid[col] > 0).mean()),
            "hit_rate_beat_spy": float(alpha.gt(0).mean()),
            "max_return_pct": float(valid[col].max()),
            "min_return_pct": float(valid[col].min()),
        })
    return pd.DataFrame(rows)


# --- Main ------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--tier", default="all", choices=list(TIERS.keys()) + ["all"])
    p.add_argument("--years", type=int, default=2,
                   help="years of history to backtest (default 2)")
    p.add_argument("--quick", action="store_true",
                   help="only test on top 200 tickers")
    p.add_argument("--max-tickers", type=int, default=0,
                   help="limit universe size (0 = all)")
    p.add_argument("--output-dir", default="backtest_results")
    args = p.parse_args()

    print("=" * 70)
    print("r1000 Rule Backtester")
    print("=" * 70)

    # Universe
    universe, _ = load_universe("r1000")
    if args.quick:
        universe = universe[:200]
    if args.max_tickers > 0:
        universe = universe[:args.max_tickers]
    print(f"Universe: {len(universe)} tickers")

    # SPY
    spy = fetch_spy_benchmark(days=args.years * 252 + 200)
    if spy.empty:
        print("FAIL: no SPY data")
        return 1

    # Rebalance dates
    end_date = pd.Timestamp.now().normalize() - pd.Timedelta(days=200)
    start_date = end_date - pd.Timedelta(days=args.years * 365)
    dates = month_ends(start_date.strftime("%Y-%m-%d"),
                       end_date.strftime("%Y-%m-%d"))
    print(f"Backtesting {len(dates)} month-ends from {dates[0].date()} to {dates[-1].date()}")

    # Tiers to run
    tiers_to_run = list(TIERS.keys()) if args.tier == "all" else [args.tier]

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    all_summaries = []
    for tier_name in tiers_to_run:
        print()
        print("-" * 70)
        print(f"Backtesting {tier_name} ({TIERS[tier_name][1]})")
        print("-" * 70)
        rule_func, _ = TIERS[tier_name]
        records = backtest_tier(
            tier_name, rule_func, universe, spy, dates,
            verbose=True,
        )
        # Save raw records
        if records:
            df = pd.DataFrame([asdict(r) for r in records])
            df.to_csv(out_dir / f"{tier_name}_records.csv", index=False)
            print(f"[save] {len(records)} records -> {tier_name}_records.csv")

        # Summary
        summary = summarize(records)
        if not summary.empty:
            summary["tier"] = tier_name
            summary["tier_name"] = TIERS[tier_name][1]
            all_summaries.append(summary)
            print(f"\n[{tier_name}] Summary:")
            print(summary.to_string(index=False))

    # Combined summary
    if all_summaries:
        combined = pd.concat(all_summaries, ignore_index=True)
        combined.to_csv(out_dir / "backtest_summary.csv", index=False)
        print()
        print("=" * 70)
        print("COMBINED SUMMARY")
        print("=" * 70)
        print(combined.to_string(index=False))

    return 0


if __name__ == "__main__":
    sys.exit(main())
