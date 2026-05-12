#!/usr/bin/env python3
"""Evaluate an AutoLearning policy candidate against champion gates.

This runner is deliberately conservative. It does not mutate production config
and it does not pretend a full 83-month policy backtest has happened when only
snapshot/proxy artifacts are available. Missing historical evidence blocks the
relevant gate and is written explicitly into the decision artifact.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from r1000_auto_learning_evidence import read_json, safe_float  # noqa: E402
from r1000_auto_learning_policy import load_policy, validate_policy  # noqa: E402


DEFAULT_POLICY = "research/auto_learning_policy_candidate.yaml"
DEFAULT_LATEST_RUN = "cloud_results/full_rebuild/latest_global_alpha_universe"
DEFAULT_OUT_DIR = "outputs/auto_learning/challenger"
DEFAULT_E1_METRICS = "outputs/experiments/E1_auto_feature_gates_on/metrics.json"
DEFAULT_E5_METRICS = "outputs/experiments/E5_orchestrator_balanced/metrics.json"
DEFAULT_WEEKLY_LEADER_MAIN_METRICS = "outputs/weekly_leader_broker_replay/main/metrics.json"
DEFAULT_WEEKLY_LEADER_CONCENTRATED_METRICS = "outputs/weekly_leader_broker_replay/concentrated/metrics.json"


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_csv_rows(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def metric(metrics: dict[str, Any], *names: str, default: float = 0.0) -> float:
    for name in names:
        if name in metrics:
            return safe_float(metrics.get(name), default)
    return default


def load_baseline(latest_run: Path) -> dict[str, Any]:
    main = read_json(latest_run / "backtest_metrics.json")
    conc = read_json(latest_run / "concentrated_backtest_metrics.json")
    return {
        "main": {
            "cagr": metric(main, "cagr", "strategy_cagr"),
            "sharpe": metric(main, "sharpe"),
            "max_dd": metric(main, "max_dd"),
            "avg_turnover_monthly": metric(main, "avg_turnover_monthly"),
            "avg_stock_names": metric(main, "avg_stock_names"),
            "avg_cash_weight": metric(main, "avg_cash_weight"),
            "months": int(metric(main, "months")),
        },
        "concentrated": {
            "cagr": metric(conc, "strategy_cagr", "cagr"),
            "sharpe": metric(conc, "sharpe"),
            "max_dd": metric(conc, "max_dd"),
            "selected_names": int(metric(conc, "selected_names")),
        },
    }


def gate_row(
    gate: str,
    check: str,
    passed: bool,
    severity: str,
    observed: Any = "",
    threshold: Any = "",
    reason: str = "",
    evidence: str = "",
) -> dict[str, Any]:
    return {
        "gate": gate,
        "check": check,
        "passed": bool(passed),
        "severity": severity,
        "observed": observed,
        "threshold": threshold,
        "reason": reason,
        "evidence": evidence,
    }


def candidate_thresholds(policy: dict[str, Any]) -> dict[str, Any]:
    gates = policy.get("promotion_gates") or {}
    return {
        "main": gates.get("main_gate") or {},
        "concentrated": gates.get("concentrated_gate") or {},
        "orchestrator": gates.get("orchestrator_gate") or {},
        "stress": gates.get("stress_gate") or {},
        "cost_sensitivity_bps": gates.get("cost_sensitivity_bps") or [],
        "stability": gates.get("stability_gate") or {},
    }


def evaluate_challenger(
    policy: dict[str, Any],
    baseline: dict[str, Any],
    e1_metrics: dict[str, Any],
    e5_metrics: dict[str, Any],
    main_v2_audit: dict[str, Any],
    concentrated_policy: dict[str, Any],
    alpha_sprint_metrics: dict[str, Any],
    weekly_leader_main_metrics: dict[str, Any],
    weekly_leader_concentrated_metrics: dict[str, Any],
) -> dict[str, Any]:
    validation = validate_policy(policy)
    thresholds = candidate_thresholds(policy)
    rows: list[dict[str, Any]] = []

    rows.append(gate_row(
        "schema",
        "policy_valid",
        validation.get("valid") is True,
        "hard",
        observed=validation.get("issues"),
        threshold="valid proposal-only schema",
        reason="Policy must be proposal-only and keep production activation disabled.",
    ))
    rows.append(gate_row(
        "schema",
        "production_activation_disabled",
        (policy.get("guardrails") or {}).get("production_activation_allowed") is False,
        "hard",
        observed=(policy.get("guardrails") or {}).get("production_activation_allowed"),
        threshold=False,
        reason="AutoLearning policy cannot directly change production.",
    ))
    rows.append(gate_row(
        "schema",
        "human_approval_required",
        (policy.get("guardrails") or {}).get("requires_human_approval") is True,
        "hard",
        observed=(policy.get("guardrails") or {}).get("requires_human_approval"),
        threshold=True,
        reason="Capital allocation and execution policies require human approval.",
    ))

    main_base = baseline.get("main") or {}
    main_gate = thresholds["main"]
    e1_backtested = bool(e1_metrics.get("backtest_executed"))
    e1_candidate = e1_metrics.get("candidate_dry_run_metrics") or {}
    cand_main_cagr = metric(e1_candidate, "main_cagr", default=metric(e1_metrics, "cagr"))
    cand_main_sharpe = metric(e1_candidate, "main_sharpe", default=metric(e1_metrics, "sharpe"))
    cand_main_dd = metric(e1_candidate, "main_max_dd", default=metric(e1_metrics, "max_dd"))
    base_cagr = safe_float(main_base.get("cagr"))
    base_sharpe = safe_float(main_base.get("sharpe"))
    base_dd = safe_float(main_base.get("max_dd"))
    max_cagr_reg = safe_float(main_gate.get("max_cagr_regression_pp"), 1.0) / 100.0
    max_sharpe_reg = safe_float(main_gate.get("max_sharpe_regression"), 0.08)
    max_dd_worse = safe_float(main_gate.get("max_dd_worsening_pp"), 1.0) / 100.0
    rows.append(gate_row(
        "main",
        "feature_gate_candidate_backtest_executed",
        e1_backtested,
        "hard",
        observed=e1_metrics.get("status"),
        threshold="full candidate rebuild/backtest",
        reason="Feature-gate candidate currently has dry-run/proxy metrics only.",
        evidence=DEFAULT_E1_METRICS,
    ))
    rows.append(gate_row(
        "main",
        "main_cagr_floor",
        cand_main_cagr >= base_cagr - max_cagr_reg,
        "hard",
        observed=cand_main_cagr,
        threshold=base_cagr - max_cagr_reg,
        reason="Candidate main CAGR must not regress beyond the policy gate.",
        evidence=DEFAULT_E1_METRICS,
    ))
    rows.append(gate_row(
        "main",
        "main_sharpe_floor",
        cand_main_sharpe >= base_sharpe - max_sharpe_reg,
        "hard",
        observed=cand_main_sharpe,
        threshold=base_sharpe - max_sharpe_reg,
        reason="Candidate main Sharpe must not regress beyond the policy gate.",
        evidence=DEFAULT_E1_METRICS,
    ))
    rows.append(gate_row(
        "main",
        "main_max_dd_floor",
        cand_main_dd >= base_dd - max_dd_worse,
        "hard",
        observed=cand_main_dd,
        threshold=base_dd - max_dd_worse,
        reason="Candidate main MaxDD must not worsen beyond the policy gate.",
        evidence=DEFAULT_E1_METRICS,
    ))
    rows.append(gate_row(
        "main_v2",
        "main_v2_historical_backtest_exists",
        False,
        "hard",
        observed="latest_snapshot_only",
        threshold="83-month main_v2 backtest",
        reason="Main v2 currently has latest shadow output, not historical performance.",
        evidence="outputs/main_v2/main_v2_audit_latest.json",
    ))
    rows.append(gate_row(
        "main_v2",
        "main_v2_cap_audit",
        safe_float(main_v2_audit.get("single_name_cap")) <= 0.15 and safe_float(main_v2_audit.get("n_positions")) > 0,
        "soft",
        observed={"positions": main_v2_audit.get("n_positions"), "cash": main_v2_audit.get("cash_target")},
        threshold="cap<=15%, positions>0",
        reason="Latest shadow construction is internally useful but not enough for promotion.",
        evidence="outputs/main_v2/main_v2_audit_latest.json",
    ))

    conc_base = baseline.get("concentrated") or {}
    conc_gate = thresholds["concentrated"]
    cap_violations = concentrated_policy.get("cap_violations") or []
    rows.append(gate_row(
        "concentrated",
        "concentrated_cagr_floor",
        safe_float(conc_base.get("cagr")) >= safe_float(conc_gate.get("min_cagr"), 0.30),
        "hard",
        observed=conc_base.get("cagr"),
        threshold=conc_gate.get("min_cagr", 0.30),
        reason="Standalone concentrated historical CAGR must clear the policy floor.",
        evidence="cloud_results/full_rebuild/latest_global_alpha_universe/concentrated_backtest_metrics.json",
    ))
    rows.append(gate_row(
        "concentrated",
        "concentrated_max_dd_floor",
        safe_float(conc_base.get("max_dd")) >= safe_float(conc_gate.get("max_dd_floor"), -0.25),
        "hard",
        observed=conc_base.get("max_dd"),
        threshold=conc_gate.get("max_dd_floor", -0.25),
        reason="Standalone concentrated MaxDD must clear the policy floor.",
        evidence="cloud_results/full_rebuild/latest_global_alpha_universe/concentrated_backtest_metrics.json",
    ))
    rows.append(gate_row(
        "concentrated",
        "single_name_and_sector_cap_audit",
        len(cap_violations) <= int(conc_gate.get("single_name_cap_violations_allowed", 0)),
        "hard",
        observed=len(cap_violations),
        threshold=conc_gate.get("single_name_cap_violations_allowed", 0),
        reason="Latest concentrated policy audit found cap violations that must be resolved before more capital.",
        evidence="outputs/concentrated_policy/policy_audit_latest.json",
    ))

    orch_gate = thresholds["orchestrator"]
    e5_backtested = bool(e5_metrics.get("backtest_executed"))
    rows.append(gate_row(
        "orchestrator",
        "orchestrator_historical_backtest_exists",
        e5_backtested,
        "hard",
        observed=e5_metrics.get("status"),
        threshold="83-month orchestrator backtest",
        reason="Orchestrator balanced currently reports latest snapshot only.",
        evidence=DEFAULT_E5_METRICS,
    ))
    rows.append(gate_row(
        "orchestrator",
        "snapshot_cash_floor",
        safe_float(e5_metrics.get("proposed_cash_target")) <= safe_float(orch_gate.get("max_avg_cash"), 0.25),
        "soft",
        observed=e5_metrics.get("proposed_cash_target"),
        threshold=orch_gate.get("max_avg_cash", 0.25),
        reason="Latest snapshot cash is within the proposed max average cash threshold, but historical cash drag is unknown.",
        evidence=DEFAULT_E5_METRICS,
    ))

    alpha_status = alpha_sprint_metrics.get("status")
    weekly_leader_available = bool(weekly_leader_main_metrics.get("status") == "completed" or weekly_leader_concentrated_metrics.get("status") == "completed")
    rows.append(gate_row(
        "alpha_sprint",
        "alpha_sprint_historical_backtest_exists",
        alpha_status not in {"not_backtested_missing_historical_scored_snapshot", None, ""} or weekly_leader_available,
        "hard",
        observed={"alpha_sprint_status": alpha_status, "weekly_leader_available": weekly_leader_available},
        threshold="weekly/historical alpha sprint or weekly leader-entry broker replay",
        reason="Alpha Sprint can remain candidate-only until bull/strong-bull historical tests exist; weekly leader entry broker replay can now serve as the first counterfactual bridge.",
        evidence=f"{DEFAULT_WEEKLY_LEADER_MAIN_METRICS},{DEFAULT_WEEKLY_LEADER_CONCENTRATED_METRICS}",
    ))
    rows.append(gate_row(
        "weekly_leader_entry",
        "weekly_leader_broker_replay_available",
        weekly_leader_available,
        "soft",
        observed={
            "main_status": weekly_leader_main_metrics.get("status"),
            "main_cagr": weekly_leader_main_metrics.get("cagr"),
            "concentrated_status": weekly_leader_concentrated_metrics.get("status"),
            "concentrated_cagr": weekly_leader_concentrated_metrics.get("cagr"),
        },
        threshold="completed account-like replay",
        reason="New-leader entry ideas should be judged by broker-ledger metrics, not latest snapshot recommendations.",
        evidence=f"{DEFAULT_WEEKLY_LEADER_MAIN_METRICS},{DEFAULT_WEEKLY_LEADER_CONCENTRATED_METRICS}",
    ))

    rows.append(gate_row(
        "stress",
        "stress_windows_backtested",
        False,
        "hard",
        observed="not_available",
        threshold="2020/2022/momentum/rate/vix stress windows",
        reason="Policy challenger needs monthly equity and allocation series before stress gates can pass.",
    ))
    rows.append(gate_row(
        "cost",
        "cost_sensitivity_backtested",
        False,
        "hard",
        observed="not_available",
        threshold=thresholds.get("cost_sensitivity_bps", [25, 50, 75]),
        reason="Cost sensitivity has not been run for the full candidate policy.",
    ))
    rows.append(gate_row(
        "stability",
        "rolling_3y_5y_backtested",
        False,
        "hard",
        observed="not_available",
        threshold="rolling 3y and 5y pass",
        reason="Rolling stability cannot pass until full challenger return series exists.",
    ))

    hard_rows = [row for row in rows if row["severity"] == "hard"]
    hard_failed = [row for row in hard_rows if not row["passed"]]
    soft_failed = [row for row in rows if row["severity"] == "soft" and not row["passed"]]
    approved = not hard_failed
    return {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mode": "challenger_gate_evaluation",
        "research_only": True,
        "production_activation_allowed": False,
        "policy_version": policy.get("policy_version"),
        "approved_for_promotion": approved,
        "status": "approved" if approved else "blocked",
        "hard_failures": hard_failed,
        "soft_failures": soft_failed,
        "gate_rows": rows,
        "baseline": baseline,
        "proxy_artifacts": {
            "feature_gate_metrics": DEFAULT_E1_METRICS,
            "orchestrator_metrics": DEFAULT_E5_METRICS,
            "main_v2_audit": "outputs/main_v2/main_v2_audit_latest.json",
            "concentrated_policy_audit": "outputs/concentrated_policy/policy_audit_latest.json",
            "alpha_sprint_metrics": "outputs/alpha_sprint/backtest_metrics.json",
            "weekly_leader_main_metrics": DEFAULT_WEEKLY_LEADER_MAIN_METRICS,
            "weekly_leader_concentrated_metrics": DEFAULT_WEEKLY_LEADER_CONCENTRATED_METRICS,
        },
        "next_required_backtests": [
            "main_v2_83_month_backtest",
            "orchestrator_83_month_backtest",
            "weekly_leader_entry_cost_and_stress_replay",
            "alpha_sprint_weekly_historical_backtest",
            "stress_window_equity_curve_test",
            "cost_sensitivity_25_50_75_bps",
            "rolling_3y_5y_stability",
        ],
    }


def render_report(decision: dict[str, Any]) -> str:
    rows = decision.get("gate_rows") or []
    failed = decision.get("hard_failures") or []
    lines = [
        "# AutoLearning Policy Challenger Report",
        "",
        "This report evaluates the candidate policy gates. It does not apply the policy to production.",
        "",
        f"- Policy version: `{decision.get('policy_version')}`",
        f"- Status: `{decision.get('status')}`",
        f"- Approved for promotion: `{decision.get('approved_for_promotion')}`",
        f"- Hard failures: {len(failed)}",
        "",
        "## Gate Matrix",
        "",
        "| Gate | Check | Severity | Passed | Observed | Threshold |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| {gate} | {check} | {severity} | {passed} | `{observed}` | `{threshold}` |".format(
                gate=row.get("gate"),
                check=row.get("check"),
                severity=row.get("severity"),
                passed=row.get("passed"),
                observed=row.get("observed"),
                threshold=row.get("threshold"),
            )
        )
    lines.extend(["", "## Blockers", ""])
    if not failed:
        lines.append("No hard blockers.")
    else:
        for row in failed:
            lines.append(f"- {row.get('gate')}/{row.get('check')}: {row.get('reason')}")
    lines.extend(["", "## Next Required Backtests", ""])
    for item in decision.get("next_required_backtests") or []:
        lines.append(f"- `{item}`")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", default=DEFAULT_POLICY)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--e1-metrics", default=DEFAULT_E1_METRICS)
    parser.add_argument("--e5-metrics", default=DEFAULT_E5_METRICS)
    parser.add_argument("--weekly-leader-main-metrics", default=DEFAULT_WEEKLY_LEADER_MAIN_METRICS)
    parser.add_argument("--weekly-leader-concentrated-metrics", default=DEFAULT_WEEKLY_LEADER_CONCENTRATED_METRICS)
    args = parser.parse_args()

    policy = load_policy(repo_path(args.policy))
    baseline = load_baseline(repo_path(args.latest_run))
    decision = evaluate_challenger(
        policy=policy,
        baseline=baseline,
        e1_metrics=read_json(repo_path(args.e1_metrics)),
        e5_metrics=read_json(repo_path(args.e5_metrics)),
        main_v2_audit=read_json(repo_path("outputs/main_v2/main_v2_audit_latest.json")),
        concentrated_policy=read_json(repo_path("outputs/concentrated_policy/policy_audit_latest.json")),
        alpha_sprint_metrics=read_json(repo_path("outputs/alpha_sprint/backtest_metrics.json")),
        weekly_leader_main_metrics=read_json(repo_path(args.weekly_leader_main_metrics)),
        weekly_leader_concentrated_metrics=read_json(repo_path(args.weekly_leader_concentrated_metrics)),
    )

    out_dir = repo_path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "challenger_decision.json", decision)
    write_csv_rows(
        out_dir / "challenger_gate_matrix.csv",
        decision.get("gate_rows") or [],
        ["gate", "check", "passed", "severity", "observed", "threshold", "reason", "evidence"],
    )
    (out_dir / "challenger_report.md").write_text(render_report(decision), encoding="utf-8")
    print(f"[auto-policy-challenger] status={decision['status']} hard_failures={len(decision['hard_failures'])}")
    print(f"[auto-policy-challenger] wrote {out_dir / 'challenger_decision.json'}")
    return 0 if decision["approved_for_promotion"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
