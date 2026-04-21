#!/usr/bin/env python3
"""phase15_s1_future_winner_factor_ic.py

Per-factor rank-IC audit on the future_winner sleeve composite.

Why this exists
===============
The future_winner composite in r1000_signals.py:642-707 stacks ~40 factors
with hand-tuned weights. Standalone backtest (engine_diagnostics_summary)
shows future_winner topn_cagr_1m = 16.08% — WEAKEST of the three sleeves vs
early_scout 35.73% / core_compounder 20.14%. The hypothesis: composite
dilution from low-/negative-IC factors is dragging the sleeve below what
its best factors can produce.

Methodology
===========
1. Load feature_store_latest.parquet (53k rows, 920 tickers, 97 months).
2. Compute forward_r_1m per (ticker, date) by shift(-1) on r_1m grouped by
   ticker and sorted by rebalance_date.
3. For each factor in FUTURE_WINNER_FACTORS (only those present in the
   feature store — ML predictions like pred_future_winner_ret are computed
   downstream and not available here), compute per-month cross-sectional
   Spearman rank-IC vs forward_r_1m AND forward_r_3m.
4. Aggregate across 83-ish backtest months: IC_mean, IC_std, IC_IR
   (= IC_mean / IC_std), months_abs_IC_gt_0p02 (stability).
5. Also compute IC on the TOP-30% future_winner_scout_score subset — a
   proxy for the actual future_winner candidate pool since
   portfolio_sleeve_label is not in the feature_store (assigned later).

Output
======
research/phase15_s1_future_winner_factor_ic.csv with columns:
  factor, current_weight, ic_1m_universe, ic_ir_1m_universe,
  ic_1m_fw_subset, ic_ir_1m_fw_subset, ic_3m_universe, stability_pct,
  prune_candidate (True if |IC_mean| < 0.02 AND |IC_IR| < 0.3)

Run
===
  py -3 research/phase15_s1_future_winner_factor_ic.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats


# Factor name -> (current composite weight in r1000_signals.py future_winner).
# Weights pulled from r1000_signals.py:642-707 at 2026-04-21. Variable weights
# (phase-toggle controlled) marked as 'var'. Factors downstream of the ML
# ensemble or blueprint functions (pred_future_winner_*, minervini_*, p5_*,
# insider_flow_*, multi_year, persistence_trend, long_horizon_alpha) are not
# present in feature_store and are skipped here.
FUTURE_WINNER_FACTORS: dict[str, float | str] = {
    "future_winner_scout_score": 1.10,
    "anticipatory_growth_score": 0.95,
    "dynamic_leader_score": 0.95,
    "leader_emergence_score": 0.90,
    "relative_strength_composite": 0.90,
    "revision_blueprint_score": 0.95,
    "analyst_revision_trend_score": 0.70,
    "revision_score": 0.65,
    "target_upside_pct": 0.60,
    "revenue_growth_final": 0.55,
    "earnings_growth_final": 0.45,
    "fundamental_turnaround_acceleration_score": 0.50,
    "cashflow_inflection_under_loss_score": 0.35,
    "breakout_setup_quality_score": 0.35,
    "value_inflection_score": 0.45,
    "uptrend_continuation_score": 0.30,
    "uptrend_breakdown_penalty": -0.30,
    "oneil_leadership_score": 0.55,
    "industry_group_strength_score": "var",
    "industry_within_leader_rank": 0.20,
    "rs_industry_6m": 0.25,
    "rs_industry_3m": "var",
    "industry_rotation_signal": "var",
    "archetype_emerging_growth_score": 0.70,
    "broken_momentum_penalty": -0.35,
}

PRUNE_IC_MEAN_THRESHOLD = 0.02
PRUNE_IC_IR_THRESHOLD = 0.30

DEFAULT_FEATURE_STORE = (
    r"G:\내 드라이브\r1000_top30_institutional\feature_store\feature_store_latest.parquet"
)
OUTPUT_CSV = Path(__file__).with_suffix("").parent / "phase15_s1_future_winner_factor_ic.csv"


def compute_forward_returns(df: pd.DataFrame) -> pd.DataFrame:
    """Add forward_r_1m and forward_r_3m columns by shifting within each ticker."""
    df = df.sort_values(["ticker", "rebalance_date"]).copy()
    df["forward_r_1m"] = df.groupby("ticker")["r_1m"].shift(-1)
    df["forward_r_3m"] = df.groupby("ticker")["r_1m"].shift(-1).rolling(3, min_periods=2).sum()
    # forward_r_3m above is approximate (sum of next 3 monthly log-like returns);
    # for rank-IC purposes the ordering is preserved.
    return df


def monthly_rank_ic(df: pd.DataFrame, factor: str, target: str) -> pd.Series:
    """Return a Series of per-month cross-sectional Spearman rank-IC values."""
    results: dict[pd.Timestamp, float] = {}
    for date, grp in df.groupby("rebalance_date"):
        x = pd.to_numeric(grp[factor], errors="coerce")
        y = pd.to_numeric(grp[target], errors="coerce")
        mask = x.notna() & y.notna()
        if mask.sum() < 30:
            continue
        try:
            rho = stats.spearmanr(x[mask], y[mask]).statistic
        except Exception:
            continue
        if np.isfinite(rho):
            results[date] = float(rho)
    return pd.Series(results).sort_index()


def ic_summary(ic_series: pd.Series) -> tuple[float, float, float, float]:
    """Return (mean, std, IR, fraction of months with |IC| > 0.02)."""
    if ic_series.empty:
        return (np.nan, np.nan, np.nan, np.nan)
    mean = float(ic_series.mean())
    std = float(ic_series.std(ddof=1)) if len(ic_series) > 1 else 0.0
    ir = mean / std if std > 1e-10 else np.nan
    stability = float((ic_series.abs() > 0.02).mean())
    return (mean, std, ir, stability)


def run_audit(feature_store_path: str | Path = DEFAULT_FEATURE_STORE) -> pd.DataFrame:
    print(f"Loading feature store: {feature_store_path}")
    df = pd.read_parquet(feature_store_path)
    print(f"  rows={len(df):,} tickers={df['ticker'].nunique()} months={df['rebalance_date'].nunique()}")

    df = compute_forward_returns(df)
    df["rebalance_date"] = pd.to_datetime(df["rebalance_date"])

    # Future-winner candidate subset: top-30% by scout_score cross-sectionally per month.
    if "future_winner_scout_score" in df.columns:
        scout = pd.to_numeric(df["future_winner_scout_score"], errors="coerce")
        thresholds = df.assign(_scout=scout).groupby("rebalance_date")["_scout"].transform(
            lambda s: s.quantile(0.70)
        )
        fw_mask = scout >= thresholds
        fw_df = df[fw_mask].copy()
        print(f"  FW candidate subset (top-30% by scout_score): {len(fw_df):,} rows")
    else:
        fw_df = df.iloc[0:0]
        print("  WARN: future_winner_scout_score not in feature_store; fw_subset IC will be blank")

    rows: list[dict] = []
    for factor, weight in FUTURE_WINNER_FACTORS.items():
        if factor not in df.columns:
            print(f"  skip [{factor}] - not in feature_store (likely computed downstream)")
            continue
        ic1 = monthly_rank_ic(df, factor, "forward_r_1m")
        ic3 = monthly_rank_ic(df, factor, "forward_r_3m")
        fw_ic1 = monthly_rank_ic(fw_df, factor, "forward_r_1m") if not fw_df.empty else pd.Series(dtype=float)
        m1, s1, ir1, stab1 = ic_summary(ic1)
        m3, s3, ir3, stab3 = ic_summary(ic3)
        mf, sf, irf, stabf = ic_summary(fw_ic1)
        prune = (
            (abs(m1) < PRUNE_IC_MEAN_THRESHOLD) and (abs(ir1) < PRUNE_IC_IR_THRESHOLD)
            if np.isfinite(m1) and np.isfinite(ir1)
            else False
        )
        rows.append({
            "factor": factor,
            "current_weight": weight,
            "ic_1m_universe": round(m1, 4),
            "ic_ir_1m_universe": round(ir1, 3) if np.isfinite(ir1) else np.nan,
            "stability_1m_universe_pct": round(stab1 * 100, 1) if np.isfinite(stab1) else np.nan,
            "ic_3m_universe": round(m3, 4),
            "ic_ir_3m_universe": round(ir3, 3) if np.isfinite(ir3) else np.nan,
            "ic_1m_fw_subset": round(mf, 4) if np.isfinite(mf) else np.nan,
            "ic_ir_1m_fw_subset": round(irf, 3) if np.isfinite(irf) else np.nan,
            "n_months_universe": int(len(ic1)),
            "prune_candidate": prune,
        })

    result = pd.DataFrame(rows).sort_values("ic_ir_1m_universe", ascending=False, na_position="last")
    result.to_csv(OUTPUT_CSV, index=False)
    print(f"\nWrote {OUTPUT_CSV}  ({len(result)} factors audited)")
    print("\nTop 5 by IC_IR_1m (universe):")
    print(result.head(5).to_string(index=False))
    print("\nBottom 5 by IC_IR_1m (universe):")
    print(result.tail(5).to_string(index=False))
    print(f"\nPrune candidates (|IC|<{PRUNE_IC_MEAN_THRESHOLD} AND |IR|<{PRUNE_IC_IR_THRESHOLD}):")
    prunes = result.loc[result["prune_candidate"], ["factor", "current_weight", "ic_1m_universe", "ic_ir_1m_universe"]]
    print(prunes.to_string(index=False) if not prunes.empty else "  (none)")
    return result


if __name__ == "__main__":
    feature_store = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_FEATURE_STORE
    run_audit(feature_store)
