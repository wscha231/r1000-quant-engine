#!/usr/bin/env python3
"""Compare the source Full Rebuild's integrated replay summary against the
sidecar-only re-run's summary, and emit a human-readable delta report.

The whole point of the sidecar-only loop: it isolates the effect of a
sidecar-stage code change (crisis_score formula, governor diagnostics,
verdict format, threshold learning) on the observable replay outputs --
without paying the 4-hour cost of re-collecting macro data and re-running
walk-forward training.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _safe_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _leg_metrics(summary: dict[str, Any], portfolio_kind: str) -> dict[str, Any]:
    for leg in summary.get("legs", []):
        if leg.get("portfolio_kind") == portfolio_kind:
            return leg
    return {}


def _verdict(leg: dict[str, Any]) -> dict[str, float | None]:
    verdict = leg.get("verdict") or {}
    return {
        "base_cagr": _safe_float(verdict.get("base_cagr")),
        "gov_cagr": _safe_float(verdict.get("governed_cagr")),
        "cagr_delta_pp": _safe_float(verdict.get("cagr_delta_pp")),
        "base_max_dd": _safe_float(verdict.get("base_max_dd")),
        "gov_max_dd": _safe_float(verdict.get("governed_max_dd")),
        "mdd_delta_pp": _safe_float(verdict.get("mdd_delta_pp")),
        "gates_pass": verdict.get("gates_pass"),
    }


def render(source_run_id: str, source: dict[str, Any], fixed: dict[str, Any], crisis_diag: dict[str, Any]) -> str:
    lines = [
        f"# Sidecar-only verification: source run {source_run_id} vs fixed code",
        "",
        "This is NOT a full backtest. It re-runs only the modified sidecar code over",
        "the source run's already-built features/books/metrics. Use it to confirm",
        "that a sidecar-stage change does what was intended, before paying for a",
        "full rebuild.",
        "",
        "## Crisis score coverage on the source features",
        "",
    ]
    if crisis_diag.get("status") != "ok":
        lines.append(f"- status: `{crisis_diag.get('status', 'absent')}`")
    else:
        lines.extend([
            f"- live components: `{crisis_diag.get('live_components')}`",
            f"- dead components: `{crisis_diag.get('dead_components')}`",
            f"- pre-renormalization weight ceiling: `{crisis_diag.get('pre_renorm_ceiling')}`",
            f"- renormalization active: `{crisis_diag.get('renormalization_active')}`",
            "",
            "| metric | OLD score (pre-fix) | NEW score (renormalized) |",
            "|---|---|---|",
        ])
        new = crisis_diag.get("score_new", {}) or {}
        old = crisis_diag.get("score_old_for_comparison", {}) or {}
        for key in ("max", "p99", "p95", "p90", "mean", "days_caution_default", "days_defense_default", "days_crisis_default"):
            lines.append(f"| {key} | {old.get(key)} | {new.get(key)} |")

    lines.extend(["", "## Integrated replay (broker-ledger next-close)", ""])
    for kind in ("main", "concentrated"):
        src = _verdict(_leg_metrics(source, kind))
        fix = _verdict(_leg_metrics(fixed, kind))
        lines.extend([
            f"### {kind}",
            "",
            "| | source run | fixed code | delta |",
            "|---|---|---|---|",
        ])
        for label, key, fmt in (
            ("base CAGR", "base_cagr", lambda v: f"{v:.4f}" if v is not None else "-"),
            ("gov  CAGR", "gov_cagr", lambda v: f"{v:.4f}" if v is not None else "-"),
            ("CAGR delta pp", "cagr_delta_pp", lambda v: f"{v:+.2f}" if v is not None else "-"),
            ("base MDD", "base_max_dd", lambda v: f"{v:.4f}" if v is not None else "-"),
            ("gov  MDD", "gov_max_dd", lambda v: f"{v:.4f}" if v is not None else "-"),
            ("MDD delta pp", "mdd_delta_pp", lambda v: f"{v:+.2f}" if v is not None else "-"),
        ):
            s = src.get(key)
            f = fix.get(key)
            delta = (f - s) if isinstance(s, (int, float)) and isinstance(f, (int, float)) else None
            lines.append(f"| {label} | {fmt(s)} | {fmt(f)} | {fmt(delta) if delta is not None else '-'} |")
        lines.extend([
            "",
            f"- source gates_pass: `{src.get('gates_pass')}`",
            f"- fixed  gates_pass: `{fix.get('gates_pass')}`",
            "",
        ])
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-run-id", required=True)
    p.add_argument("--source-summary", required=True, help="Path to source run's integrated replay summary.json")
    p.add_argument("--fixed-summary", required=True, help="Path to this re-runs integrated replay summary.json")
    p.add_argument("--crisis-diag", default="", help="Optional path to diagnose_crisis_features output")
    p.add_argument("--output", default="outputs/sidecar_only_verify/delta_report.md")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    source = load(repo_path(args.source_summary))
    fixed = load(repo_path(args.fixed_summary))
    crisis_diag = load(repo_path(args.crisis_diag)) if args.crisis_diag else {}
    report = render(args.source_run_id, source, fixed, crisis_diag)
    out = repo_path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"[sidecar-delta] wrote {out} ({len(report.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
