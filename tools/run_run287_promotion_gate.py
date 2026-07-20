#!/usr/bin/env python3
"""Evaluate the single Run287 promotion/rollback gate without auto-promotion."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from run287_promotion_gate import (
    DEFAULT_CONTRACT,
    DEFAULT_EVIDENCE,
    DEFAULT_STATE,
    evaluate_gate,
    canonical_sha256,
    overlay_latest_run_evidence,
    read_json,
    sha256_file,
)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def render_report(gate: dict[str, Any]) -> str:
    actuals = gate["forward_paper_gate"]["actuals"]
    return "\n".join(
        [
            "# Run287 single promotion and rollback gate",
            "",
            f"- Canonical state: `{gate['canonical_promotion_state']}`",
            f"- Effective state: `{gate['effective_promotion_state']}`",
            f"- Maximum evidence-supported state: `{gate['maximum_evidence_supported_state']}`",
            f"- Historical gate: `{gate['historical_gate']['status']}`",
            f"- Forward gate: `{gate['forward_paper_gate']['status']}`",
            f"- 63-session evidence: `{gate['forward_paper_gate']['resolved_63d_status']}`",
            f"- Completed sessions / decision weeks: `{actuals['completed_market_sessions']} / {actuals['distinct_decision_weeks']}`",
            f"- Resolved 21/63/126D: `{actuals['resolved_21d_outcomes']} / {actuals['resolved_63d_outcomes']} / {actuals['resolved_126d_outcomes']}`",
            f"- Rollback triggered: `{str(gate['rollback']['triggered']).lower()}`",
            "- Automatic forward transition: `false`",
            "- Production activation allowed: `false`",
            "- Live trading enabled: `false`",
            "",
            "A successful workflow or dashboard build cannot advance this state. A reviewed",
            "canonical state-pointer change is required for every forward transition.",
            "",
        ]
    )


def build_approval_packet(gate: dict[str, Any], state: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    review_ready = gate["effective_promotion_state"] == "FORWARD_PAPER_REVIEW_READY"
    historical = evidence.get("historical") or {}
    return {
        "schema_version": "run287-user-approval-packet-v1",
        "status": "READY_FOR_USER_REVIEW" if review_ready else "NOT_ELIGIBLE",
        "requested_approval_scope": "production_candidate_review_only_no_live_activation",
        "exact_source_hashes": gate["source_hashes"],
        "canonical_champion": state.get("canonical_champion"),
        "official_challenger": state.get("official_challenger"),
        "champion_vs_challenger_historical_metrics": historical.get("metrics") or {},
        "forward_paper_metrics_and_observation_count": evidence.get("forward_paper") or {},
        "stress_cost_concentration_integrity": {
            "historical_checks": gate["historical_gate"]["checks"],
            "forward_zero_integrity_checks": gate["forward_paper_gate"]["zero_integrity_checks"],
            "rollback_triggers": gate["rollback"]["triggers"],
        },
        "current_target_reserve_changes": evidence.get("current_target_reserve_changes") or {},
        "worst_case_failure_modes": evidence.get("worst_case_failure_modes") or [],
        "rollback_plan": gate["rollback"],
        "unresolved_data_limitations": gate["unresolved_data_limitations"],
        "user_approval_granted": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--state", default=str(DEFAULT_STATE))
    parser.add_argument("--evidence", default=str(DEFAULT_EVIDENCE))
    parser.add_argument("--output-dir", default="outputs/run287_promotion_gate")
    parser.add_argument("--latest-run", default="")
    parser.add_argument("--request-state")
    parser.add_argument("--transition-authorization")
    args = parser.parse_args()

    paths = {key: Path(value).resolve() for key, value in {
        "contract": args.contract, "state": args.state, "evidence": args.evidence
    }.items()}
    contract = read_json(paths["contract"])
    state = read_json(paths["state"])
    evidence = read_json(paths["evidence"])
    if args.latest_run:
        evidence = overlay_latest_run_evidence(evidence, Path(args.latest_run).resolve())
    authorization = read_json(Path(args.transition_authorization).resolve()) if args.transition_authorization else None
    hashes = {f"{key}_sha256": sha256_file(path) for key, path in paths.items()}
    hashes["base_evidence_sha256"] = hashes["evidence_sha256"]
    hashes["evidence_sha256"] = canonical_sha256(evidence)
    gate = evaluate_gate(
        contract,
        state,
        evidence,
        source_hashes=hashes,
        requested_state=args.request_state,
        transition_authorization=authorization,
    )
    gate["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    output = Path(args.output_dir)
    write_json(output / "promotion_gate.json", gate)
    write_json(output / "champion_challenger_comparison.json", gate["champion_challenger"])
    write_json(output / "rollback_plan.json", gate["rollback"])
    write_json(output / "user_approval_packet.json", build_approval_packet(gate, state, evidence))
    (output / "promotion_gate.md").write_text(render_report(gate), encoding="utf-8")
    print(json.dumps({
        "status": "COMPLETED_GOVERNANCE_ONLY",
        "promotion_state": gate["effective_promotion_state"],
        "maximum_evidence_supported_state": gate["maximum_evidence_supported_state"],
        "forward_status": gate["forward_paper_gate"]["status"],
        "rollback_triggered": gate["rollback"]["triggered"],
        "output_dir": str(output),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
