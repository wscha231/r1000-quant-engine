#!/usr/bin/env python3
"""aggregate_portfolio_performance — combined NAV / CAGR across sleeves.

Reads multiple sleeve portfolios (core ML / concentrated / event-driven),
applies a capital-allocation split, and reports per-sleeve + aggregate
metrics. Solves the user's pain: "각각노는것 같다, 평가는 포트별 전체
총합으로 하는게 맞지않나" — multiple sleeves should still roll up to one
total CAGR.

Inputs (auto-detect, fall back to defaults):
  outputs/portfolio_latest.csv                   (core ML)
  outputs/concentrated_portfolio_latest.csv      (concentrated)
  outputs/event_portfolio.json                   (event-driven, optional)
  outputs/backtest_metrics.json                  (core CAGR/Sharpe/MaxDD)
  outputs/concentrated_backtest_metrics.json     (concentrated metrics)

Outputs:
  outputs/aggregate_performance.json
  stdout: pretty table

Allocation:
  --core 0.60 --concentrated 0.30 --event 0.10
  Default: 60/30/10. Must sum to 1.0.

Usage:
    py -3 tools/aggregate_portfolio_performance.py
    py -3 tools/aggregate_portfolio_performance.py --core 0.70 --concentrated 0.30 --event 0.0
    py -3 tools/aggregate_portfolio_performance.py --base-dir cloud_results/full_rebuild/latest_global_alpha_universe

Aggregate math:
  - aggregate_cagr_target = sum(allocation_i * sleeve_cagr_i)
    (linear approximation — true compound is slightly higher, but the
    approximation is dominant enough for sleeve-mix decision-making.)
  - aggregate_max_dd_proxy = sum(allocation_i * sleeve_max_dd_i)
    (this is OPTIMISTIC because correlated drawdowns happen together;
    a more realistic estimate would compute correlation-weighted DD,
    but that requires daily-level NAV history of each sleeve.)

Use this tool's output as the headline metric for portfolio-level
decisions; per-sleeve metrics for sleeve-level tuning.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

import pandas as pd


def _safe_load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _safe_load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def _format_pct(v: Optional[float]) -> str:
    if v is None or pd.isna(v):
        return "  N/A "
    return f"{float(v) * 100:+6.2f}%"


def _format_ratio(v: Optional[float]) -> str:
    if v is None or pd.isna(v):
        return " N/A "
    return f"{float(v):5.3f}"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base-dir", default="outputs", help="directory containing the *_latest files")
    p.add_argument("--core", type=float, default=0.60, help="core ML allocation (default 0.60)")
    p.add_argument("--concentrated", type=float, default=0.30, help="concentrated allocation (default 0.30)")
    p.add_argument("--event", type=float, default=0.10, help="event-driven allocation (default 0.10)")
    p.add_argument("--out", default=None, help="output JSON path (default <base-dir>/aggregate_performance.json)")
    args = p.parse_args()

    alloc_total = args.core + args.concentrated + args.event
    if abs(alloc_total - 1.0) > 1e-3:
        print(f"WARN: allocations sum to {alloc_total:.3f}, not 1.000. Normalizing.", file=sys.stderr)
        args.core /= alloc_total
        args.concentrated /= alloc_total
        args.event /= alloc_total

    base = Path(args.base_dir)
    out_path = Path(args.out) if args.out else base / "aggregate_performance.json"

    core_metrics = _safe_load_json(base / "backtest_metrics.json")
    conc_metrics = _safe_load_json(base / "concentrated_backtest_metrics.json")
    core_pf = _safe_load_csv(base / "portfolio_latest.csv")
    conc_pf = _safe_load_csv(base / "concentrated_portfolio_latest.csv")
    event_pf_payload = _safe_load_json(base / "event_portfolio.json")
    event_metrics = _safe_load_json(base / "event_portfolio_metrics.json")

    sleeves = {
        "core_ml": {
            "allocation": float(args.core),
            "cagr": float(core_metrics.get("strategy_cagr", core_metrics.get("cagr", float("nan")))),
            "sharpe": float(core_metrics.get("strategy_sharpe", core_metrics.get("sharpe", float("nan")))),
            "max_dd": float(core_metrics.get("strategy_max_dd", core_metrics.get("max_dd", float("nan")))),
            "ir": float(core_metrics.get("ir", float("nan"))),
            "n_holdings": int(len(core_pf)) if not core_pf.empty else 0,
        },
        "concentrated": {
            "allocation": float(args.concentrated),
            "cagr": float(conc_metrics.get("strategy_cagr", conc_metrics.get("cagr", float("nan")))),
            "sharpe": float(conc_metrics.get("strategy_sharpe", conc_metrics.get("sharpe", float("nan")))),
            "max_dd": float(conc_metrics.get("strategy_max_dd", conc_metrics.get("max_dd", float("nan")))),
            "ir": float(conc_metrics.get("ir", float("nan"))),
            "n_holdings": int(len(conc_pf)) if not conc_pf.empty else 0,
        },
        "event_driven": {
            "allocation": float(args.event),
            "cagr": float(event_metrics.get("cagr", float("nan"))),
            "sharpe": float(event_metrics.get("sharpe", float("nan"))),
            "max_dd": float(event_metrics.get("max_dd", float("nan"))),
            "ir": float(event_metrics.get("ir", float("nan"))),
            "n_holdings": int(len(event_pf_payload.get("holdings", []))) if event_pf_payload else 0,
        },
    }

    # Aggregate (linear approximation; see file docstring for caveat).
    aggregate_cagr = 0.0
    aggregate_max_dd = 0.0
    aggregate_sharpe_weighted = 0.0
    valid_alloc_sum = 0.0
    for s in sleeves.values():
        if pd.isna(s["cagr"]):
            continue
        aggregate_cagr += s["allocation"] * s["cagr"]
        aggregate_max_dd += s["allocation"] * (s["max_dd"] if pd.notna(s["max_dd"]) else 0.0)
        if pd.notna(s["sharpe"]):
            aggregate_sharpe_weighted += s["allocation"] * s["sharpe"]
            valid_alloc_sum += s["allocation"]
    aggregate = {
        "cagr_linear_approx": aggregate_cagr,
        "max_dd_proxy": aggregate_max_dd,
        "sharpe_weighted": (aggregate_sharpe_weighted / valid_alloc_sum) if valid_alloc_sum > 0 else float("nan"),
        "total_n_holdings": sum(s["n_holdings"] for s in sleeves.values()),
        "allocations_sum": sum(s["allocation"] for s in sleeves.values()),
    }

    payload = {
        "as_of": pd.Timestamp.utcnow().isoformat(),
        "sleeves": sleeves,
        "aggregate": aggregate,
        "notes": [
            "cagr_linear_approx is the allocation-weighted average of sleeve CAGRs.",
            "True compound aggregate is slightly higher when sleeves rebalance independently.",
            "max_dd_proxy assumes simultaneous worst-case across sleeves (pessimistic).",
            "Real DD depends on inter-sleeve correlation and is captured only in",
            "  daily-NAV-level aggregation (TODO: P11b lifetime NAV ledger).",
        ],
    }

    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # Pretty-print
    print()
    print("=" * 80)
    print("Aggregate Portfolio Performance")
    print("=" * 80)
    print(f"  base_dir: {base}")
    print(f"  output:   {out_path}")
    print()
    header = f"{'sleeve':<14s} {'alloc':>7s} {'CAGR':>8s} {'Sharpe':>7s} {'MaxDD':>8s} {'IR':>7s} {'N':>4s}"
    print(header)
    print("-" * len(header))
    for name, s in sleeves.items():
        print(
            f"{name:<14s} "
            f"{s['allocation']*100:>6.1f}% "
            f"{_format_pct(s['cagr']):>8s} "
            f"{_format_ratio(s['sharpe']):>7s} "
            f"{_format_pct(s['max_dd']):>8s} "
            f"{_format_ratio(s['ir']):>7s} "
            f"{s['n_holdings']:>4d}"
        )
    print("-" * len(header))
    print(
        f"{'AGGREGATE':<14s} "
        f"{aggregate['allocations_sum']*100:>6.1f}% "
        f"{_format_pct(aggregate['cagr_linear_approx']):>8s} "
        f"{_format_ratio(aggregate['sharpe_weighted']):>7s} "
        f"{_format_pct(aggregate['max_dd_proxy']):>8s} "
        f"{'    ':>7s} "
        f"{aggregate['total_n_holdings']:>4d}"
    )
    print()
    print("Notes:")
    for n in payload["notes"]:
        print(f"  - {n}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
