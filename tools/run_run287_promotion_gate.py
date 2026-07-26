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
    overlay_multiple_testing_evidence,
    read_json,
    sha256_file,
)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def verify_runtime_anchor(path: Path, expected_sha256: str, label: str) -> str:
    expected = str(expected_sha256 or "").strip().lower()
    if len(expected) != 64 or any(
        character not in "0123456789abcdef" for character in expected
    ):
        raise ValueError(f"runtime_step_anchor_invalid:{label}")
    if not path.is_file():
        raise ValueError(f"runtime_step_anchor_missing:{label}")
    actual = sha256_file(path)
    if actual != expected:
        raise ValueError(f"runtime_step_anchor_mismatch:{label}")
    return actual


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
    parser.add_argument("--expected-paper-integrity-sha256", default="")
    parser.add_argument(
        "--expected-risk-outcome-parent-anchor-sha256",
        default="",
    )
    parser.add_argument("--expected-risk-outcome-summary-sha256", default="")
    parser.add_argument("--expected-risk-price-cache-manifest-sha256", default="")
    parser.add_argument("--expected-scorecard-sha256", default="")
    parser.add_argument("--multiple-testing-gate", default="")
    parser.add_argument(
        "--expected-multiple-testing-gate-sha256",
        default="",
    )
    parser.add_argument("--request-state")
    parser.add_argument("--transition-authorization")
    args = parser.parse_args()

    paths = {key: Path(value).resolve() for key, value in {
        "contract": args.contract, "state": args.state, "evidence": args.evidence
    }.items()}
    contract = read_json(paths["contract"])
    state = read_json(paths["state"])
    evidence = read_json(paths["evidence"])
    # This check is runtime-owned.  A tracked or caller-supplied boolean is
    # never sufficient without an exact hash-pinned gate bundle.
    historical = evidence.setdefault("historical", {})
    historical["multiple_testing_pass"] = False
    multiple_testing_limitation = (
        "No runtime-verified multiple-testing gate evidence is available."
    )
    limitations = historical.setdefault("limitations", [])
    if multiple_testing_limitation not in limitations:
        limitations.append(multiple_testing_limitation)
    runtime_anchor_specs: dict[str, tuple[str, str]] = {
        "paper_integrity": (
            "daily_simulated_fill_ledger/snapshot_integrity.json",
            args.expected_paper_integrity_sha256,
        ),
        "risk_outcome_parent_anchor": (
            "run287_risk_outcome_parent_anchor/anchor.json",
            args.expected_risk_outcome_parent_anchor_sha256,
        ),
        "risk_outcome_summary": (
            "run287_risk_outcome_archive/summary.json",
            args.expected_risk_outcome_summary_sha256,
        ),
        "risk_price_cache_manifest": (
            "run287_risk_outcome_price_cache/replay_price_cache_manifest.json",
            args.expected_risk_price_cache_manifest_sha256,
        ),
        "scorecard": (
            "run287_operating_scorecard/operating_scorecard.json",
            args.expected_scorecard_sha256,
        ),
    }
    runtime_anchor_hashes: dict[str, str] = {}
    if args.latest_run:
        latest_run = Path(args.latest_run).resolve()
        for label, (relative, expected) in runtime_anchor_specs.items():
            if expected:
                runtime_anchor_hashes[
                    f"runtime_{label}_sha256"
                ] = verify_runtime_anchor(
                    latest_run / relative,
                    expected,
                    label,
                )
        evidence = overlay_latest_run_evidence(
            evidence,
            latest_run,
            expected_risk_outcome_parent_anchor_sha256=(
                args.expected_risk_outcome_parent_anchor_sha256
            ),
        )
        for label, (relative, expected) in runtime_anchor_specs.items():
            if expected:
                verify_runtime_anchor(latest_run / relative, expected, label)
    multiple_testing_hashes: dict[str, str] = {}
    if args.multiple_testing_gate:
        if not args.expected_multiple_testing_gate_sha256:
            raise ValueError("multiple_testing_gate_expected_sha256_required")
        multiple_testing_gate_path = Path(
            args.multiple_testing_gate
        ).resolve()
        evidence = overlay_multiple_testing_evidence(
            evidence,
            multiple_testing_gate_path,
            expected_gate_sha256=(
                args.expected_multiple_testing_gate_sha256
            ),
        )
        observation = evidence.get("multiple_testing_gate_observation") or {}
        multiple_testing_hashes[
            "runtime_multiple_testing_gate_sha256"
        ] = str(observation.get("gate_sha256") or "")
        for name, digest in (
            observation.get("artifact_hashes") or {}
        ).items():
            key = (
                "runtime_multiple_testing_"
                + str(name).replace(".", "_")
                + "_sha256"
            )
            multiple_testing_hashes[key] = str(digest)
            verify_runtime_anchor(
                multiple_testing_gate_path.parent / str(name),
                str(digest),
                f"multiple_testing_{str(name).replace('.', '_')}",
            )
        verify_runtime_anchor(
            multiple_testing_gate_path,
            args.expected_multiple_testing_gate_sha256,
            "multiple_testing_gate",
        )
    elif args.expected_multiple_testing_gate_sha256:
        raise ValueError("multiple_testing_gate_path_required")
    authorization = read_json(Path(args.transition_authorization).resolve()) if args.transition_authorization else None
    hashes = {f"{key}_sha256": sha256_file(path) for key, path in paths.items()}
    hashes["base_evidence_sha256"] = hashes["evidence_sha256"]
    hashes["evidence_sha256"] = canonical_sha256(evidence)
    hashes.update(runtime_anchor_hashes)
    hashes.update(multiple_testing_hashes)
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
