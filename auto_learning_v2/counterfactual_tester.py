"""Counterfactual readiness and result summarization for AutoLearning v2."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from r1000_auto_learning_evidence import read_json, safe_float


HYPOTHESIS_EXPERIMENT_MAP = {
    "bear_rs_reversal_v1": "E1_auto_feature_gates_on",
    "main_future_alpha_concentration_v1": "E2_main_v2_balanced",
    "concentrated_neutral_25_v1": "E4_concentrated_balanced",
    "risk_governor_layered_exit_v1": "E6_risk_sensing_on",
    "alpha_sprint_breakout_fallback_v1": "E8_alpha_sprint_sidecar",
}


def _experiment_rows(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(row.get("experiment_id")): row for row in summary.get("ranked") or []}


def build_counterfactual_results(hypotheses: list[dict[str, Any]], root: str | Path) -> list[dict[str, Any]]:
    summary = read_json(Path(root) / "outputs" / "experiments" / "experiment_matrix_summary.json")
    experiments = _experiment_rows(summary)
    results: list[dict[str, Any]] = []
    for hypothesis in hypotheses:
        hid = str(hypothesis.get("id"))
        experiment_id = HYPOTHESIS_EXPERIMENT_MAP.get(hid)
        experiment = experiments.get(experiment_id or "", {})
        backtest_executed = experiment.get("backtest_executed")
        requires_full = bool(experiment.get("requires_full_challenger_backtest"))
        if not experiment_id:
            status = "infrastructure_or_guardrail"
        elif backtest_executed is True and not requires_full:
            status = "counterfactual_available"
        elif experiment:
            status = "needs_full_challenger_backtest"
        else:
            status = "missing_experiment"

        cagr_delta = safe_float(experiment.get("cagr_delta_pp"), 0.0) if experiment else None
        maxdd_delta = safe_float(experiment.get("maxdd_delta_pp"), 0.0) if experiment else None
        sharpe_delta = safe_float(experiment.get("sharpe_delta"), 0.0) if experiment else None
        passed_discovery = bool(experiment.get("passed_discovery")) if experiment else False
        production_ready = status == "counterfactual_available" and passed_discovery and cagr_delta is not None and cagr_delta >= 3.0
        results.append(
            {
                "hypothesis_id": hid,
                "experiment_id": experiment_id,
                "status": status,
                "backtest_executed": backtest_executed,
                "requires_full_challenger_backtest": requires_full,
                "passed_discovery": passed_discovery,
                "production_ready": production_ready,
                "cagr_delta_pp": cagr_delta,
                "maxdd_delta_pp": maxdd_delta,
                "sharpe_delta": sharpe_delta,
                "notes": _notes(status, experiment, hypothesis),
            }
        )
    return results


def _notes(status: str, experiment: dict[str, Any], hypothesis: dict[str, Any]) -> str:
    if status == "counterfactual_available":
        return "Historical replay exists; review discovery/production gates."
    if status == "needs_full_challenger_backtest":
        return f"Only {experiment.get('status')} evidence exists; run full historical replay before promotion."
    if status == "missing_experiment":
        return "No mapped aggressive-lab experiment exists yet."
    return "Governance/infrastructure hypothesis; blocks promotion until replay coverage improves."


def write_counterfactual_csv(path: Path, results: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "hypothesis_id",
        "experiment_id",
        "status",
        "backtest_executed",
        "requires_full_challenger_backtest",
        "passed_discovery",
        "production_ready",
        "cagr_delta_pp",
        "maxdd_delta_pp",
        "sharpe_delta",
        "notes",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in results:
            writer.writerow({key: row.get(key) for key in fieldnames})


def render_counterfactual_report(results: list[dict[str, Any]]) -> str:
    lines = [
        "# AutoLearning v2 Counterfactual Report",
        "",
        "This report states whether each creative hypothesis has enough historical evidence to be trusted.",
        "",
        "| Hypothesis | Experiment | Status | Discovery | CAGR delta pp | MaxDD delta pp | Notes |",
        "| --- | --- | --- | ---: | ---: | ---: | --- |",
    ]
    for row in results:
        cagr = row.get("cagr_delta_pp")
        maxdd = row.get("maxdd_delta_pp")
        lines.append(
            "| {hypothesis} | {experiment} | `{status}` | {discovery} | {cagr} | {maxdd} | {notes} |".format(
                hypothesis=row.get("hypothesis_id"),
                experiment=row.get("experiment_id") or "",
                status=row.get("status"),
                discovery=str(row.get("passed_discovery")).lower(),
                cagr="" if cagr is None else f"{safe_float(cagr):.2f}",
                maxdd="" if maxdd is None else f"{safe_float(maxdd):.2f}",
                notes=row.get("notes"),
            )
        )
    lines.append("")
    return "\n".join(lines)
