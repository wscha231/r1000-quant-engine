#!/usr/bin/env python3
"""Evaluate the single Run287 promotion/rollback gate without auto-promotion."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from run287_promotion_gate import (
    CANONICAL_STATES,
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
    repository_root = Path(__file__).resolve().parents[1]
    canonical_pointer_path = (
        repository_root
        / "data_static"
        / "run287_multiple_testing_approved_pointer.json"
    ).resolve()
    approved_bundle_root = (
        repository_root
        / "data_static"
        / "run287_multiple_testing_approved"
    ).resolve()
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
    parser.add_argument(
        "--multiple-testing-contract",
        default="docs/run287_multiple_testing_gate_contract.json",
    )
    parser.add_argument(
        "--multiple-testing-experiment-ledger",
        default="",
    )
    parser.add_argument(
        "--multiple-testing-return-matrix",
        default="",
    )
    parser.add_argument(
        "--multiple-testing-promotion-state-snapshot",
        default="",
    )
    parser.add_argument(
        "--multiple-testing-repository-root",
        default=str(Path(__file__).resolve().parents[1]),
    )
    parser.add_argument(
        "--multiple-testing-approved-pointer",
        default=(
            "data_static/"
            "run287_multiple_testing_approved_pointer.json"
        ),
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
    approved_pointer_path = Path(
        args.multiple_testing_approved_pointer
    ).resolve()
    if (
        not approved_pointer_path.is_file()
        or approved_pointer_path.is_symlink()
    ):
        raise ValueError("multiple_testing_approved_pointer_invalid")
    approved_pointer = read_json(approved_pointer_path)
    if (
        approved_pointer.get("schema_version")
        != "run287-approved-multiple-testing-pointer-v1"
    ):
        raise ValueError("multiple_testing_approved_pointer_schema_invalid")
    promotion_state = str(state.get("promotion_state") or "")
    advanced_state = promotion_state != "RESEARCH_ONLY"
    required_states = approved_pointer.get(
        "required_for_promotion_states"
    )
    if (
        not isinstance(required_states, list)
        or set(required_states) != set(CANONICAL_STATES) - {"RESEARCH_ONLY"}
    ):
        raise ValueError(
            "multiple_testing_approved_pointer_state_policy_invalid"
        )
    if (
        not advanced_state
        and approved_pointer.get("status")
        != "UNAVAILABLE_RESEARCH_ONLY"
        and not args.multiple_testing_gate
    ):
        raise ValueError(
            "research_only_multiple_testing_pointer_status_invalid"
        )
    if advanced_state and not args.multiple_testing_gate:
        raise ValueError(
            "advanced_state_multiple_testing_bundle_required"
        )
    if (
        advanced_state
        and approved_pointer_path != canonical_pointer_path
    ):
        raise ValueError(
            "advanced_state_canonical_multiple_testing_pointer_required"
        )
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
        if not args.multiple_testing_experiment_ledger:
            raise ValueError("multiple_testing_experiment_ledger_required")
        if not args.multiple_testing_return_matrix:
            raise ValueError("multiple_testing_return_matrix_required")
        multiple_testing_gate_path = Path(
            args.multiple_testing_gate
        ).resolve()
        multiple_testing_promotion_state_snapshot = Path(
            args.multiple_testing_promotion_state_snapshot
            or paths["state"]
        ).resolve()
        multiple_testing_repository_root = Path(
            args.multiple_testing_repository_root
        ).resolve()
        if advanced_state:
            pointer_fields = {
                "gate_path": str(multiple_testing_gate_path),
                "expected_gate_sha256": str(
                    args.expected_multiple_testing_gate_sha256
                ).lower(),
                "contract_path": str(
                    Path(args.multiple_testing_contract).resolve()
                ),
                "experiment_ledger_path": str(
                    Path(
                        args.multiple_testing_experiment_ledger
                    ).resolve()
                ),
                "return_matrix_path": str(
                    Path(args.multiple_testing_return_matrix).resolve()
                ),
                "promotion_state_snapshot_path": str(
                    multiple_testing_promotion_state_snapshot
                ),
            }
            resolved_pointer_fields = {
                field: (
                    str(
                        (
                            Path(__file__).resolve().parents[1]
                            / str(approved_pointer.get(field) or "")
                        ).resolve()
                    )
                    if field != "expected_gate_sha256"
                    else str(approved_pointer.get(field) or "").lower()
                )
                for field in pointer_fields
            }
            approved_paths = {
                field: Path(value).resolve()
                for field, value in resolved_pointer_fields.items()
                if field != "expected_gate_sha256"
            }
            if (
                approved_pointer.get("status")
                != "READY_REVIEWED_IMMUTABLE_BUNDLE"
                or pointer_fields != resolved_pointer_fields
                or multiple_testing_repository_root != repository_root
                or promotion_state not in required_states
                or any(
                    not path.is_relative_to(approved_bundle_root)
                    or not path.is_file()
                    or path.is_symlink()
                    for path in approved_paths.values()
                )
                or approved_pointer.get("automatic_promotion_allowed")
                is not False
                or approved_pointer.get("production_activation_allowed")
                is not False
                or approved_pointer.get("live_trading_enabled") is not False
            ):
                raise ValueError(
                    "advanced_state_multiple_testing_pointer_mismatch"
                )
        evidence = overlay_multiple_testing_evidence(
            evidence,
            multiple_testing_gate_path,
            expected_gate_sha256=(
                args.expected_multiple_testing_gate_sha256
            ),
            contract_path=Path(
                args.multiple_testing_contract
            ).resolve(),
            experiment_ledger_path=Path(
                args.multiple_testing_experiment_ledger
            ).resolve(),
            return_matrix_path=Path(
                args.multiple_testing_return_matrix
            ).resolve(),
            promotion_state_snapshot_path=(
                multiple_testing_promotion_state_snapshot
            ),
            repository_root=Path(
                multiple_testing_repository_root
            ),
            current_promotion_state=state,
        )
        observation = evidence.get("multiple_testing_gate_observation") or {}
        if (
            advanced_state
            and (
                approved_pointer.get("applicable_candidate_id")
                != observation.get("candidate_id")
                or approved_pointer.get("applicable_causal_family_id")
                != observation.get("causal_family_id")
                or approved_pointer.get("applicable_selected_trial_id")
                != observation.get("selected_trial_id")
                or (
                    state.get("official_challenger") or {}
                ).get("candidate_id")
                != approved_pointer.get("applicable_candidate_id")
            )
        ):
            raise ValueError(
                "advanced_state_multiple_testing_candidate_mismatch"
            )
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
    elif (
        args.expected_multiple_testing_gate_sha256
        or args.multiple_testing_experiment_ledger
        or args.multiple_testing_return_matrix
        or args.multiple_testing_promotion_state_snapshot
    ):
        raise ValueError("multiple_testing_gate_path_required")
    authorization = read_json(Path(args.transition_authorization).resolve()) if args.transition_authorization else None
    hashes = {f"{key}_sha256": sha256_file(path) for key, path in paths.items()}
    hashes["base_evidence_sha256"] = hashes["evidence_sha256"]
    hashes["evidence_sha256"] = canonical_sha256(evidence)
    hashes.update(runtime_anchor_hashes)
    hashes.update(multiple_testing_hashes)
    hashes["approved_multiple_testing_pointer_sha256"] = sha256_file(
        approved_pointer_path
    )
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
