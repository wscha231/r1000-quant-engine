#!/usr/bin/env python3
"""Evaluate aggressive lab discovery gates for one experiment."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from aggressive_lab_common import (
    ROOT,
    ensure_required_outputs,
    load_yaml,
    read_json,
    safe_float,
    write_json,
)


def _metric(payload: dict[str, Any], key: str) -> float | None:
    if key in payload:
        return safe_float(payload.get(key))
    main = payload.get("main") or {}
    return safe_float(main.get(key))


def evaluate_discovery(
    experiment_dir: Path,
    baseline_metrics_path: Path,
    gates_path: Path,
) -> dict[str, Any]:
    metrics = read_json(experiment_dir / "metrics.json", {}) or {}
    baseline = read_json(baseline_metrics_path, {}) or {}
    gates = load_yaml(gates_path)
    pass_logic = gates.get("pass_logic", {}) if isinstance(gates, dict) else {}
    primary = pass_logic.get("primary_improvements", {}) or {}
    safety = pass_logic.get("required_safety_checks", {}) or {}
    required_outputs = gates.get("required_outputs", []) if isinstance(gates, dict) else []

    exp_id = metrics.get("experiment_id") or experiment_dir.name
    is_control = bool(metrics.get("control")) or exp_id == "E0_baseline_latest"

    exp_cagr = _metric(metrics, "cagr")
    base_cagr = _metric(baseline, "cagr")
    exp_maxdd = _metric(metrics, "max_dd")
    base_maxdd = _metric(baseline, "max_dd")
    exp_sharpe = _metric(metrics, "sharpe")
    base_sharpe = _metric(baseline, "sharpe")
    exp_turnover = _metric(metrics, "avg_turnover_monthly")
    base_turnover = _metric(baseline, "avg_turnover_monthly")

    deltas = {
        "cagr_improvement_pp": None if exp_cagr is None or base_cagr is None else (exp_cagr - base_cagr) * 100.0,
        "maxdd_improvement_pp": None if exp_maxdd is None or base_maxdd is None else (exp_maxdd - base_maxdd) * 100.0,
        "sharpe_improvement": None if exp_sharpe is None or base_sharpe is None else exp_sharpe - base_sharpe,
        "turnover_worsening_pp": None
        if exp_turnover is None or base_turnover is None
        else (exp_turnover - base_turnover) * 100.0,
    }

    primary_checks = {
        "cagr": (deltas["cagr_improvement_pp"] is not None)
        and (deltas["cagr_improvement_pp"] >= float(primary.get("cagr_improvement_pp_min", 2.0))),
        "maxdd": (deltas["maxdd_improvement_pp"] is not None)
        and (deltas["maxdd_improvement_pp"] >= float(primary.get("maxdd_improvement_pp_min", 2.0))),
        "sharpe": (deltas["sharpe_improvement"] is not None)
        and (deltas["sharpe_improvement"] >= float(primary.get("sharpe_improvement_min", 0.08))),
    }
    output_checks = ensure_required_outputs(experiment_dir, list(required_outputs))
    turnover_limit = float(safety.get("turnover_worsening_pp_max", 10.0))
    turnover_ok = deltas["turnover_worsening_pp"] is None or deltas["turnover_worsening_pp"] <= turnover_limit
    outputs_ok = all(output_checks.values())

    passed = (not is_control) and any(primary_checks.values()) and turnover_ok and outputs_ok

    return {
        "experiment_id": exp_id,
        "control": is_control,
        "passed_discovery": bool(passed),
        "reason": "control_baseline_not_promotable" if is_control else ("passed" if passed else "gate_failed"),
        "deltas": deltas,
        "primary_checks": primary_checks,
        "safety_checks": {
            "turnover_ok": turnover_ok,
            "required_outputs_exist": outputs_ok,
        },
        "required_outputs": output_checks,
        "thresholds": {
            "primary_improvements": primary,
            "required_safety_checks": safety,
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Discovery Gate Report",
        "",
        f"- Experiment: `{report.get('experiment_id')}`",
        f"- Control: `{report.get('control')}`",
        f"- Passed discovery: `{report.get('passed_discovery')}`",
        f"- Reason: `{report.get('reason')}`",
        "",
        "## Deltas",
        "",
    ]
    for key, value in (report.get("deltas") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## Required Outputs")
    lines.append("")
    for key, value in (report.get("required_outputs") or {}).items():
        lines.append(f"- `{key}`: `{value}`")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-dir", required=True)
    parser.add_argument("--baseline-metrics", required=True)
    parser.add_argument("--discovery-gates", default="research/aggressive_lab_202605/discovery_gates.yaml")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    exp_dir = Path(args.experiment_dir)
    if not exp_dir.is_absolute():
        exp_dir = ROOT / exp_dir
    base = Path(args.baseline_metrics)
    if not base.is_absolute():
        base = ROOT / base
    gates = Path(args.discovery_gates)
    if not gates.is_absolute():
        gates = ROOT / gates
    report = evaluate_discovery(exp_dir, base, gates)
    out_json = Path(args.out) if args.out else exp_dir / "gate_report.json"
    if not out_json.is_absolute():
        out_json = ROOT / out_json
    write_json(out_json, report)
    out_md = out_json.with_suffix(".md")
    out_md.write_text(render_markdown(report), encoding="utf-8")
    print(f"[gates] wrote {out_json}")
    print(f"[gates] wrote {out_md}")
    return 0 if report.get("control") or report.get("passed_discovery") else 1


if __name__ == "__main__":
    raise SystemExit(main())
