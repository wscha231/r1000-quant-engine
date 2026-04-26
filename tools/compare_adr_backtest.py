#!/usr/bin/env python3
"""compare_adr_backtest — A/B verdict helper for r1000+adr universe.

Reads two backtest_metrics.json files (R1000 baseline vs R1000+ADR) and
prints a verdict against the ship gate:
    ΔCAGR ≥ +0.5pp AND ΔSharpe ≥ -0.05 AND ΔMaxDD ≥ -3pp

Usage:
    py -3 tools/compare_adr_backtest.py \\
        --baseline outputs/backtest_metrics.json \\
        --variant  outputs_adr/backtest_metrics.json

    # Compare against canonical CURRENT_BASELINE in run_local.py:
    py -3 tools/compare_adr_backtest.py --variant outputs/backtest_metrics.json --use-pinned-baseline

Companion to:
    .github/workflows/full_rebuild_manual.yml (use universe_mode r1000 + r1000+adr
    for the two FULL rebuilds, then compare with this script)

Exit codes:
    0  SHIP — all 3 ship gates pass
    1  REGRESS — at least one gate fails
    2  PARTIAL — CAGR/Sharpe gate borderline, MaxDD gate fails
    3  framework error
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Ship gate thresholds (per CLAUDE.md):
SHIP_GATE = {
    "delta_cagr_min_pp": 0.5,    # ≥ +0.5pp
    "delta_sharpe_min": -0.05,   # ≥ -0.05 (allow tiny regression)
    "delta_max_dd_min_pp": -3.0, # ≥ -3pp (positive delta = less DD = better)
}


def load_metrics(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"metrics file missing: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def get_pinned_baseline() -> dict:
    """Return CURRENT_BASELINE dict from run_local.py."""
    try:
        from run_local import CURRENT_BASELINE
        return CURRENT_BASELINE
    except Exception as e:
        raise RuntimeError(f"could not import CURRENT_BASELINE: {e}")


def verdict(baseline: dict, variant: dict) -> tuple[str, dict]:
    """Compute verdict + delta dict."""
    bl_cagr = float(baseline.get("strategy_cagr", baseline.get("cagr", 0)))
    var_cagr = float(variant.get("strategy_cagr", variant.get("cagr", 0)))
    bl_sharpe = float(baseline.get("strategy_sharpe", baseline.get("sharpe", 0)))
    var_sharpe = float(variant.get("strategy_sharpe", variant.get("sharpe", 0)))
    bl_dd = float(baseline.get("strategy_max_dd", baseline.get("max_dd", 0)))
    var_dd = float(variant.get("strategy_max_dd", variant.get("max_dd", 0)))

    deltas = {
        "delta_cagr_pp": (var_cagr - bl_cagr) * 100.0,
        "delta_sharpe": var_sharpe - bl_sharpe,
        "delta_max_dd_pp": (var_dd - bl_dd) * 100.0,   # positive = less DD = better
        "baseline_cagr": bl_cagr,
        "variant_cagr": var_cagr,
        "baseline_sharpe": bl_sharpe,
        "variant_sharpe": var_sharpe,
        "baseline_max_dd": bl_dd,
        "variant_max_dd": var_dd,
    }
    ok_cagr = deltas["delta_cagr_pp"] >= SHIP_GATE["delta_cagr_min_pp"]
    ok_sharpe = deltas["delta_sharpe"] >= SHIP_GATE["delta_sharpe_min"]
    ok_dd = deltas["delta_max_dd_pp"] >= SHIP_GATE["delta_max_dd_min_pp"]

    if ok_cagr and ok_sharpe and ok_dd:
        v = "SHIP"
    elif (ok_cagr or ok_sharpe) and ok_dd:
        v = "PARTIAL"
    else:
        v = "REGRESS"
    return v, deltas


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--baseline",
                   help="baseline backtest_metrics.json (e.g. R1000-only run)")
    p.add_argument("--variant",
                   help="variant backtest_metrics.json (e.g. R1000+ADR run)")
    p.add_argument("--use-pinned-baseline", action="store_true",
                   help="use run_local.py CURRENT_BASELINE instead of --baseline file")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    args = p.parse_args()

    if not args.variant:
        print("ERROR: --variant required", file=sys.stderr)
        return 3

    if args.use_pinned_baseline:
        baseline = get_pinned_baseline()
        baseline_label = baseline.get("name", "CURRENT_BASELINE")
    else:
        if not args.baseline:
            print("ERROR: pass --baseline FILE or --use-pinned-baseline", file=sys.stderr)
            return 3
        baseline = load_metrics(Path(args.baseline))
        baseline_label = args.baseline

    variant = load_metrics(Path(args.variant))
    v, deltas = verdict(baseline, variant)

    if args.json:
        print(json.dumps({
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "baseline": baseline_label,
            "variant": args.variant,
            "verdict": v,
            "deltas": deltas,
            "ship_gate": SHIP_GATE,
        }, indent=2))
    else:
        print("=" * 70)
        print(f"r1000+ADR backtest verdict — {datetime.now():%Y-%m-%d %H:%M}")
        print("=" * 70)
        print(f"  baseline: {baseline_label}")
        print(f"  variant:  {args.variant}")
        print()
        print(f"  CAGR    {deltas['baseline_cagr']*100:>7.2f}%  ->  "
              f"{deltas['variant_cagr']*100:>7.2f}%   ΔCAGR  {deltas['delta_cagr_pp']:+.2f}pp  "
              f"(gate ≥ {SHIP_GATE['delta_cagr_min_pp']:+.2f}pp)")
        print(f"  Sharpe  {deltas['baseline_sharpe']:>7.3f}   ->  "
              f"{deltas['variant_sharpe']:>7.3f}    ΔSharpe {deltas['delta_sharpe']:+.3f}  "
              f"(gate ≥ {SHIP_GATE['delta_sharpe_min']:+.3f})")
        print(f"  MaxDD   {deltas['baseline_max_dd']*100:>7.2f}%  ->  "
              f"{deltas['variant_max_dd']*100:>7.2f}%   ΔMaxDD {deltas['delta_max_dd_pp']:+.2f}pp  "
              f"(gate ≥ {SHIP_GATE['delta_max_dd_min_pp']:+.2f}pp)")
        print()
        symbol = {"SHIP": "✅", "PARTIAL": "🟡", "REGRESS": "❌"}[v]
        print(f"VERDICT: {symbol}  {v}")
        print()
        if v == "SHIP":
            print("  All 3 gates pass. ADR universe ready for production.")
            print("  Action: rotate CURRENT_BASELINE in run_local.py to reflect new metrics.")
        elif v == "PARTIAL":
            print("  CAGR or Sharpe gate borderline; MaxDD gate ok.")
            print("  Action: investigate which sleeve / regime drove the partial pass.")
        else:
            print("  At least one gate fails. ADR universe NOT ship-ready.")
            print("  Action: review per-ADR contribution; may need to filter by mcap or country.")

    return {"SHIP": 0, "PARTIAL": 2, "REGRESS": 1}[v]


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(2)
    except Exception as exc:
        print(f"\ncompare framework error: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(3)
