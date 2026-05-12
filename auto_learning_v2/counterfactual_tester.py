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

# Risk-adjusted promotion guards. A candidate that boosts CAGR while
# silently tanking risk-adjusted return (Sharpe) or drawdown must not be
# treated as a "good" counterfactual. These thresholds are deliberately
# narrow: tiny Sharpe noise is allowed, but meaningful risk regression
# blocks both discovery (weekly leader counterfactual) and production
# readiness (generic counterfactual path).
MAX_SHARPE_REGRESSION = 0.10
MAX_MAXDD_REGRESSION_PP = -5.0


def _experiment_rows(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(row.get("experiment_id")): row for row in summary.get("ranked") or []}


def build_counterfactual_results(hypotheses: list[dict[str, Any]], root: str | Path) -> list[dict[str, Any]]:
    root_path = Path(root)
    summary = read_json(root_path / "outputs" / "experiments" / "experiment_matrix_summary.json")
    experiments = _experiment_rows(summary)
    results: list[dict[str, Any]] = []
    for hypothesis in hypotheses:
        hid = str(hypothesis.get("id"))
        weekly_bridge = _weekly_leader_counterfactual(root_path, hid)
        if weekly_bridge:
            results.append(weekly_bridge)
            continue
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
        production_ready = (
            status == "counterfactual_available"
            and passed_discovery
            and cagr_delta is not None
            and cagr_delta >= 3.0
            and (sharpe_delta is None or sharpe_delta >= -MAX_SHARPE_REGRESSION)
        )
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


def _weekly_leader_counterfactual(root: Path, hypothesis_id: str) -> dict[str, Any] | None:
    if hypothesis_id != "alpha_sprint_breakout_fallback_v1":
        return None
    candidate = read_json(root / "outputs" / "weekly_leader_broker_replay" / "concentrated" / "metrics.json")
    baseline = read_json(root / "outputs" / "broker_replay" / "concentrated" / "metrics.json")
    if not candidate or candidate.get("status") != "completed":
        return None
    cand_cagr = safe_float(candidate.get("cagr"), 0.0)
    base_cagr = safe_float(baseline.get("cagr"), 0.0) if baseline else 0.0
    cand_dd = safe_float(candidate.get("max_dd"), 0.0)
    base_dd = safe_float(baseline.get("max_dd"), 0.0) if baseline else 0.0
    cand_sharpe = safe_float(candidate.get("sharpe"), 0.0)
    base_sharpe = safe_float(baseline.get("sharpe"), 0.0) if baseline else 0.0
    cagr_delta = (cand_cagr - base_cagr) * 100.0
    maxdd_delta = (cand_dd - base_dd) * 100.0
    sharpe_delta = (cand_sharpe - base_sharpe) if baseline else 0.0
    passed = bool(
        cagr_delta > 0
        and maxdd_delta >= MAX_MAXDD_REGRESSION_PP
        and sharpe_delta >= -MAX_SHARPE_REGRESSION
    )
    return {
        "hypothesis_id": hypothesis_id,
        "experiment_id": "weekly_leader_entry_broker_replay",
        "status": "counterfactual_available",
        "backtest_executed": True,
        "requires_full_challenger_backtest": False,
        "passed_discovery": passed,
        "production_ready": False,
        "cagr_delta_pp": cagr_delta,
        "maxdd_delta_pp": maxdd_delta,
        "sharpe_delta": sharpe_delta,
        "discovery_gate": {
            "cagr_delta_pp_gt": 0.0,
            "maxdd_delta_pp_min": MAX_MAXDD_REGRESSION_PP,
            "sharpe_delta_min": -MAX_SHARPE_REGRESSION,
        },
        "notes": "Weekly leader-entry broker replay is available as account-like counterfactual evidence; keep proposal-only until stress/cost gates pass.",
    }


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
