#!/usr/bin/env python3
"""Phase E3 -- Crisis Type Classifier (CODEX_HANDOFF v3.6 Section 17.4)

Reads the daily feature panel produced by Phase E2 and labels each trading
day with a crisis archetype. The labels feed Phase E5 / E6 (exposure ladder
+ re-entry ladder), where each archetype has its own pacing rules:

  - shock_crash:    fast defense + fast re-entry (2020 COVID style)
  - slow_bear:      gradual defense + slow re-entry (2022 rate-hike style)
  - credit_crisis:  fast defense + wait for credit stabilization
  - normal_pullback: no defense action (avoid false alarms)
  - recovery:       re-entry ladder activates
  - normal:         no signal

The classifier is RULE-BASED and PIT-safe -- features at time T are derived
only from data available at T close (E2 guarantees this).

Input:
    outputs/crisis_signals/daily_features.parquet   (from E2)

Output:
    outputs/crisis_signals/daily_classification.csv
    outputs/crisis_signals/classification_audit.json

Usage:
    py -3 tools/run_crisis_type_classifier.py
    py -3 tools/run_crisis_type_classifier.py --base-dir /alt/path

Plan ref:
    CODEX_HANDOFF_PLAN_C_V3_5_20260520.md Section 17.4 (Phase E3)
    research/final_integrated_engine_20260524/plan.md Section 2 E3
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

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASE = Path("/content/drive/MyDrive/r1000_top30_institutional")


# ---------------------------------------------------------------------------
# Path discovery (mirrors E2 convention)
# ---------------------------------------------------------------------------


def discover_features_path(base_dir: Optional[Path]) -> Optional[Path]:
    candidates = [base_dir] if base_dir else []
    candidates += [DEFAULT_BASE, ROOT]
    for cand in candidates:
        if cand is None or not cand.exists():
            continue
        p = cand / "outputs" / "crisis_signals" / "daily_features.parquet"
        if p.exists():
            return p
    return None


# ---------------------------------------------------------------------------
# Streak counter (days below MA200)
# ---------------------------------------------------------------------------


def consecutive_streak(series: pd.Series) -> pd.Series:
    """For a 0/1 series, return consecutive True days. Resets at every 0.

    Example: [0,0,1,1,1,0,1,1] -> [0,0,1,2,3,0,1,2]
    """
    s = series.fillna(0).astype(int)
    # Group resets every time the value changes
    groups = (s != s.shift()).cumsum()
    streak = s.groupby(groups).cumsum() * s
    return streak.astype(int)


# ---------------------------------------------------------------------------
# Classification rules (PIT-safe -- each row uses only its own column values)
# ---------------------------------------------------------------------------


@dataclass
class Thresholds:
    shock_spy_5d_dd: float = -0.08   # SPY 5d drawdown <= -8%
    shock_vix_z: float = 2.5
    slow_bear_min_days_below_ma200: int = 30
    slow_bear_rising_yield_bps: float = 25.0   # 20d 10Y change >= 25 bps
    credit_hy_z: float = 2.0
    normal_pullback_5d_lo: float = -0.08
    normal_pullback_5d_hi: float = -0.03
    normal_pullback_vix_lo: float = 0.5
    normal_pullback_vix_hi: float = 2.0
    recovery_vix_max: float = 0.5
    recovery_spy_ma_reclaim: bool = True


def classify_rows(features: pd.DataFrame, thr: Thresholds) -> pd.DataFrame:
    """Return DataFrame with crisis_type column plus per-archetype boolean flags."""
    out = pd.DataFrame(index=features.index)

    # Days below MA200 streak (uses only past data via consecutive_streak)
    spy_below = features.get("spy_below_ma200", pd.Series(0, index=features.index)).fillna(0)
    qqq_below = features.get("qqq_below_ma200", pd.Series(0, index=features.index)).fillna(0)
    out["days_spy_below_ma200"] = consecutive_streak(spy_below)
    out["days_qqq_below_ma200"] = consecutive_streak(qqq_below)

    # Pre-compute helper columns
    spy_5d = features.get("spy_5d_dd", pd.Series(np.nan, index=features.index))
    vix_z = features.get("vix_zscore_60d", pd.Series(np.nan, index=features.index))
    hy_z = features.get("hy_oas_zscore_60d", pd.Series(np.nan, index=features.index))
    y10_20d = features.get("ten_year_20d_change_bps", pd.Series(np.nan, index=features.index))
    spy_close = features.get("spy_close", pd.Series(np.nan, index=features.index))
    spy_ma50 = features.get("spy_ma50", pd.Series(np.nan, index=features.index))

    # ─── shock_crash ───
    out["is_shock_crash"] = (
        (spy_5d <= thr.shock_spy_5d_dd)
        & (vix_z >= thr.shock_vix_z)
    ).fillna(False)

    # ─── credit_crisis ───
    # Note: only HY available on this branch; IG would tighten further
    out["is_credit_crisis"] = (hy_z >= thr.credit_hy_z).fillna(False)

    # ─── slow_bear ───
    out["is_slow_bear"] = (
        (spy_below.astype(bool))
        & (qqq_below.astype(bool))
        & (out["days_spy_below_ma200"] >= thr.slow_bear_min_days_below_ma200)
        & (y10_20d.fillna(0) >= thr.slow_bear_rising_yield_bps)
    ).fillna(False)

    # ─── normal_pullback ───
    out["is_normal_pullback"] = (
        (spy_5d.between(thr.normal_pullback_5d_lo, thr.normal_pullback_5d_hi))
        & (vix_z.between(thr.normal_pullback_vix_lo, thr.normal_pullback_vix_hi))
    ).fillna(False)

    # ─── recovery ───
    out["is_recovery"] = (
        (vix_z <= thr.recovery_vix_max)
        & (spy_close >= spy_ma50)
        & (~out["is_shock_crash"])
        & (~out["is_credit_crisis"])
    ).fillna(False)

    # Priority cascade: shock_crash > credit_crisis > slow_bear > recovery > normal_pullback > normal
    # Shock takes priority over credit because the VIX spike is typically the
    # leading signal (HY spread widens after VIX in real crises). Recovery
    # beats normal_pullback because re-entry signal is more actionable.
    def _label(row: pd.Series) -> str:
        if row["is_shock_crash"]:
            return "shock_crash"
        if row["is_credit_crisis"]:
            return "credit_crisis"
        if row["is_slow_bear"]:
            return "slow_bear"
        if row["is_recovery"]:
            return "recovery"
        if row["is_normal_pullback"]:
            return "normal_pullback"
        return "normal"

    out["crisis_type"] = out.apply(_label, axis=1)
    return out


def classification_summary(classification: pd.DataFrame) -> dict:
    counts = classification["crisis_type"].value_counts().to_dict()
    pcts = (classification["crisis_type"].value_counts(normalize=True) * 100).round(2).to_dict()
    return {
        "row_count": int(len(classification)),
        "counts": {k: int(v) for k, v in counts.items()},
        "pct": {k: float(v) for k, v in pcts.items()},
        "first_date": str(classification.index.min()) if len(classification) else None,
        "last_date": str(classification.index.max()) if len(classification) else None,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base-dir", type=str, default=None)
    p.add_argument("--quiet", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    features_path = discover_features_path(Path(args.base_dir) if args.base_dir else None)
    if features_path is None:
        print(
            "ERROR: daily_features.parquet not found. Run "
            "tools/run_crisis_signal_builder.py first.",
            file=sys.stderr,
        )
        return 2
    features = pd.read_parquet(features_path)
    if features.empty:
        print("ERROR: daily_features.parquet is empty.", file=sys.stderr)
        return 2
    if not args.quiet:
        print(f"features:    {features_path.relative_to(ROOT)}  ({len(features)} rows)")
    thr = Thresholds()
    classification = classify_rows(features, thr)
    out_dir = features_path.parent
    csv_path = out_dir / "daily_classification.csv"
    audit_path = out_dir / "classification_audit.json"
    # Persist with date as a column so consumers can read it without parsing index
    csv_out = classification.copy()
    csv_out.insert(0, "date", csv_out.index.strftime("%Y-%m-%d"))
    csv_out.to_csv(csv_path, index=False)
    summary = classification_summary(classification)
    summary["thresholds"] = thr.__dict__
    audit_path.write_text(json.dumps(summary, indent=2, default=str))
    if not args.quiet:
        print(f"classification: {csv_path.relative_to(ROOT)}")
        print(f"audit:          {audit_path.relative_to(ROOT)}")
        for k, v in summary["counts"].items():
            print(f"  {k:18s} {v:6d}  ({summary['pct'].get(k, 0):.2f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
