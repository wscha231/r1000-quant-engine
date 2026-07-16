#!/usr/bin/env python3
"""Aggregate frozen Run287 diagnostics into a no-tuning bottleneck decision."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = "docs/run287_performance_bottleneck_contract_v1.json"
DEFAULT_REGISTRY = "docs/run287_do_not_repeat_registry.json"
DEFAULT_OUTPUT = "outputs/run287_performance_bottleneck_decision"
HORIZONS = (21, 63, 126)


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected object: {path}")
    return payload


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def required_columns(frame: pd.DataFrame, columns: set[str], label: str) -> None:
    missing = sorted(columns - set(frame.columns))
    if missing:
        raise ValueError(f"{label} missing columns: {missing}")


def selection_stats(frame: pd.DataFrame) -> pd.DataFrame:
    required_columns(
        frame,
        {"portfolio", "was_selected", "was_missed_leader", "rejection_reason", *[f"forward_{h}d_excess" for h in HORIZONS]},
        "selection",
    )
    rows: list[dict[str, Any]] = []
    for portfolio, group in frame.groupby("portfolio", sort=True):
        for horizon in HORIZONS:
            column = f"forward_{horizon}d_excess"
            selected = pd.to_numeric(group.loc[group["was_selected"].eq(True), column], errors="coerce").dropna()
            missed = pd.to_numeric(group.loc[group["was_missed_leader"].eq(True), column], errors="coerce").dropna()
            rows.append(
                {
                    "portfolio": portfolio,
                    "horizon": horizon,
                    "selected_count": len(selected),
                    "missed_count": len(missed),
                    "selected_mean": selected.mean(),
                    "missed_mean": missed.mean(),
                    "mean_spread": selected.mean() - missed.mean(),
                    "selected_median": selected.median(),
                    "missed_median": missed.median(),
                    "median_spread": selected.median() - missed.median(),
                }
            )
    return pd.DataFrame(rows)


def cash_rejection_stats(frame: pd.DataFrame) -> pd.DataFrame:
    subset = frame[frame["was_missed_leader"].eq(True) & frame["rejection_reason"].eq("cash")]
    rows = []
    for portfolio, group in subset.groupby("portfolio", sort=True):
        values = pd.to_numeric(group["forward_63d_excess"], errors="coerce").dropna()
        rows.append(
            {
                "portfolio": portfolio,
                "count": len(values),
                "mean_63d_excess": values.mean(),
                "median_63d_excess": values.median(),
                "broad_redeploy_support": bool(len(values) and values.mean() > 0 and values.median() > 0),
            }
        )
    return pd.DataFrame(rows)


def exit_stats(frame: pd.DataFrame) -> pd.DataFrame:
    required_columns(frame, {"portfolio", "premature_sell_candidate", "premature_sell_excess_63d", "premature_sell_excess_126d"}, "exit")
    rows = []
    for portfolio, group in frame.groupby("portfolio", sort=True):
        for horizon in (63, 126):
            values = pd.to_numeric(group[f"premature_sell_excess_{horizon}d"], errors="coerce").dropna()
            rows.append(
                {
                    "portfolio": portfolio,
                    "horizon": horizon,
                    "resolved_count": len(values),
                    "mean_sold_minus_replacement": values.mean(),
                    "median_sold_minus_replacement": values.median(),
                    "positive_mean_and_median": bool(len(values) and values.mean() > 0 and values.median() > 0),
                    "premature_candidate_count": int(group["premature_sell_candidate"].eq(True).sum()),
                }
            )
    return pd.DataFrame(rows)


def operating_stats(payload: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for item in payload.get("portfolios", []):
        base_cagr = float(item.get("broker_ledger_cagr", 0.0))
        base_mdd = float(item.get("broker_ledger_max_dd", 0.0))
        for mechanism, prefix in [("execution_policy", "execution_policy"), ("position_risk", "position_risk")]:
            cagr = float(item.get(f"{prefix}_cagr", 0.0))
            mdd = float(item.get(f"{prefix}_max_dd", 0.0))
            rows.append(
                {
                    "portfolio": item.get("portfolio"),
                    "mechanism": mechanism,
                    "baseline_cagr": base_cagr,
                    "arm_cagr": cagr,
                    "delta_cagr": cagr - base_cagr,
                    "baseline_mdd": base_mdd,
                    "arm_mdd": mdd,
                    "delta_mdd": mdd - base_mdd,
                    "joint_improvement": bool(cagr >= base_cagr and mdd >= base_mdd),
                }
            )
    return pd.DataFrame(rows)


def baseline_gaps(contract: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for portfolio, values in contract["canonical_generated_baselines"].items():
        cagr = float(values["cagr"])
        mdd = float(values["max_dd"])
        cagr_target = float(values["cagr_target"])
        mdd_target = float(values["max_dd_target"])
        rows.append(
            {
                "portfolio": portfolio,
                "cagr": cagr,
                "cagr_target": cagr_target,
                "cagr_gap_pp": max(0.0, cagr_target - cagr) * 100.0,
                "max_dd": mdd,
                "max_dd_target": mdd_target,
                "mdd_gap_pp": max(0.0, mdd_target - mdd) * 100.0,
                "target_pass": bool(cagr >= cagr_target and mdd >= mdd_target),
            }
        )
    return pd.DataFrame(rows)


def audit(
    *,
    contract: dict[str, Any],
    registry: dict[str, Any],
    selection: pd.DataFrame,
    exit_counterfactual: pd.DataFrame,
    cash_attribution: pd.DataFrame,
    operating: dict[str, Any],
    trade_attribution: dict[str, Any],
    next_ab: dict[str, Any],
    risk_outcome: dict[str, Any],
    input_hashes: dict[str, str] | None = None,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    selection_table = selection_stats(selection)
    cash_rejections = cash_rejection_stats(selection)
    exits = exit_stats(exit_counterfactual)
    operating_table = operating_stats(operating)
    gaps = baseline_gaps(contract)

    selection_edge = bool(
        len(selection_table) == 6
        and selection_table["mean_spread"].gt(0).all()
        and selection_table["median_spread"].gt(0).all()
    )
    broad_cash = bool(len(cash_rejections) == 2 and cash_rejections["broad_redeploy_support"].all())
    generic_exit = bool(len(exits) == 4 and exits["positive_mean_and_median"].all())
    execution = operating_table[operating_table["mechanism"].eq("execution_policy")]
    position_risk = operating_table[operating_table["mechanism"].eq("position_risk")]
    execution_ready = bool(len(execution) == 2 and execution["joint_improvement"].all())
    position_risk_ready = bool(len(position_risk) == 2 and position_risk["joint_improvement"].all())
    next_ab_open = bool(next_ab.get("next_single_ab_gate_open", False) and next_ab.get("selected_arm"))
    risk_ready = bool(risk_outcome.get("mechanism_review_ready", False))
    failed_families = {str(row.get("id")) for row in registry.get("entries", []) if row.get("blocked_reuse") is True}
    concentration_findings = [
        row for row in trade_attribution.get("all_findings", [])
        if "mdd_ticker_loss_concentration" in str(row.get("finding_id", ""))
    ]

    decisions = pd.DataFrame(
        [
            {"component": "selection", "evidence_status": "EDGE_PRESENT" if selection_edge else "EDGE_NOT_PROVEN", "eligible_challenger": False, "decision": "PROTECT_CURRENT_SELECTION_EDGE" if selection_edge else "CLOSE_OR_REVIEW_DATA", "reason": "selected-versus-missed spread across 21/63/126D"},
            {"component": "broad_cash_redeployment", "evidence_status": "SUPPORTED" if broad_cash else "NOT_SUPPORTED", "eligible_challenger": False, "decision": "DO_NOT_OPEN", "reason": "cash-rejected missed leaders require positive mean and median 63D excess in both books"},
            {"component": "generic_exit_delay", "evidence_status": "SUPPORTED" if generic_exit else "NOT_SUPPORTED", "eligible_challenger": False, "decision": "DO_NOT_OPEN", "reason": "sold-minus-replacement direction is not jointly positive at 63/126D"},
            {"component": "execution_policy", "evidence_status": "JOINT_IMPROVEMENT" if execution_ready else "WORSE_OR_MIXED", "eligible_challenger": False, "decision": "DO_NOT_REPEAT", "reason": "execution overlay must improve CAGR and MDD in both books"},
            {"component": "position_risk_overlay", "evidence_status": "JOINT_IMPROVEMENT" if position_risk_ready else "WORSE_OR_MIXED", "eligible_challenger": False, "decision": "WAIT_FORWARD_RISK_GATE", "reason": "existing historical risk overlay does not jointly improve both metrics"},
            {"component": "single_name_mdd_concentration", "evidence_status": "HIGH_FINDING" if concentration_findings else "NO_HIGH_FINDING", "eligible_challenger": risk_ready, "decision": "FORWARD_REVIEW_ONLY" if not risk_ready else "PREREGISTER_ONE_MECHANISM", "reason": "cluster cap and stop families are blocked; individual-risk archive must mature"},
            {"component": "external_pit_revision", "evidence_status": "SOURCE_READY" if next_ab_open else "SOURCE_BLOCKED", "eligible_challenger": next_ab_open, "decision": "OPEN_ONE_FIXED_ARM" if next_ab_open else "WAIT_PIT_SOURCE_GATE", "reason": "only source-screened historical lane may open the next fixed-book A/B"},
        ]
    )
    eligible = decisions[decisions["eligible_challenger"].eq(True)]
    status = "READY_ONE_ELIGIBLE_CHALLENGER" if len(eligible) == 1 else "BLOCKED_NO_ELIGIBLE_HISTORICAL_CHALLENGER"
    summary = {
        "schema_version": "run287-performance-bottleneck-audit-v1",
        "generated_at_utc": now_utc(),
        "status": status,
        "eligible_challenger_count": int(len(eligible)),
        "eligible_challengers": eligible["component"].tolist(),
        "selection_edge_present": selection_edge,
        "broad_cash_redeployment_supported": broad_cash,
        "generic_exit_delay_supported": generic_exit,
        "execution_policy_joint_improvement": execution_ready,
        "position_risk_joint_improvement": position_risk_ready,
        "single_name_mdd_high_finding_count": len(concentration_findings),
        "next_single_ab_gate_open": next_ab_open,
        "next_ab_blockers": next_ab.get("historical_lane", {}).get("blockers", []),
        "risk_forward_review_ready": risk_ready,
        "risk_distinct_decision_weeks": int(risk_outcome.get("distinct_decision_week_count", 0)),
        "risk_forward_outcome_event_count": int(risk_outcome.get("forward_outcome_event_count", 0)),
        "blocked_reuse_families_present": sorted(failed_families & {"monthly_dd_vix_floor", "broad_gross_floor", "stop_or_exit_delay", "rank_rs_revenue_replacement", "aggregate_cluster_cap", "composite_account_aware_execution"}),
        "diagnostic_broker_metrics_are_not_canonical_generated_baselines": True,
        "input_hashes": input_hashes or {},
        "research_only": True,
        "historical_backtest_dispatched": False,
        "threshold_tuning_allowed": False,
        "score_rank_selector_changed": False,
        "target_books_mutated": False,
        "cash_policy_changed": False,
        "orders_generated": False,
        "fullrun_dispatched": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
    }
    return summary, gaps, selection_table, cash_rejections, exits, pd.concat([decisions, operating_table.assign(component=operating_table["mechanism"], evidence_status="DIAGNOSTIC", eligible_challenger=False, decision="METRIC_DETAIL", reason="broker-ledger diagnostic")], ignore_index=True, sort=False)


def write_outputs(output: Path, result: tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]) -> None:
    summary, gaps, selection, cash, exits, decisions = result
    output.mkdir(parents=True, exist_ok=True)
    tables = {
        "canonical_gap.csv": gaps,
        "selection_spread.csv": selection,
        "cash_rejection_evidence.csv": cash,
        "exit_counterfactual.csv": exits,
        "component_decision.csv": decisions,
    }
    hashes = {}
    for name, frame in tables.items():
        path = output / name
        frame.to_csv(path, index=False)
        hashes[name] = sha256_file(path)
    report = [
        "# Run287 performance bottleneck audit",
        "",
        f"- status: `{summary['status']}`",
        f"- selection edge present: `{summary['selection_edge_present']}`",
        f"- eligible challenger count: `{summary['eligible_challenger_count']}`",
        f"- next historical A/B gate open: `{summary['next_single_ab_gate_open']}`",
        f"- risk forward review ready: `{summary['risk_forward_review_ready']}`",
        "- diagnostic broker metrics do not replace the canonical generated-book baseline.",
        "- no threshold tuning, A/B, target/cash/order mutation, fullrun, production, or live action.",
    ]
    (output / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    hashes["report.md"] = sha256_file(output / "report.md")
    summary["output_hashes"] = hashes
    (output / "manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-output-root", required=True)
    parser.add_argument("--trade-attribution-summary", required=True)
    parser.add_argument("--operating-event-summary", required=True)
    parser.add_argument("--next-ab-summary", required=True)
    parser.add_argument("--risk-outcome-summary", required=True)
    parser.add_argument("--contract", default=DEFAULT_CONTRACT)
    parser.add_argument("--registry", default=DEFAULT_REGISTRY)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = repo_path(args.artifact_output_root)
    paths = {
        "contract": repo_path(args.contract),
        "registry": repo_path(args.registry),
        "selection": root / "stock_selection_quality" / "selected_vs_available_leaders.csv",
        "exit": root / "entry_exit_timing_audit" / "premature_sell_counterfactual.csv",
        "cash": root / "cash_reentry_quality" / "cash_attribution_report.csv",
        "trade_attribution": repo_path(args.trade_attribution_summary),
        "operating": repo_path(args.operating_event_summary),
        "next_ab": repo_path(args.next_ab_summary),
        "risk_outcome": repo_path(args.risk_outcome_summary),
        "tool": Path(__file__).resolve(),
    }
    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        print(json.dumps({"status": "BLOCKED_MISSING_INPUT", "missing": missing}, indent=2))
        return 2
    result = audit(
        contract=read_json(paths["contract"]),
        registry=read_json(paths["registry"]),
        selection=pd.read_csv(paths["selection"], low_memory=False),
        exit_counterfactual=pd.read_csv(paths["exit"], low_memory=False),
        cash_attribution=pd.read_csv(paths["cash"], low_memory=False),
        operating=read_json(paths["operating"]),
        trade_attribution=read_json(paths["trade_attribution"]),
        next_ab=read_json(paths["next_ab"]),
        risk_outcome=read_json(paths["risk_outcome"]),
        input_hashes={name: sha256_file(path) for name, path in paths.items()},
    )
    write_outputs(repo_path(args.output_dir), result)
    print(json.dumps({"status": result[0]["status"], "output_dir": str(repo_path(args.output_dir))}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
