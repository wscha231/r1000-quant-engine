#!/usr/bin/env python3
"""Create canonical U0-v3 evidence for research fitting only.

The acceptance envelope authorizes one preregistered historical research fit
to consume the conservative legacy-trial floor.  It does not authorize a
broker backtest, target/order/ledger mutation, legacy-result promotion,
automatic champion change, production, live trading, or a fullrun.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools import build_run287_u0_v3_recovery_census as V3


CONTRACT_SCHEMA = "run287-u0-v3-acceptance-contract-v1"
EVIDENCE_SCHEMA = "run287-u0-v3-accepted-evidence-v1"
WORKFLOW_IDENTITY = "run287-u0-v3-acceptance"
FULL_SHA_RE = re.compile(r"[0-9a-f]{40}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")


def validate_contract(contract: Any) -> dict[str, Any]:
    if not isinstance(contract, dict):
        raise ValueError("U0-v3 acceptance contract must be an object")
    V3.require_exact_keys(
        contract,
        {
            "schema_version",
            "repository",
            "default_branch",
            "source_census_schema_version",
            "recovery_census_schema_version",
            "accepted_evidence_schema_version",
            "workflow_identity",
            "required_recovery_migration_blockers",
            "minimum_conservative_historical_trial_count_lower_bound",
            "authorization_scope",
        },
        "U0-v3 acceptance contract",
    )
    if contract.get("schema_version") != CONTRACT_SCHEMA:
        raise ValueError("U0-v3 acceptance contract schema mismatch")
    if contract.get("repository") != V3.REPOSITORY:
        raise ValueError("U0-v3 acceptance repository mismatch")
    if contract.get("default_branch") != "master":
        raise ValueError("U0-v3 acceptance default branch mismatch")
    if contract.get("source_census_schema_version") != V3.SOURCE_SCHEMA:
        raise ValueError("U0-v3 acceptance source schema mismatch")
    if contract.get("recovery_census_schema_version") != V3.OUTPUT_SCHEMA:
        raise ValueError("U0-v3 acceptance recovery schema mismatch")
    if contract.get("accepted_evidence_schema_version") != EVIDENCE_SCHEMA:
        raise ValueError("U0-v3 accepted evidence schema mismatch")
    if contract.get("workflow_identity") != WORKFLOW_IDENTITY:
        raise ValueError("U0-v3 acceptance workflow identity mismatch")
    required_migration = sorted(
        [
            "expected_return_runner_not_yet_bound_to_u0_v3_multiplicity",
            "u0_v3_not_yet_bound_to_canonical_acceptance_workflow",
        ]
    )
    if sorted(contract.get("required_recovery_migration_blockers") or []) != (
        required_migration
    ):
        raise ValueError("U0-v3 recovery migration blocker contract changed")
    minimum = contract.get(
        "minimum_conservative_historical_trial_count_lower_bound"
    )
    if type(minimum) is not int or minimum != 1:
        raise ValueError("U0-v3 minimum conservative trial floor changed")
    scope = contract.get("authorization_scope")
    required_scope = {
        "historical_challenger_research_fit_allowed": True,
        "historical_broker_backtest_allowed": False,
        "legacy_result_promotion_allowed": False,
        "target_order_ledger_mutation_allowed": False,
        "production_or_live_trading_allowed": False,
        "automatic_promotion_allowed": False,
        "fullrun_allowed": False,
    }
    if scope != required_scope:
        raise ValueError("U0-v3 acceptance authorization scope changed")
    return contract


def validate_recovered_rows(recovery: dict[str, Any]) -> list[str]:
    rows = recovery.get("recovered_candidates")
    if not isinstance(rows, list):
        return ["recovered_candidates_missing"]
    blockers: list[str] = []
    record_ids: set[str] = set()
    primary_trials: set[str] = set()
    weight_sum = 0
    for row in rows:
        if not isinstance(row, dict):
            blockers.append("recovered_candidate_malformed")
            continue
        record_id = str(row.get("record_id") or "")
        trial_id = str(row.get("canonical_trial_id") or "")
        weight = row.get("multiplicity_weight")
        if not record_id or record_id in record_ids:
            blockers.append("recovered_candidate_identity_invalid")
        record_ids.add(record_id)
        if not trial_id.startswith("legacy-code-head:") or FULL_SHA_RE.fullmatch(
            trial_id.removeprefix("legacy-code-head:")
        ) is None:
            blockers.append("canonical_trial_identity_invalid")
        if weight not in {0, 1} or isinstance(weight, bool):
            blockers.append("multiplicity_weight_invalid")
            continue
        weight_sum += weight
        if weight == 1:
            if trial_id in primary_trials:
                blockers.append("duplicate_canonical_trial_primary")
            primary_trials.add(trial_id)
        if row.get("promotion_use_allowed") is not False:
            blockers.append("legacy_promotion_use_enabled")
        if row.get("performance_claim_allowed") is not False:
            blockers.append("legacy_performance_claim_enabled")
        if row.get("performance_evaluated") is not False:
            blockers.append("legacy_performance_evaluated")
        if row.get("performance_metrics") is not None:
            blockers.append("legacy_performance_metrics_present")
        if row.get("exact_head_reuse_blocked") is not True:
            blockers.append("legacy_exact_head_reuse_not_blocked")
        if SHA256_RE.fullmatch(str(row.get("do_not_repeat_key") or "")) is None:
            blockers.append("legacy_do_not_repeat_key_invalid")
        row_blockers = row.get("legacy_result_promotion_blockers")
        if not isinstance(row_blockers, list) or not {
            "legacy_result_not_eligible_for_promotion",
            "synchronized_daily_after_cost_return_series_missing",
        }.issubset(set(row_blockers)):
            blockers.append("legacy_result_blockers_incomplete")
    summary = recovery.get("summary") or {}
    if weight_sum != summary.get("canonical_code_trial_count"):
        blockers.append("canonical_trial_weight_sum_mismatch")
    if len(primary_trials) != summary.get("canonical_code_trial_count"):
        blockers.append("canonical_trial_primary_count_mismatch")
    if len(rows) != summary.get("classified_candidate_count"):
        blockers.append("classified_candidate_count_mismatch")
    return sorted(set(blockers))


def build_acceptance(
    source: dict[str, Any],
    recovery: dict[str, Any],
    inventory: dict[str, Any],
    recovery_contract: dict[str, Any],
    acceptance_contract: dict[str, Any],
    expected_audit_sha: str,
) -> dict[str, Any]:
    acceptance_contract = validate_contract(acceptance_contract)
    expected_audit_sha = expected_audit_sha.lower()
    if FULL_SHA_RE.fullmatch(expected_audit_sha) is None:
        raise ValueError("expected U0-v3 audit SHA is invalid")
    rebuilt = V3.build_recovery_census(
        source, inventory, V3.validate_contract(recovery_contract)
    )
    if V3.canonical_sha256(rebuilt) != V3.canonical_sha256(recovery):
        raise ValueError("U0-v3 recovery census does not match recomputation")
    if recovery.get("schema_version") != V3.OUTPUT_SCHEMA:
        raise ValueError("U0-v3 recovery census schema mismatch")
    if recovery.get("repository") != acceptance_contract["repository"]:
        raise ValueError("U0-v3 recovery repository mismatch")
    if recovery.get("audit_default_branch") != acceptance_contract["default_branch"]:
        raise ValueError("U0-v3 recovery default branch mismatch")
    if str(recovery.get("audit_default_branch_sha") or "").lower() != (
        expected_audit_sha
    ):
        raise ValueError("U0-v3 recovery audit SHA mismatch")
    summary = recovery.get("summary")
    if not isinstance(summary, dict):
        raise ValueError("U0-v3 recovery summary missing")
    failures = validate_recovered_rows(recovery)
    if summary.get("historical_experiment_census_complete") is not True:
        failures.append("historical_experiment_census_incomplete")
    if summary.get("historical_challenger_preregistration_ready") is not True:
        failures.append("historical_challenger_preregistration_not_ready")
    if summary.get("historical_challenger_allowed") is not False:
        failures.append("recovery_census_prematurely_authorized_challenger")
    if recovery.get("census_completion_blockers") != []:
        failures.append("recovery_census_completion_blockers")
    if sorted(recovery.get("acceptance_migration_blockers") or []) != sorted(
        acceptance_contract["required_recovery_migration_blockers"]
    ):
        failures.append("recovery_acceptance_migration_blockers_mismatch")
    count = summary.get("conservative_historical_trial_count_lower_bound")
    canonical_count = summary.get("canonical_code_trial_count")
    registry_count = summary.get(
        "canonical_registry_published_attempt_lower_bound"
    )
    if (
        type(count) is not int
        or type(canonical_count) is not int
        or type(registry_count) is not int
        or count < acceptance_contract[
            "minimum_conservative_historical_trial_count_lower_bound"
        ]
        or count != canonical_count + registry_count
    ):
        failures.append("conservative_historical_trial_floor_invalid")
    safety = recovery.get("safety") or {}
    if safety != recovery_contract.get("safety"):
        failures.append("recovery_safety_contract_mismatch")
    if failures:
        raise ValueError("U0-v3 acceptance blocked:" + ",".join(sorted(set(failures))))
    return {
        "schema_version": EVIDENCE_SCHEMA,
        "repository": acceptance_contract["repository"],
        "workflow_identity": acceptance_contract["workflow_identity"],
        "audit_default_branch": acceptance_contract["default_branch"],
        "audit_default_branch_sha": expected_audit_sha,
        "source_census_sha256": V3.canonical_sha256(source),
        "recovery_census_sha256": V3.canonical_sha256(recovery),
        "source_inventory_sha256": V3.canonical_sha256(inventory),
        "recovery_contract_sha256": V3.canonical_sha256(recovery_contract),
        "acceptance_contract_sha256": V3.canonical_sha256(acceptance_contract),
        "conservative_historical_trial_count_lower_bound": count,
        "historical_experiment_census_complete": True,
        "historical_challenger_preregistration_ready": True,
        "historical_challenger_research_fit_allowed": True,
        "historical_broker_backtest_allowed": False,
        "legacy_result_promotion_allowed": False,
        "promotion_blockers": [],
        "target_order_ledger_mutation_allowed": False,
        "production_or_live_trading_allowed": False,
        "automatic_promotion_allowed": False,
        "fullrun_allowed": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-census", type=Path, required=True)
    parser.add_argument("--recovery-census", type=Path, required=True)
    parser.add_argument(
        "--inventory",
        type=Path,
        default=Path("docs/run287_u0_experiment_inventory.json"),
    )
    parser.add_argument(
        "--recovery-contract",
        type=Path,
        default=Path("docs/run287_u0_v3_recovery_contract.json"),
    )
    parser.add_argument(
        "--acceptance-contract",
        type=Path,
        default=Path("docs/run287_u0_v3_acceptance_contract.json"),
    )
    parser.add_argument("--expected-audit-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    evidence = build_acceptance(
        V3.read_json(args.source_census),
        V3.read_json(args.recovery_census),
        V3.read_json(args.inventory),
        V3.read_json(args.recovery_contract),
        V3.read_json(args.acceptance_contract),
        args.expected_audit_sha,
    )
    V3.write_json(args.output, evidence)
    print(json.dumps(evidence, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
