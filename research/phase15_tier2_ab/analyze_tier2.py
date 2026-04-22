#!/usr/bin/env python3
"""Phase 15 Tier 2 A/B grid analyzer.

Reads research/phase15_tier2_ab/cells/*.json snapshots from run_tier2_grid.sh
and prints a delta table per cell vs A_baseline. Also prints ship gate
verdict (CAGR >= +0.5pp, Sharpe >= -0.05, MaxDD >= -3pp).

Run after run_tier2_grid.sh completes:
  py -3 research/phase15_tier2_ab/analyze_tier2.py
"""
from __future__ import annotations

import json
from pathlib import Path

CELLS_DIR = Path(__file__).parent / "cells"
CELLS = [
    "A_baseline",
    "B_r1_only",
    "C_r2_only",
    "D_r3_only",
    "E_all_r",
    "F_r_plus_a1",
    "G_p4_only",
    "H_p6c_only",
    "I_full_stack",
]


def loadj(p: Path):
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def pct(v):
    return f"{v*100:.2f}%" if v is not None else "n/a"


def pp(v):
    return f"{v*100:+.2f}pp" if v is not None else "n/a"


def ship_verdict(d_cagr, d_sharpe, d_maxdd):
    cagr_pass = d_cagr >= 0.005
    sharpe_pass = d_sharpe >= -0.05
    maxdd_pass = d_maxdd >= -0.03
    if cagr_pass and sharpe_pass and maxdd_pass:
        return "PASS"
    if (d_cagr >= -0.001) and sharpe_pass and maxdd_pass:
        return "FLAT"
    return "FAIL"


def main():
    base_main = loadj(CELLS_DIR / "A_baseline_backtest_metrics.json")
    base_conc = loadj(CELLS_DIR / "A_baseline_concentrated_backtest_metrics.json")
    if base_main is None:
        print("ERROR: A_baseline not found. Run run_tier2_grid.sh first.")
        return
    print("Phase 15 Tier 2 — A/B Grid Verdict")
    print("=" * 110)
    print(f"{'cell':<18} {'M.CAGR':>10} {'M.Sharpe':>10} {'M.MaxDD':>10} "
          f"{'dCAGR':>10} {'dSharpe':>10} {'dMaxDD':>10} {'ship':>6}")
    print("-" * 110)
    for cell in CELLS:
        m = loadj(CELLS_DIR / f"{cell}_backtest_metrics.json")
        if m is None:
            print(f"{cell:<18} (snapshot missing)")
            continue
        if cell == "A_baseline":
            print(f"{cell:<18} {pct(m['cagr']):>10} {m['sharpe']:>10.3f} {pct(m['max_dd']):>10}"
                  f" {'-':>10} {'-':>10} {'-':>10} {'base':>6}")
            continue
        dc = m["cagr"] - base_main["cagr"]
        ds = m["sharpe"] - base_main["sharpe"]
        dm = m["max_dd"] - base_main["max_dd"]
        verdict = ship_verdict(dc, ds, dm)
        print(f"{cell:<18} {pct(m['cagr']):>10} {m['sharpe']:>10.3f} {pct(m['max_dd']):>10}"
              f" {pp(dc):>10} {ds:>+10.4f} {pp(dm):>10} {verdict:>6}")

    print("\nConcentrated deltas (if available):")
    print(f"{'cell':<18} {'C.CAGR':>10} {'C.Sharpe':>10} {'C.MaxDD':>10} "
          f"{'dCAGR':>10} {'dSharpe':>10}")
    print("-" * 80)
    for cell in CELLS:
        c = loadj(CELLS_DIR / f"{cell}_concentrated_backtest_metrics.json")
        if c is None:
            continue
        if cell == "A_baseline" or base_conc is None:
            print(f"{cell:<18} {pct(c.get('strategy_cagr')):>10} {c.get('sharpe', 0):>10.3f} "
                  f"{pct(c.get('max_dd')):>10} {'-':>10} {'-':>10}")
            continue
        dc = c["strategy_cagr"] - base_conc["strategy_cagr"]
        ds = c["sharpe"] - base_conc["sharpe"]
        print(f"{cell:<18} {pct(c['strategy_cagr']):>10} {c['sharpe']:>10.3f} {pct(c['max_dd']):>10} "
              f"{pp(dc):>10} {ds:>+10.4f}")


if __name__ == "__main__":
    main()
