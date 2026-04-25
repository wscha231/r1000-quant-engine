"""r1000_l1_threshold_sweep - Find optimal L1 stop thresholds (or prove they don't work).

Sweep across hard_stop / trailing_stop combinations to identify a sweet spot
that improves risk-adjusted returns vs no stops. Or prove that for monthly
rebalanced concentrated strategy, stops are net-negative.

Tests 5x5 = 25 threshold combinations:
  hard:     [-0.08, -0.10, -0.12, -0.15, -0.20]
  trailing: [-0.10, -0.15, -0.20, -0.25, no trail]

Output: outputs/strategy_backtest/l1_sweep.csv
"""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from r1000_per_position_replay import (
    aggregate_monthly, metrics, replay_holdings,
)
from r1000_risk_sensing import RiskConfig


def main() -> int:
    h = pd.read_csv(
        r"G:/내 드라이브/r1000_top30_institutional/outputs/reports/concentrated_strategy_holdings.csv"
    )
    h_sub = h[
        (h["target_n"] == 3)
        & (h["weighting_mode"] == "score_power")
        & (h["active_rebalance_interval_months"] == 1)
    ].copy()
    print(f"[load] {len(h_sub)} holdings")

    # Baseline (no stops) — set thresholds so they never trigger
    base_cfg = RiskConfig(oneill_hard_stop_pct=-0.99, trailing_stop_pct=-0.99)
    print("\n[baseline] simulating no-stops...")
    pos_base = replay_holdings(h_sub, base_cfg, verbose=False)
    monthly_base = aggregate_monthly(pos_base)
    m_base = metrics(monthly_base["net_original"].values)
    print(f"Baseline (no stops):")
    for k, v in m_base.items():
        if isinstance(v, float):
            print(f"  {k:<14} {v:.2f}")

    # Sweep
    hards = [-0.08, -0.10, -0.12, -0.15, -0.20]
    trails = [-0.10, -0.15, -0.20, -0.25, -0.99]  # -0.99 = effectively no trail

    rows = []
    print("\n[sweep] 25 combinations:")
    print(f"  {'hard':>6} {'trail':>6} {'CAGR':>8} {'Sharpe':>7} {'MaxDD':>8} {'Calmar':>7} {'%Stop':>6}")
    print("  " + "-" * 60)
    for hard in hards:
        for trail in trails:
            cfg = RiskConfig(oneill_hard_stop_pct=hard, trailing_stop_pct=trail)
            pos = replay_holdings(h_sub, cfg, verbose=False)
            monthly = aggregate_monthly(pos)
            m = metrics(monthly["net_with_l1"].values)
            pct_stop = (pos["stop_triggered"].notna()).mean() * 100
            row = {
                "hard_stop_pct": hard * 100,
                "trail_stop_pct": trail * 100,
                "cagr_pct": m.get("cagr_pct", np.nan),
                "sharpe": m.get("sharpe", np.nan),
                "max_dd_pct": m.get("max_dd_pct", np.nan),
                "calmar": m.get("calmar", np.nan),
                "pct_stopped": pct_stop,
            }
            rows.append(row)
            trail_label = "none" if trail < -0.5 else f"{trail*100:.0f}%"
            print(f"  {hard*100:>5.0f}% {trail_label:>6} "
                  f"{m.get('cagr_pct', np.nan):>7.2f}% "
                  f"{m.get('sharpe', np.nan):>7.2f} "
                  f"{m.get('max_dd_pct', np.nan):>7.2f}% "
                  f"{m.get('calmar', np.nan):>7.2f} "
                  f"{pct_stop:>5.1f}%")

    df = pd.DataFrame(rows)
    df["beats_baseline_sharpe"] = df["sharpe"] > m_base["sharpe"]
    df["beats_baseline_cagr"] = df["cagr_pct"] > m_base["cagr_pct"]
    df["beats_baseline_calmar"] = df["calmar"] > m_base["calmar"]

    out_path = Path("outputs/strategy_backtest/l1_sweep.csv")
    df.to_csv(out_path, index=False)
    print(f"\n[save] {out_path}")

    # Find best by Calmar
    print()
    print(f"Baseline Calmar: {m_base['calmar']:.2f}")
    print()
    best_calmar = df.sort_values("calmar", ascending=False).head(5)
    print("Top 5 by Calmar (CAGR/|MaxDD|):")
    print(best_calmar[["hard_stop_pct", "trail_stop_pct", "cagr_pct",
                        "sharpe", "max_dd_pct", "calmar", "pct_stopped"]].to_string(index=False))

    # Any combination that beats baseline on all metrics?
    winners = df[df["beats_baseline_sharpe"] & df["beats_baseline_cagr"]
                  & df["beats_baseline_calmar"]]
    print()
    if len(winners) > 0:
        print(f"WINNERS (beat baseline on Sharpe + CAGR + Calmar): {len(winners)}")
        print(winners[["hard_stop_pct", "trail_stop_pct", "cagr_pct",
                        "sharpe", "max_dd_pct", "calmar"]].to_string(index=False))
    else:
        print("NO COMBINATION beats baseline on all 3 metrics.")
        print("CONCLUSION: For monthly-rebalanced concentrated 3-name,")
        print("            fixed-pct L1 stops are net-NEGATIVE.")
        print("            Need different risk mechanism (vol-adjusted, or")
        print("            confirmation-based, or skip L1).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
