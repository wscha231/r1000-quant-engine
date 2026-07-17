#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.audit_run287_performance_bottlenecks import audit, write_outputs  # noqa: E402


def contract() -> dict[str, object]:
    return {
        "canonical_generated_baselines": {
            "main": {"cagr": 0.344032, "max_dd": -0.253619, "cagr_target": 0.35, "max_dd_target": -0.25},
            "concentrated": {"cagr": 0.490971, "max_dd": -0.229552, "cagr_target": 0.50, "max_dd_target": -0.25},
        }
    }


def selection() -> pd.DataFrame:
    rows = []
    for portfolio in ["main", "concentrated"]:
        rows.append({"portfolio": portfolio, "was_selected": True, "was_missed_leader": False, "rejection_reason": "", "forward_21d_excess": 0.03, "forward_63d_excess": 0.06, "forward_126d_excess": 0.12})
        rows.append({"portfolio": portfolio, "was_selected": False, "was_missed_leader": True, "rejection_reason": "cash", "forward_21d_excess": -0.01, "forward_63d_excess": -0.02, "forward_126d_excess": -0.03})
    return pd.DataFrame(rows)


def exits() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"portfolio": "main", "premature_sell_candidate": True, "premature_sell_excess_63d": 0.01, "premature_sell_excess_126d": -0.02},
            {"portfolio": "concentrated", "premature_sell_candidate": False, "premature_sell_excess_63d": -0.01, "premature_sell_excess_126d": -0.03},
        ]
    )


def operating() -> dict[str, object]:
    return {
        "portfolios": [
            {
                "portfolio": portfolio,
                "broker_ledger_cagr": 0.40,
                "broker_ledger_max_dd": -0.20,
                "execution_policy_cagr": 0.35,
                "execution_policy_max_dd": -0.25,
                "position_risk_cagr": 0.30,
                "position_risk_max_dd": -0.19,
            }
            for portfolio in ["main", "concentrated"]
        ]
    }


def test_blocked_but_actionable_diagnosis() -> None:
    result = audit(
        contract=contract(),
        registry={"entries": [{"id": "stop_or_exit_delay", "blocked_reuse": True}, {"id": "aggregate_cluster_cap", "blocked_reuse": True}]},
        selection=selection(),
        exit_counterfactual=exits(),
        cash_attribution=pd.DataFrame([{"portfolio": "main"}]),
        operating=operating(),
        trade_attribution={"all_findings": [{"finding_id": "F6_mdd_ticker_loss_concentration_concentrated"}]},
        next_ab={"next_single_ab_gate_open": False, "selected_arm": None, "historical_lane": {"blockers": ["source_not_ready"]}},
        risk_outcome={"mechanism_review_ready": False, "distinct_decision_week_count": 1, "forward_outcome_event_count": 0},
    )
    summary, gaps, selection_table, cash, exit_table, decisions = result
    assert summary["status"] == "BLOCKED_NO_ELIGIBLE_HISTORICAL_CHALLENGER"
    assert summary["selection_edge_present"] is True
    assert summary["broad_cash_redeployment_supported"] is False
    assert summary["generic_exit_delay_supported"] is False
    assert summary["execution_policy_joint_improvement"] is False
    assert summary["position_risk_joint_improvement"] is False
    assert summary["fullrun_dispatched"] is False
    assert abs(gaps.set_index("portfolio").loc["main", "cagr_gap_pp"] - 0.5968) < 1e-10
    assert len(selection_table) == 6
    assert not cash["broad_redeploy_support"].any()
    assert not exit_table["positive_mean_and_median"].all()
    assert decisions.loc[decisions["component"].eq("selection"), "decision"].iloc[0] == "PROTECT_CURRENT_SELECTION_EDGE"
    with tempfile.TemporaryDirectory() as tmp:
        write_outputs(Path(tmp), result)
        assert (Path(tmp) / "manifest.json").exists()
        assert (Path(tmp) / "component_decision.csv").exists()


def test_missing_selection_schema_fails() -> None:
    try:
        audit(
            contract=contract(),
            registry={"entries": []},
            selection=selection().drop(columns=["forward_63d_excess"]),
            exit_counterfactual=exits(),
            cash_attribution=pd.DataFrame(),
            operating=operating(),
            trade_attribution={"all_findings": []},
            next_ab={},
            risk_outcome={},
        )
    except ValueError as exc:
        assert "selection missing columns" in str(exc)
    else:
        raise AssertionError("missing selection column must fail")


def main() -> None:
    test_blocked_but_actionable_diagnosis()
    test_missing_selection_schema_fails()
    print("run287_performance_bottleneck_smoke: PASS")


if __name__ == "__main__":
    main()
