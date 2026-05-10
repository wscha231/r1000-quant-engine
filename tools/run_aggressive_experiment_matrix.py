#!/usr/bin/env python3
"""Run the full aggressive lab experiment matrix and aggregate results."""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aggressive_lab_common import ROOT, load_yaml, read_json, safe_float, write_csv_rows, write_json


DEFAULT_MATRIX = "research/aggressive_lab_202605/experiment_matrix.yaml"
DEFAULT_GATES = "research/aggressive_lab_202605/discovery_gates.yaml"


def _metric(payload: dict[str, Any], key: str) -> float | None:
    if key in payload:
        return safe_float(payload.get(key))
    main = payload.get("main") or {}
    return safe_float(main.get(key))


def _run_experiment(exp_id: str, matrix: str, gates: str, outputs_root: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "run_aggressive_lab.py"),
            "--matrix",
            matrix,
            "--discovery-gates",
            gates,
            "--experiment-id",
            exp_id,
            "--outputs-root",
            outputs_root,
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def _aggregate(outputs_root: Path, experiment_ids: list[str]) -> dict[str, Any]:
    baseline = read_json(outputs_root / "E0_baseline_latest" / "metrics.json", {}) or {}
    base_cagr = _metric(baseline, "cagr")
    base_maxdd = _metric(baseline, "max_dd")
    base_sharpe = _metric(baseline, "sharpe")
    base_turnover = _metric(baseline, "avg_turnover_monthly")
    rows: list[dict[str, Any]] = []
    for exp_id in experiment_ids:
        metrics = read_json(outputs_root / exp_id / "metrics.json", {}) or {}
        gate = read_json(outputs_root / exp_id / "gate_report.json", {}) or {}
        cagr = _metric(metrics, "cagr")
        maxdd = _metric(metrics, "max_dd")
        sharpe = _metric(metrics, "sharpe")
        turnover = _metric(metrics, "avg_turnover_monthly")
        cagr_delta = None if cagr is None or base_cagr is None else (cagr - base_cagr) * 100.0
        maxdd_delta = None if maxdd is None or base_maxdd is None else (maxdd - base_maxdd) * 100.0
        sharpe_delta = None if sharpe is None or base_sharpe is None else sharpe - base_sharpe
        turnover_delta = None if turnover is None or base_turnover is None else (turnover - base_turnover) * 100.0
        discovery_score = 0.0
        if cagr_delta is not None:
            discovery_score += cagr_delta
        if maxdd_delta is not None:
            discovery_score += maxdd_delta
        if sharpe_delta is not None:
            discovery_score += sharpe_delta * 10.0
        if turnover_delta is not None and turnover_delta > 0:
            discovery_score -= turnover_delta
        rows.append(
            {
                "experiment_id": exp_id,
                "status": metrics.get("status"),
                "category": metrics.get("category"),
                "backtest_executed": metrics.get("backtest_executed"),
                "passed_discovery": gate.get("passed_discovery"),
                "cagr": cagr,
                "cagr_delta_pp": cagr_delta,
                "max_dd": maxdd,
                "maxdd_delta_pp": maxdd_delta,
                "sharpe": sharpe,
                "sharpe_delta": sharpe_delta,
                "turnover": turnover,
                "turnover_delta_pp": turnover_delta,
                "discovery_score": discovery_score,
                "requires_full_challenger_backtest": metrics.get("requires_full_challenger_backtest")
                or metrics.get("requires_orchestrator_backtest")
                or metrics.get("requires_tactical_historical_backtest")
                or metrics.get("requires_weekly_historical_backtest"),
            }
        )
    ranked = sorted(rows, key=lambda row: safe_float(row.get("discovery_score"), -999.0) or -999.0, reverse=True)
    return {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "baseline_experiment": "E0_baseline_latest",
        "rows": rows,
        "ranked": ranked,
    }


def _render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Aggressive Lab Matrix Ranking",
        "",
        "This ranking is discovery-only. Passing discovery is not production approval.",
        "",
        "| Rank | Experiment | Status | Discovery | CAGR delta pp | MaxDD delta pp | Sharpe delta | Backtest | Notes |",
        "| ---: | --- | --- | --- | ---: | ---: | ---: | --- | --- |",
    ]
    for idx, row in enumerate(summary.get("ranked") or [], start=1):
        notes = "needs full challenger" if row.get("requires_full_challenger_backtest") else ""
        lines.append(
            "| {idx} | `{exp}` | `{status}` | `{disc}` | {cagr} | {dd} | {sharpe} | `{bt}` | {notes} |".format(
                idx=idx,
                exp=row.get("experiment_id"),
                status=row.get("status"),
                disc=row.get("passed_discovery"),
                cagr="" if row.get("cagr_delta_pp") is None else f"{row.get('cagr_delta_pp'):.2f}",
                dd="" if row.get("maxdd_delta_pp") is None else f"{row.get('maxdd_delta_pp'):.2f}",
                sharpe="" if row.get("sharpe_delta") is None else f"{row.get('sharpe_delta'):.3f}",
                bt=row.get("backtest_executed"),
                notes=notes,
            )
        )
    lines.extend(["", "## Interpretation", ""])
    lines.append("Most experiments are still snapshot/proxy adapters. The ranking is useful for prioritization, not promotion.")
    lines.append("E6 can pass discovery on drawdown improvement while still needing a position-aware risk replay.")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", default=DEFAULT_MATRIX)
    parser.add_argument("--discovery-gates", default=DEFAULT_GATES)
    parser.add_argument("--outputs-root", default="outputs/experiments")
    parser.add_argument("--keep-going", action="store_true", default=True)
    args = parser.parse_args()

    matrix = load_yaml(ROOT / args.matrix)
    experiment_ids = [str(exp.get("id")) for exp in matrix.get("experiments", []) or [] if exp.get("id")]
    outputs_root = Path(args.outputs_root)
    if not outputs_root.is_absolute():
        outputs_root = ROOT / outputs_root
    run_results = []
    rc = 0
    for exp_id in experiment_ids:
        result = _run_experiment(exp_id, args.matrix, args.discovery_gates, str(outputs_root))
        run_results.append({"experiment_id": exp_id, "returncode": result.returncode, "stdout": result.stdout[-4000:]})
        if result.returncode != 0:
            rc = max(rc, result.returncode)
            if not args.keep_going:
                break

    summary = _aggregate(outputs_root, experiment_ids)
    summary["run_results"] = run_results
    write_json(outputs_root / "experiment_matrix_summary.json", summary)
    write_csv_rows(
        outputs_root / "experiment_matrix_ranking.csv",
        summary["ranked"],
        [
            "experiment_id",
            "status",
            "category",
            "backtest_executed",
            "passed_discovery",
            "cagr",
            "cagr_delta_pp",
            "max_dd",
            "maxdd_delta_pp",
            "sharpe",
            "sharpe_delta",
            "turnover",
            "turnover_delta_pp",
            "discovery_score",
            "requires_full_challenger_backtest",
        ],
    )
    (outputs_root / "experiment_matrix_ranking.md").write_text(_render_markdown(summary), encoding="utf-8")
    print(f"[matrix] ran {len(run_results)} experiments")
    print(f"[matrix] wrote {outputs_root / 'experiment_matrix_ranking.md'}")
    return 0 if rc in (0, 1, 2) else rc


if __name__ == "__main__":
    raise SystemExit(main())
