#!/usr/bin/env python3
"""r1000_tactical_backtest — Phase 17 v3 Layer 15 weekly tactical sleeve backtester.

User insight (2026-04-29):
  "tactical 백테스트는 없는듯한데 신규 전략도 믿을만한지 데이터화하자."

The tactical sleeve picks ~5 names weekly using a blended explosion +
acceleration score. Until now it was trusted blindly. This module
backtests that strategy against history and produces the standard
performance dict (CAGR / Sharpe / MaxDD / weekly hit rate) so the
sleeve can be ship-gated like any other phase.

Strategy
========
Weekly cadence — every Monday close:
  1. Score all eligible names (mcap >= $300M, dollar_vol >= $3M)
  2. tactical_score =
        +0.30 * rs_acceleration_score
        +0.25 * h6_dynamic_leader_score
        +0.25 * explosion_entry_score          (Phase 17 L11)
        -0.25 * explosion_exit_score
        -0.20 * stage2_overext_penalty
        +0.15 * (theme_phase_multiplier_max - 1.0)
  3. Pick top-N (default 5)
  4. Equal-weight, hold 1 week
  5. On Monday close next week: sell all, repeat

Output
======
    outputs/tactical_backtest/
        weekly_returns.parquet   ts, port_ret, spy_ret, holdings_json
        metrics.json             cagr, sharpe, max_dd, hit_rate, ...

Usage
=====
    python r1000_tactical_backtest.py
    python r1000_tactical_backtest.py --top-n 5 --start 2020-01-01
    python r1000_tactical_backtest.py --history outputs/scored_history.parquet

Notes
=====
* Requires multi-week historical scored data (feature_store_latest has
  only the latest snapshot). If the history file is missing, prints a
  clear message and exits with rc=2 — does NOT fabricate data.
* Walk-forward safe: at week W, only uses features known at W-1 close.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = REPO_ROOT / "outputs" / "tactical_backtest"

# Default tactical_score blend weights (sum-positive coefs add to ~0.95;
# they are NOT a normalized weight vector — the formula produces a
# dimensionless score, then top-N selection ranks across the cross
# section).
DEFAULT_BLEND = {
    "rs_acceleration_score": 0.30,
    "h6_dynamic_leader_score": 0.25,
    "explosion_entry_score": 0.25,
    "explosion_exit_score": -0.25,
    "stage2_overext_penalty": -0.20,
    "theme_phase_multiplier_max": 0.15,  # measured as (mult - 1.0)
}

ELIGIBILITY_MCAP_MIN = 300_000_000
ELIGIBILITY_DOLLAR_VOL_MIN = 3_000_000


@dataclass
class WeeklyResult:
    week_start: pd.Timestamp
    holdings: list[str]
    port_ret: float
    spy_ret: Optional[float]


def compute_tactical_score(df: pd.DataFrame, blend: dict = DEFAULT_BLEND) -> pd.Series:
    """Linear combo of named columns, missing -> 0 (penalty for absence)."""
    score = pd.Series(0.0, index=df.index)
    for col, w in blend.items():
        if col not in df.columns:
            continue
        s = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
        if col == "theme_phase_multiplier_max":
            s = s - 1.0
        score = score + w * s
    return score


def filter_eligible(df: pd.DataFrame) -> pd.DataFrame:
    """Apply mcap + liquidity floors. Missing fields = pass (data
    quality issue, not a hard reject for the backtest)."""
    out = df
    if "mktcap" in out.columns:
        mc = pd.to_numeric(out["mktcap"], errors="coerce")
        out = out[(mc >= ELIGIBILITY_MCAP_MIN) | mc.isna()]
    if "dollar_vol_avg_20d" in out.columns:
        dv = pd.to_numeric(out["dollar_vol_avg_20d"], errors="coerce")
        out = out[(dv >= ELIGIBILITY_DOLLAR_VOL_MIN) | dv.isna()]
    return out


def load_history(path: Path) -> Optional[pd.DataFrame]:
    """Load scored_history. Expects columns: ticker, rebalance_date,
    tactical_score input cols, r_1m or weekly forward return."""
    if not path.exists():
        return None
    if path.suffix == ".csv":
        return pd.read_csv(path)
    return pd.read_parquet(path)


def backtest_loop(
    history: pd.DataFrame,
    top_n: int,
    blend: dict,
    start: Optional[pd.Timestamp],
    end: Optional[pd.Timestamp],
) -> tuple[list[WeeklyResult], dict]:
    """Walk forward through weekly rebalance dates."""
    if "rebalance_date" not in history.columns:
        raise ValueError("history must contain 'rebalance_date' column")
    history = history.copy()
    history["rebalance_date"] = pd.to_datetime(history["rebalance_date"], errors="coerce")
    history = history.dropna(subset=["rebalance_date"])

    # Build weekly forward return: prefer pre-computed r_1w if present,
    # otherwise approximate r_1m / 4 (under-states tactical edge but
    # consistent direction). Better: r_1m raw monthly with monthly cadence.
    has_weekly = "r_1w" in history.columns
    if has_weekly:
        history["fwd_ret"] = pd.to_numeric(history["r_1w"], errors="coerce")
    elif "r_1m" in history.columns:
        history["fwd_ret"] = pd.to_numeric(history["r_1m"], errors="coerce")
    else:
        raise ValueError("history must contain r_1w or r_1m for forward-return labelling")

    if start is not None:
        history = history[history["rebalance_date"] >= start]
    if end is not None:
        history = history[history["rebalance_date"] <= end]

    spy_ret_by_date = {}
    if "ticker" in history.columns:
        spy_rows = history[history["ticker"].astype(str).str.upper() == "SPY"]
        for _, row in spy_rows.iterrows():
            spy_ret_by_date[row["rebalance_date"]] = float(row["fwd_ret"])

    results: list[WeeklyResult] = []
    for date, snap in history.groupby("rebalance_date", sort=True):
        eligible = filter_eligible(snap)
        if eligible.empty:
            continue
        score = compute_tactical_score(eligible, blend)
        eligible = eligible.assign(_score=score.values)
        eligible = eligible.sort_values("_score", ascending=False)
        # Skip if all scores are zero (no signal — likely models missing)
        if float(eligible["_score"].abs().max()) < 1e-9:
            continue
        picks = eligible.head(top_n)
        if picks.empty:
            continue
        port_ret = float(picks["fwd_ret"].dropna().mean()) if not picks["fwd_ret"].dropna().empty else 0.0
        results.append(WeeklyResult(
            week_start=date,
            holdings=picks["ticker"].astype(str).tolist() if "ticker" in picks.columns else [],
            port_ret=port_ret,
            spy_ret=spy_ret_by_date.get(date),
        ))

    metrics = compute_metrics(results, has_weekly)
    return results, metrics


def compute_metrics(results: list[WeeklyResult], has_weekly: bool) -> dict:
    if not results:
        return {"n_periods": 0, "note": "no rebalance periods produced"}
    rets = np.array([r.port_ret for r in results], dtype=float)
    spy_rets = np.array([r.spy_ret if r.spy_ret is not None else np.nan for r in results], dtype=float)

    # Annualization
    periods_per_year = 52 if has_weekly else 12
    growth = float(np.prod(1.0 + rets))
    n_years = len(rets) / periods_per_year
    cagr = float(growth ** (1.0 / n_years) - 1.0) if n_years > 0 and growth > 0 else float("nan")

    mean = float(np.nanmean(rets))
    std = float(np.nanstd(rets, ddof=1)) if len(rets) > 1 else float("nan")
    sharpe = float(mean / std * np.sqrt(periods_per_year)) if std and std > 0 else float("nan")

    cum = np.cumprod(1.0 + rets)
    peak = np.maximum.accumulate(cum)
    dd = (cum / peak) - 1.0
    max_dd = float(dd.min()) if len(dd) else float("nan")

    valid_spy = ~np.isnan(spy_rets)
    excess = rets[valid_spy] - spy_rets[valid_spy] if valid_spy.any() else np.array([])
    excess_mean = float(np.mean(excess)) if len(excess) else float("nan")
    hit_rate = float((rets > 0).mean())
    beat_spy_rate = float((excess > 0).mean()) if len(excess) else float("nan")

    return {
        "n_periods": len(rets),
        "cadence": "weekly" if has_weekly else "monthly_proxy",
        "cagr": cagr,
        "sharpe": sharpe,
        "max_dd": max_dd,
        "hit_rate": hit_rate,
        "beat_spy_rate": beat_spy_rate,
        "mean_period_return": mean,
        "vol_period": std,
        "excess_mean": excess_mean,
        "growth_multiple": growth,
        "first_date": str(results[0].week_start.date()),
        "last_date": str(results[-1].week_start.date()),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--history", default="outputs/scored_history.parquet",
                   help="scored history parquet (multi-week snapshots)")
    p.add_argument("--top-n", type=int, default=5)
    p.add_argument("--start", default=None, help="YYYY-MM-DD")
    p.add_argument("--end", default=None, help="YYYY-MM-DD")
    p.add_argument("--blend-json", default=None,
                   help="optional JSON file overriding DEFAULT_BLEND weights")
    args = p.parse_args()

    history_path = (REPO_ROOT / args.history) if not Path(args.history).is_absolute() else Path(args.history)
    history = load_history(history_path)
    if history is None or history.empty:
        print(f"[tactical-bt] ERROR: history not found at {history_path}.")
        print("              Run the main pipeline first to produce scored_history.parquet")
        print("              (or pass --history <path>).")
        return 2

    blend = dict(DEFAULT_BLEND)
    if args.blend_json:
        blend.update(json.loads(Path(args.blend_json).read_text()))

    start = pd.to_datetime(args.start) if args.start else None
    end = pd.to_datetime(args.end) if args.end else None

    print(f"[tactical-bt] history rows: {len(history)}  unique dates: {history['rebalance_date'].nunique() if 'rebalance_date' in history.columns else 'n/a'}")
    print(f"[tactical-bt] top_n={args.top_n}  blend={blend}")

    results, metrics = backtest_loop(history, args.top_n, blend, start, end)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    weekly_df = pd.DataFrame([
        {
            "week_start": r.week_start,
            "holdings": json.dumps(r.holdings),
            "port_ret": r.port_ret,
            "spy_ret": r.spy_ret,
        } for r in results
    ])
    weekly_path = OUTPUT_DIR / "weekly_returns.parquet"
    weekly_df.to_parquet(weekly_path, index=False)
    weekly_df.to_csv(OUTPUT_DIR / "weekly_returns.csv", index=False)

    metrics_path = OUTPUT_DIR / "metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2, default=str))

    print()
    print(f"[tactical-bt] periods:        {metrics.get('n_periods')}")
    print(f"[tactical-bt] cadence:        {metrics.get('cadence')}")
    print(f"[tactical-bt] CAGR:           {metrics.get('cagr')}")
    print(f"[tactical-bt] Sharpe:         {metrics.get('sharpe')}")
    print(f"[tactical-bt] MaxDD:          {metrics.get('max_dd')}")
    print(f"[tactical-bt] hit_rate:       {metrics.get('hit_rate')}")
    print(f"[tactical-bt] beat_spy_rate:  {metrics.get('beat_spy_rate')}")
    print(f"[tactical-bt] wrote {weekly_path}")
    print(f"[tactical-bt] wrote {metrics_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
