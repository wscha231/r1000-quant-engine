#!/usr/bin/env python3
"""phase15_s1a ablation summary.

Reads baseline + 3 ablation snapshots and reports delta CAGR / Sharpe / MaxDD
for main blend and concentrated per variant. Surfaces shipping recommendation:
the subset of factor-drops that keeps main flat-to-positive AND preserves
the concentrated gain seen in the full 3-factor treatment (b2zq3xkam).

Run (after ablation bbl6mkuiq completes):
  py -3 research/phase15_s1a_ab/ablation_summary.py
"""
from __future__ import annotations

import json
from pathlib import Path

BASE = Path(__file__).parent
ABL = BASE / "ablation"

VARIANTS = [
    ("baseline", BASE / "baseline_backtest_metrics.json", BASE / "baseline_concentrated_backtest_metrics.json"),
    ("full_prune_all_3 (b2zq3xkam)", BASE / "treatment_backtest_metrics.json", BASE / "treatment_concentrated_backtest_metrics.json"),
    ("drop_ft only (A)", ABL / "A_ft_backtest_metrics.json", ABL / "A_ft_concentrated_backtest_metrics.json"),
    ("drop_cf only (B)", ABL / "B_cf_backtest_metrics.json", ABL / "B_cf_concentrated_backtest_metrics.json"),
    ("drop_ub only (C)", ABL / "C_ub_backtest_metrics.json", ABL / "C_ub_concentrated_backtest_metrics.json"),
]


def loadj(p: Path):
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def pp(v):
    return f"{v*100:+.2f}pp" if v is not None else "n/a"


def pct(v):
    return f"{v*100:.2f}%" if v is not None else "n/a"


def main():
    rows = []
    base_m, base_c = None, None
    for name, bp, cp in VARIANTS:
        b = loadj(bp); c = loadj(cp)
        if name == "baseline":
            base_m, base_c = b, c
        if b is None or c is None:
            rows.append({"variant": name, "status": "NOT YET AVAILABLE"})
            continue
        row = {"variant": name}
        row["main_cagr"] = pct(b.get("cagr"))
        row["main_sharpe"] = f"{b.get('sharpe', 0):.3f}"
        row["main_maxdd"] = pct(b.get("max_dd"))
        row["conc_cagr"] = pct(c.get("strategy_cagr"))
        row["conc_sharpe"] = f"{c.get('sharpe', 0):.3f}"
        row["conc_maxdd"] = pct(c.get("max_dd"))
        if base_m and base_c and name != "baseline":
            row["dCAGR_main"] = pp(b["cagr"] - base_m["cagr"])
            row["dSharpe_main"] = f"{b['sharpe'] - base_m['sharpe']:+.4f}"
            row["dMaxDD_main"] = pp(b["max_dd"] - base_m["max_dd"])
            row["dCAGR_conc"] = pp(c["strategy_cagr"] - base_c["strategy_cagr"])
            row["dSharpe_conc"] = f"{c['sharpe'] - base_c['sharpe']:+.4f}"
            row["dMaxDD_conc"] = pp(c["max_dd"] - base_c["max_dd"])
            row["ship_main"] = "PASS" if (b["cagr"] - base_m["cagr"]) >= 0.005 else ("FLAT" if (b["cagr"] - base_m["cagr"]) >= -0.001 else "FAIL")
        rows.append(row)

    # Print
    print("=" * 110)
    print("Phase 15-S1a ablation summary")
    print("=" * 110)
    for r in rows:
        print()
        print(f"-- {r['variant']} --")
        if r.get("status") == "NOT YET AVAILABLE":
            print("  (run not yet produced output — wait for bbl6mkuiq)")
            continue
        print(f"  MAIN:  CAGR {r['main_cagr']}  Sharpe {r['main_sharpe']}  MaxDD {r['main_maxdd']}"
              + (f"   | dCAGR {r.get('dCAGR_main','-')}  dSharpe {r.get('dSharpe_main','-')}  dMaxDD {r.get('dMaxDD_main','-')}  ship={r.get('ship_main','-')}" if 'dCAGR_main' in r else ""))
        print(f"  CONC:  CAGR {r['conc_cagr']}  Sharpe {r['conc_sharpe']}  MaxDD {r['conc_maxdd']}"
              + (f"   | dCAGR {r.get('dCAGR_conc','-')}  dSharpe {r.get('dSharpe_conc','-')}  dMaxDD {r.get('dMaxDD_conc','-')}" if 'dCAGR_conc' in r else ""))

    # Recommendation
    print()
    print("=" * 110)
    print("Recommendation")
    print("=" * 110)
    print("Ship criteria: any single-factor drop where main_ship is PASS or FLAT AND conc_dCAGR > +0.50pp.")
    print("If one or two drops qualify, ship that combination (default cfg True for those sub-toggles).")
    print("If none qualify, keep all at default False; pivot to concentrated-only path (r1000_pipeline.py line ~11939)")
    print("or 15-S1b ML target horizon realign (FULL rebuild, ~2-3h).")


if __name__ == "__main__":
    main()
