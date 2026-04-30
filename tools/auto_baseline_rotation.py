#!/usr/bin/env python3
"""auto_baseline_rotation — Phase 17 v3 Layer 14 (2026-04-30) automated baseline rotation.

User insight (2026-04-29):
  "auto baseline rotation"

Reads the most recent FULL rebuild metrics, compares against the
CURRENT_BASELINE dict in run_local.py, and rotates the baseline if
the ship gate passes.

Ship gate (matches CLAUDE.md "Ship gate" section):
    ΔCAGR     >= +0.5pp
    ΔSharpe   >= -0.05
    ΔMaxDD    >= -3pp     (positive delta = less drawdown = better)
    sleeve early_scout >= 4   (Phase 8 collapse regression guard)

If gate passes:
    1. Update CURRENT_BASELINE dict literal in run_local.py
    2. Print summary
    3. Optional: archive previous baseline as PRIOR_BASELINE_{date} dict

Output
======
    Prints PASS / FAIL verdict + delta table.
    On PASS: writes back run_local.py (caller commits + pushes).

Usage
=====
    python tools/auto_baseline_rotation.py
    python tools/auto_baseline_rotation.py --metrics path/to/backtest_metrics.json
    python tools/auto_baseline_rotation.py --dry-run     # no file modify

Notes
=====
This tool does NOT commit or push. The wrapping GitHub workflow
(auto_baseline_rotation_weekly.yml) handles git side-effects.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
RUN_LOCAL_PATH = REPO_ROOT / "run_local.py"

# Default candidate metric files (first existing wins)
DEFAULT_METRICS_CANDIDATES = [
    "outputs/backtest_metrics.json",
    "cloud_results/full/backtest_metrics.json",
    "cloud_results/backtest_metrics.json",
]

# Ship gate thresholds (matches CLAUDE.md)
DELTA_CAGR_MIN = 0.005      # +0.5 pp
DELTA_SHARPE_MIN = -0.05
DELTA_MAXDD_MIN = -0.03     # MaxDD delta >= -3pp (less drawdown is better)
EARLY_SCOUT_MIN = 4


def find_metrics_file(override: Optional[str]) -> Optional[Path]:
    if override:
        p = Path(override)
        return p if p.exists() else None
    for rel in DEFAULT_METRICS_CANDIDATES:
        p = REPO_ROOT / rel
        if p.exists():
            return p
    return None


def parse_current_baseline(text: str) -> Optional[dict]:
    """Extract the CURRENT_BASELINE dict literal as a parsed object.

    Uses ast to evaluate the dict subexpression safely.
    """
    import ast
    m = re.search(r"^CURRENT_BASELINE\s*=\s*", text, flags=re.M)
    if not m:
        return None
    start = m.end()
    # Walk to find matching closing brace
    depth = 0
    i = start
    while i < len(text):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                literal = text[start:end]
                try:
                    return ast.literal_eval(literal)
                except Exception:
                    return None
        i += 1
    return None


def replace_current_baseline(text: str, new_dict: dict) -> str:
    """Replace the CURRENT_BASELINE dict literal in run_local.py text."""
    m = re.search(r"^CURRENT_BASELINE\s*=\s*", text, flags=re.M)
    if not m:
        raise ValueError("CURRENT_BASELINE assignment not found in run_local.py")
    start = m.end()
    depth = 0
    i = start
    while i < len(text):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                rendered = json_to_python_dict_literal(new_dict)
                return text[: start] + rendered + text[end:]
        i += 1
    raise ValueError("could not find end of CURRENT_BASELINE dict")


def json_to_python_dict_literal(obj, indent: int = 0) -> str:
    """Render a Python dict / list / scalar as a multi-line literal
    matching the project style (4-space indent, double-quoted keys)."""
    pad = "    " * indent
    inner = "    " * (indent + 1)
    if isinstance(obj, dict):
        if not obj:
            return "{}"
        lines = ["{"]
        for k, v in obj.items():
            lines.append(f"{inner}{json.dumps(k)}: {json_to_python_dict_literal(v, indent + 1)},")
        lines.append(f"{pad}" + "}")
        return "\n".join(lines)
    if isinstance(obj, list):
        if not obj:
            return "[]"
        return "[" + ", ".join(json_to_python_dict_literal(x, indent + 1) for x in obj) + "]"
    if obj is None:
        return "None"
    if isinstance(obj, bool):
        return "True" if obj else "False"
    if isinstance(obj, (int, float)):
        return repr(obj)
    return json.dumps(obj)


def evaluate_gate(baseline: dict, candidate: dict) -> tuple[bool, list[str]]:
    msgs: list[str] = []
    bl_cagr = float(baseline.get("cagr", 0.0))
    bl_sharpe = float(baseline.get("sharpe", 0.0))
    bl_maxdd = float(baseline.get("max_dd", 0.0))
    cd_cagr = float(candidate.get("cagr", 0.0))
    cd_sharpe = float(candidate.get("sharpe", 0.0))
    cd_maxdd = float(candidate.get("max_dd", 0.0))
    d_cagr = cd_cagr - bl_cagr
    d_sharpe = cd_sharpe - bl_sharpe
    d_maxdd = cd_maxdd - bl_maxdd

    pass_cagr = d_cagr >= DELTA_CAGR_MIN
    pass_sharpe = d_sharpe >= DELTA_SHARPE_MIN
    pass_maxdd = d_maxdd >= DELTA_MAXDD_MIN

    sleeve_counts = candidate.get("sleeve_counts_reference") or {}
    early = int(sleeve_counts.get("early_scout", 0)) if isinstance(sleeve_counts, dict) else 0
    pass_sleeve = early >= EARLY_SCOUT_MIN

    msgs.append(f"ΔCAGR    {d_cagr:+.4f}  ({'PASS' if pass_cagr else 'FAIL'}; min {DELTA_CAGR_MIN})")
    msgs.append(f"ΔSharpe  {d_sharpe:+.4f}  ({'PASS' if pass_sharpe else 'FAIL'}; min {DELTA_SHARPE_MIN})")
    msgs.append(f"ΔMaxDD   {d_maxdd:+.4f}  ({'PASS' if pass_maxdd else 'FAIL'}; min {DELTA_MAXDD_MIN})")
    msgs.append(f"early_scout count {early}  ({'PASS' if pass_sleeve else 'FAIL'}; min {EARLY_SCOUT_MIN})")
    overall = pass_cagr and pass_sharpe and pass_maxdd and pass_sleeve
    return overall, msgs


def build_candidate_baseline(metrics: dict, name: str) -> dict:
    """Map raw backtest_metrics.json to CURRENT_BASELINE dict shape."""
    sleeve_counts = metrics.get("sleeve_counts") or metrics.get("sleeve_counts_reference") or {}
    return {
        "name": name,
        "cagr": float(metrics.get("strategy_cagr") or metrics.get("cagr") or 0.0),
        "sharpe": float(metrics.get("strategy_sharpe") or metrics.get("sharpe") or 0.0),
        "max_dd": float(metrics.get("strategy_max_dd") or metrics.get("max_dd") or 0.0),
        "ir": float(metrics.get("ir") or 0.0),
        "avg_turnover_monthly": float(metrics.get("avg_turnover_monthly") or 0.0),
        "avg_stock_names": float(metrics.get("avg_stock_names") or 0.0),
        "beat_month_ratio": float(metrics.get("beat_month_ratio") or 0.0),
        "excess_cagr": float(metrics.get("excess_cagr") or 0.0),
        "sleeve_counts_reference": {
            "core_compounder": int(sleeve_counts.get("core_compounder", 0)) if isinstance(sleeve_counts, dict) else 0,
            "future_winner": int(sleeve_counts.get("future_winner", 0)) if isinstance(sleeve_counts, dict) else 0,
            "early_scout": int(sleeve_counts.get("early_scout", 0)) if isinstance(sleeve_counts, dict) else 0,
        },
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--metrics", default=None, help="path to backtest_metrics.json")
    p.add_argument("--name", default=None, help="rotation name (default: auto-generated)")
    p.add_argument("--dry-run", action="store_true", help="evaluate only; do not modify run_local.py")
    args = p.parse_args()

    metrics_path = find_metrics_file(args.metrics)
    if metrics_path is None:
        print("[auto-baseline] ERROR: no metrics file found", file=sys.stderr)
        for c in DEFAULT_METRICS_CANDIDATES:
            print(f"                tried: {c}", file=sys.stderr)
        return 2
    metrics = json.loads(metrics_path.read_text())

    text = RUN_LOCAL_PATH.read_text()
    baseline = parse_current_baseline(text)
    if baseline is None:
        print("[auto-baseline] ERROR: could not parse CURRENT_BASELINE", file=sys.stderr)
        return 2

    name = args.name or f"AUTO ROTATION {metrics_path.parent.name} {metrics.get('asof', '')}"
    candidate = build_candidate_baseline(metrics, name)

    print(f"[auto-baseline] metrics file: {metrics_path}")
    print(f"[auto-baseline] candidate: CAGR={candidate['cagr']:.4f} Sharpe={candidate['sharpe']:.4f} "
          f"MaxDD={candidate['max_dd']:.4f}")
    print(f"[auto-baseline] baseline:  CAGR={baseline['cagr']:.4f} Sharpe={baseline['sharpe']:.4f} "
          f"MaxDD={baseline['max_dd']:.4f}")

    pass_, msgs = evaluate_gate(baseline, candidate)
    for m in msgs:
        print(f"[auto-baseline]   {m}")

    verdict = "SHIP" if pass_ else "HOLD"
    print(f"[auto-baseline] verdict: {verdict}")

    if not pass_:
        return 1

    if args.dry_run:
        print("[auto-baseline] --dry-run: skipping run_local.py update")
        return 0

    new_text = replace_current_baseline(text, candidate)
    RUN_LOCAL_PATH.write_text(new_text)
    print(f"[auto-baseline] wrote {RUN_LOCAL_PATH} (CURRENT_BASELINE rotated to '{candidate['name']}')")
    return 0


if __name__ == "__main__":
    sys.exit(main())
