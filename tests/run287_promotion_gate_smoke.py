#!/usr/bin/env python3
"""P9 single promotion/rollback gate regression tests."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from run287_promotion_gate import (  # noqa: E402
    DEFAULT_CONTRACT,
    DEFAULT_EVIDENCE,
    DEFAULT_STATE,
    evaluate_gate,
    gate_for_consumer,
    overlay_latest_run_evidence,
    read_json,
)


def _inputs() -> tuple[dict, dict, dict]:
    return read_json(DEFAULT_CONTRACT), read_json(DEFAULT_STATE), read_json(DEFAULT_EVIDENCE)


def _passing_evidence(contract: dict, evidence: dict) -> dict:
    payload = copy.deepcopy(evidence)
    payload["candidate_id"] = "single-shadow-challenger"
    for field in contract["required_historical_checks"]:
        payload["historical"][field] = True
    thresholds = contract["forward_thresholds"]
    forward = payload["forward_paper"]
    forward.update(
        {
            "completed_market_sessions": thresholds["minimum_completed_market_sessions"],
            "distinct_decision_weeks": thresholds["minimum_distinct_decision_weeks"],
            "resolved_21d_outcomes": thresholds["minimum_resolved_21d_outcomes"],
            "resolved_63d_outcomes": thresholds["minimum_resolved_63d_outcomes"],
            "resolved_126d_outcomes": thresholds["minimum_resolved_126d_outcomes"],
            "selection_evaluable": True,
            "exit_evaluable": True,
            "defense_evaluable": True,
            "reentry_evaluable": True,
        }
    )
    champion = payload["accounts"]["champion"]
    challenger = copy.deepcopy(champion)
    challenger["account_id"] = "run287-challenger-paper"
    challenger["ledger_root"] = "paper_archive/challenger/single-shadow-challenger"
    payload["accounts"]["challenger"] = challenger
    payload["accounts"]["paired_decision_date_count"] = 60
    return payload


def test_current_packet_remains_research_only_and_underpowered() -> None:
    contract, state, evidence = _inputs()
    gate = evaluate_gate(contract, state, evidence, source_hashes={"evidence_sha256": "current"})
    assert gate["canonical_promotion_state"] == "RESEARCH_ONLY"
    assert gate["effective_promotion_state"] == "RESEARCH_ONLY"
    assert gate["maximum_evidence_supported_state"] == "RESEARCH_ONLY"
    assert gate["forward_paper_gate"]["resolved_63d_status"] == "UNDERPOWERED"
    assert gate["automatic_forward_transition_performed"] is False
    assert gate["production_activation_allowed"] is False
    assert gate["live_trading_enabled"] is False


def test_all_evidence_only_sets_maximum_and_never_auto_advances() -> None:
    contract, state, evidence = _inputs()
    gate = evaluate_gate(contract, state, _passing_evidence(contract, evidence))
    assert gate["maximum_evidence_supported_state"] == "FORWARD_PAPER_REVIEW_READY"
    assert gate["forward_paper_gate"]["status"] == "REVIEW_READY"
    assert gate["effective_promotion_state"] == "RESEARCH_ONLY"
    assert gate["canonical_state_unchanged"] is True


def test_manual_transition_is_candidate_only_and_requires_exact_authorization() -> None:
    contract, state, evidence = _inputs()
    passing = _passing_evidence(contract, evidence)
    approval = {
        "approved": True,
        "approved_by": "user",
        "approved_at_utc": "2026-07-20T00:00:00Z",
        "approved_scope": "shadow-state-pointer-review",
        "requested_state": "SHADOW_OPERATION_READY",
        "evidence_sha256": "evidence-hash",
    }
    gate = evaluate_gate(
        contract,
        state,
        passing,
        source_hashes={"evidence_sha256": "evidence-hash"},
        requested_state="SHADOW_OPERATION_READY",
        transition_authorization=approval,
    )
    transition = gate["transition_request"]
    assert transition["status"] == "REVIEWED_STATE_CHANGE_PR_REQUIRED", transition
    assert transition["canonical_state_changed"] is False
    assert gate["effective_promotion_state"] == "RESEARCH_ONLY"
    bad = copy.deepcopy(approval)
    bad["evidence_sha256"] = "wrong"
    blocked = evaluate_gate(
        contract,
        state,
        passing,
        source_hashes={"evidence_sha256": "evidence-hash"},
        requested_state="SHADOW_OPERATION_READY",
        transition_authorization=bad,
    )
    assert blocked["transition_request"]["status"] == "TRANSITION_REQUEST_BLOCKED"


def test_champion_and_challenger_cannot_share_ledger_or_contract() -> None:
    contract, state, evidence = _inputs()
    passing = _passing_evidence(contract, evidence)
    passing["accounts"]["challenger"]["ledger_root"] = passing["accounts"]["champion"]["ledger_root"]
    passing["accounts"]["challenger"]["cost_contract_sha256"] = "different-cost"
    gate = evaluate_gate(contract, state, passing)
    assert gate["effective_promotion_state"] == "BLOCKED_OR_ROLLED_BACK"
    assert gate["rollback"]["triggered"] is True
    assert gate["rollback"]["canonical_champion_preserved"] is True
    assert gate["rollback"]["paper_history_preserved"] is True


def test_rollback_trigger_deescalates_but_preserves_forward_history() -> None:
    contract, state, evidence = _inputs()
    state = copy.deepcopy(state)
    state["promotion_state"] = "FORWARD_PAPER_VALIDATING"
    passing = _passing_evidence(contract, evidence)
    passing["rollback"]["stress_mdd_degradation"] = True
    gate = evaluate_gate(contract, state, passing)
    assert gate["effective_promotion_state"] == "BLOCKED_OR_ROLLED_BACK"
    assert "stress_mdd_degradation" in gate["rollback"]["triggers"]
    assert gate["rollback"]["policy_pointer_action"] == "RESTORE_CANONICAL_CHAMPION"
    assert gate["rollback"]["paper_history_preserved"] is True


def test_runner_emits_one_consistent_state_and_noneligible_approval_packet() -> None:
    with TemporaryDirectory() as tmp:
        out = Path(tmp) / "gate"
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "run_run287_promotion_gate.py"),
                "--output-dir",
                str(out),
            ],
            cwd=ROOT,
            check=True,
        )
        gate = json.loads((out / "promotion_gate.json").read_text(encoding="utf-8"))
        packet = json.loads((out / "user_approval_packet.json").read_text(encoding="utf-8"))
        assert gate["effective_promotion_state"] == "RESEARCH_ONLY"
        assert packet["status"] == "NOT_ELIGIBLE"
        assert packet["production_activation_allowed"] is False
        consumer = gate_for_consumer(out.parent, explicit=out / "promotion_gate.json")
        assert consumer["promotion_state"] == "RESEARCH_ONLY"
        assert consumer["source_path"].endswith("promotion_gate.json")


def test_lower_signal_frequency_never_changes_fixed_thresholds() -> None:
    contract, state, evidence = _inputs()
    passing = _passing_evidence(contract, evidence)
    passing["forward_paper"]["resolved_63d_outcomes"] = contract["forward_thresholds"]["minimum_resolved_63d_outcomes"] - 1
    gate = evaluate_gate(contract, state, passing)
    assert gate["forward_paper_gate"]["status"] == "UNDERPOWERED"
    assert gate["forward_paper_gate"]["resolved_63d_status"] == "UNDERPOWERED"
    assert gate["forward_paper_gate"]["thresholds"] == contract["forward_thresholds"]


def test_canonical_consumers_and_workflows_use_the_single_gate() -> None:
    for rel in (
        "tools/build_run287_operating_scorecard.py",
        "tools/build_public_portfolio_dashboard.py",
        "tools/run_user_current_report.py",
    ):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "gate_for_consumer" in text, rel
    daily = (ROOT / ".github/workflows/daily_operating_selection_refresh.yml").read_text(encoding="utf-8")
    for token in (
        "python tools/run_run287_promotion_gate.py",
        "--state data_static/run287_promotion_state.json",
        "outputs/run287_promotion_gate/",
        "daily_run287_promotion_gate.log",
    ):
        assert token in daily, token
    pages = (ROOT / ".github/workflows/pages_deploy.yml").read_text(encoding="utf-8")
    assert "tools/run287_promotion_gate.py" in pages
    assert "data_static/run287_promotion_state.json" in pages
    public = json.loads((ROOT / "docs/public/data/dashboard.json").read_text(encoding="utf-8"))
    assert public["status"]["promotion_state"] == "RESEARCH_ONLY"
    assert public["status"]["rollback_triggered"] is False
    app = (ROOT / "docs/public/app.js").read_text(encoding="utf-8")
    assert "data.status?.promotion_state || data.status?.decision" in app


def test_runtime_overlay_counts_sessions_and_negative_cash_fails_closed() -> None:
    contract, state, evidence = _inputs()
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        paper = root / "daily_simulated_fill_ledger"
        for portfolio in ("main", "concentrated"):
            directory = paper / portfolio
            directory.mkdir(parents=True)
            directory.joinpath("equity_curve.csv").write_text(
                "date,cash_usd\n2026-07-13,100\n2026-07-14,-1\n2026-07-15,100\n",
                encoding="utf-8",
            )
            directory.joinpath("fills.csv").write_text(
                "date,signal_date,client_order_id\n2026-07-14,2026-07-14,dup\n2026-07-15,2026-07-14,dup\n",
                encoding="utf-8",
            )
            directory.joinpath("manifest.json").write_text(
                json.dumps({"result_status": "RESTORED_CONTINUATION"}), encoding="utf-8"
            )
        overlaid = overlay_latest_run_evidence(evidence, root)
        assert overlaid["forward_paper"]["completed_market_sessions"] == 3
        assert overlaid["forward_paper"]["negative_cash_count"] == 2
        assert overlaid["forward_paper"]["duplicate_client_order_id_count"] == 2
        assert overlaid["forward_paper"]["duplicate_fill_count"] == 0
        assert overlaid["historical"] == evidence["historical"]
        gate = evaluate_gate(contract, state, overlaid)
        assert gate["effective_promotion_state"] == "BLOCKED_OR_ROLLED_BACK"
        assert "forward_integrity:negative_cash_count" in gate["rollback"]["triggers"]


if __name__ == "__main__":
    tests = [value for key, value in sorted(globals().items()) if key.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"run287_promotion_gate_smoke: {len(tests)} passed")
