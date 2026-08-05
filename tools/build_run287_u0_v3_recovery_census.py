#!/usr/bin/env python3
"""Classify every U0-v2 candidate without inventing historical evidence.

The v2 exporter is an exact-head GitHub collector and intentionally leaves
every experiment-like record unmapped.  This recovery layer assigns stable
canonical identities by exact code head, deduplicates aliases, and counts all
unknown legacy candidates conservatively for future multiple-testing gates.
Missing parameters, PIT data, costs, target books, and daily return series stay
explicitly missing.  This tool never authorizes a backtest or promotion.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


SOURCE_SCHEMA = "run287-u0-v2-github-census-v1"
INVENTORY_SCHEMA = "run287-u0-experiment-inventory-v1"
CONTRACT_SCHEMA = "run287-u0-v3-recovery-contract-v1"
OUTPUT_SCHEMA = "run287-u0-v3-recovery-census-v1"
REPOSITORY = "wscha231/r1000-quant-engine"
SHA_RE = re.compile(r"[0-9a-f]{40}")


def reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, nested in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = nested
    return value


def read_json(path: Path) -> Any:
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicate_json_keys,
    )


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def require_exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(f"{label} keys mismatch: missing={missing}, extra={extra}")


def validate_contract(contract: Any) -> dict[str, Any]:
    if not isinstance(contract, dict):
        raise ValueError("recovery contract must be an object")
    require_exact_keys(
        contract,
        {
            "schema_version",
            "source_census_schema_version",
            "source_inventory_schema_version",
            "output_schema_version",
            "canonical_trial_identity",
            "unrecovered_candidate_policy",
            "multiplicity_policy",
            "safety",
        },
        "recovery contract",
    )
    if contract.get("schema_version") != CONTRACT_SCHEMA:
        raise ValueError("recovery contract schema mismatch")
    if contract.get("source_census_schema_version") != SOURCE_SCHEMA:
        raise ValueError("recovery source census schema mismatch")
    if contract.get("source_inventory_schema_version") != INVENTORY_SCHEMA:
        raise ValueError("recovery source inventory schema mismatch")
    if contract.get("output_schema_version") != OUTPUT_SCHEMA:
        raise ValueError("recovery output schema mismatch")

    identity = contract.get("canonical_trial_identity")
    if not isinstance(identity, dict):
        raise ValueError("canonical trial identity policy is missing")
    require_exact_keys(
        identity,
        {
            "key",
            "duplicate_policy",
            "alias_multiplicity_weight",
            "primary_multiplicity_weight",
        },
        "canonical_trial_identity",
    )
    if identity != {
        "key": "experiment_candidate_head_sha",
        "duplicate_policy": "ONE_TRIAL_PER_EXACT_CODE_HEAD",
        "alias_multiplicity_weight": 0,
        "primary_multiplicity_weight": 1,
    }:
        raise ValueError("canonical trial identity policy changed")

    unknown = contract.get("unrecovered_candidate_policy")
    if not isinstance(unknown, dict):
        raise ValueError("unrecovered candidate policy is missing")
    required_unknown = {
        "evidence_state": "UNVERIFIED_ASSERTION",
        "evaluation_class": "UNVERIFIED_LEGACY",
        "exact_trial_manifest_status": "MISSING",
        "after_cost_daily_return_series_status": "MISSING",
        "pit_status": "UNVERIFIED",
        "parameter_hash_status": "MISSING",
        "data_hash_status": "MISSING",
        "target_book_hash_status": "MISSING",
        "cash_cost_contract_status": "MISSING",
        "promotion_use_allowed": False,
        "performance_claim_allowed": False,
        "do_not_repeat_exact_head": True,
    }
    require_exact_keys(unknown, set(required_unknown), "unrecovered_candidate_policy")
    if unknown != required_unknown:
        raise ValueError("unrecovered candidate policy changed")

    multiplicity = contract.get("multiplicity_policy")
    if not isinstance(multiplicity, dict):
        raise ValueError("multiplicity policy is missing")
    required_multiplicity = {
        "count_each_distinct_candidate_code_head": True,
        "also_count_all_canonical_registry_published_attempt_lower_bounds": True,
        "overcount_when_overlap_is_unresolved": True,
        "zero_return_imputation_allowed": False,
        "summary_metric_to_daily_return_conversion_allowed": False,
    }
    require_exact_keys(multiplicity, set(required_multiplicity), "multiplicity_policy")
    if multiplicity != required_multiplicity:
        raise ValueError("multiplicity policy changed")

    safety = contract.get("safety")
    if not isinstance(safety, dict):
        raise ValueError("recovery safety policy is missing")
    required_safety = {
        "metadata_only": True,
        "fullrun_allowed": False,
        "target_order_ledger_mutation_allowed": False,
        "production_or_live_trading_allowed": False,
        "automatic_promotion_allowed": False,
        "acceptance_gate_migration_allowed_by_this_contract": False,
    }
    require_exact_keys(safety, set(required_safety), "safety")
    if safety != required_safety:
        raise ValueError("recovery safety policy changed")
    return contract


def validate_source_census(census: Any) -> dict[str, Any]:
    if not isinstance(census, dict):
        raise ValueError("source census must be an object")
    if census.get("schema_version") != SOURCE_SCHEMA:
        raise ValueError("source census schema mismatch")
    if census.get("repository") != REPOSITORY:
        raise ValueError("source census repository mismatch")
    audit_sha = str(census.get("audit_default_branch_sha") or "").lower()
    if SHA_RE.fullmatch(audit_sha) is None:
        raise ValueError("source census audit SHA is invalid")
    source_contract = census.get("source_contract")
    if not isinstance(source_contract, dict):
        raise ValueError("source census contract is missing")
    for field, expected in (
        ("metadata_only", True),
        ("fullrun_executed", False),
        ("production_or_live_mutated", False),
        ("champion_changed", False),
    ):
        if source_contract.get(field) is not expected:
            raise ValueError(f"unsafe source census contract: {field}")
    summary = census.get("summary")
    candidates = census.get("experiment_candidates")
    if not isinstance(summary, dict) or not isinstance(candidates, list):
        raise ValueError("source census summary or candidates are missing")
    blockers = census.get("promotion_blockers") or []
    if not isinstance(blockers, list) or any(
        not isinstance(item, str) or not item for item in blockers
    ):
        raise ValueError("source census blockers are malformed")
    if summary.get("experiment_candidate_count") != len(candidates):
        raise ValueError("source census candidate count mismatch")
    record_ids: list[str] = []
    for row in candidates:
        if not isinstance(row, dict):
            raise ValueError("source census candidate is malformed")
        record_id = str(row.get("record_id") or "")
        head_sha = str(row.get("head_sha") or "").lower()
        if not record_id or SHA_RE.fullmatch(head_sha) is None:
            raise ValueError("source census candidate identity is invalid")
        for field in (
            "matched_do_not_repeat_ids",
            "capability_family_candidates",
            "promotion_blockers",
        ):
            values = row.get(field) or []
            if not isinstance(values, list) or any(
                not isinstance(item, str) or not item
                for item in values
            ):
                raise ValueError(f"source census candidate {field} is invalid")
        record_ids.append(record_id)
    if len(record_ids) != len(set(record_ids)):
        raise ValueError("source census candidate record IDs are duplicated")
    return census


def validate_inventory(inventory: Any) -> tuple[dict[str, dict[str, Any]], int]:
    if not isinstance(inventory, dict) or inventory.get("schema_version") != INVENTORY_SCHEMA:
        raise ValueError("source inventory schema mismatch")
    entries = inventory.get("entries")
    if not isinstance(entries, list):
        raise ValueError("source inventory entries are missing")
    by_id: dict[str, dict[str, Any]] = {}
    attempt_lower_bound = 0
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("source inventory entry is malformed")
        entry_id = str(entry.get("registry_entry_id") or "")
        attempts = entry.get("published_attempt_count_lower_bound")
        if (
            not entry_id
            or entry_id in by_id
            or not isinstance(attempts, int)
            or isinstance(attempts, bool)
            or attempts < 0
        ):
            raise ValueError("source inventory entry identity or count is invalid")
        by_id[entry_id] = entry
        attempt_lower_bound += attempts
    declared = (inventory.get("summary") or {}).get("registry_entry_count")
    if declared != len(entries):
        raise ValueError("source inventory entry count mismatch")
    return by_id, attempt_lower_bound


def canonical_trial_id(head_sha: str) -> str:
    return f"legacy-code-head:{head_sha}"


def classification_for(
    row: dict[str, Any],
    *,
    primary_record_id: str,
    group_record_ids: list[str],
    group_registry_ids: list[str],
    group_capability_families: list[str],
    group_changed_paths_incomplete: bool,
    group_ancestry_unverified: bool,
    inventory_by_id: dict[str, dict[str, Any]],
    unknown_policy: dict[str, Any],
) -> dict[str, Any]:
    source_registry_ids = row.get("matched_do_not_repeat_ids") or []
    if not isinstance(source_registry_ids, list) or any(
        not isinstance(item, str) or item not in inventory_by_id
        for item in source_registry_ids
    ):
        raise ValueError("candidate registry linkage is invalid")
    matched = [inventory_by_id[item] for item in group_registry_ids]
    evidence_states = sorted({item["evidence_state"] for item in matched})
    evaluation_classes = sorted({item["evaluation_class"] for item in matched})
    manifest_states = sorted(
        {item["exact_trial_manifest_status"] for item in matched}
    )
    return_states = sorted(
        {item["after_cost_daily_return_series_status"] for item in matched}
    )
    is_primary = row["record_id"] == primary_record_id
    head_sha = str(row["head_sha"]).lower()
    blockers = [
        "legacy_result_not_eligible_for_promotion",
        "pit_contract_unverified",
        "exact_parameter_and_data_hash_missing",
        "target_book_cash_and_cost_contract_missing",
        "synchronized_daily_after_cost_return_series_missing",
    ]
    if group_changed_paths_incomplete:
        blockers.append("changed_paths_incomplete")
    if group_ancestry_unverified:
        blockers.append("git_ancestry_unverified")
    return {
        "record_id": row["record_id"],
        "record_type": row.get("record_type"),
        "number": row.get("number"),
        "name": row.get("name"),
        "title": row.get("title"),
        "state": row.get("state"),
        "url": row.get("url"),
        "head_sha": head_sha,
        "ancestry": row.get("ancestry"),
        "canonical_trial_id": canonical_trial_id(head_sha),
        "canonical_primary_record_id": primary_record_id,
        "canonical_group_record_ids": group_record_ids,
        "is_canonical_primary": is_primary,
        "multiplicity_weight": 1 if is_primary else 0,
        "capability_family_candidates": group_capability_families,
        "source_record_matched_do_not_repeat_ids": sorted(
            set(source_registry_ids)
        ),
        "matched_do_not_repeat_ids": group_registry_ids,
        "classification_source": (
            "CANONICAL_REGISTRY_LINK_PLUS_EXACT_HEAD"
            if matched
            else "CONSERVATIVE_UNVERIFIED_EXACT_HEAD"
        ),
        "evaluation_classes": evaluation_classes or [
            unknown_policy["evaluation_class"]
        ],
        "evidence_states": evidence_states or [unknown_policy["evidence_state"]],
        "exact_trial_manifest_states": manifest_states or [
            unknown_policy["exact_trial_manifest_status"]
        ],
        "after_cost_daily_return_series_states": return_states or [
            unknown_policy["after_cost_daily_return_series_status"]
        ],
        "pit_status": unknown_policy["pit_status"],
        "parameter_hash_status": unknown_policy["parameter_hash_status"],
        "data_hash_status": unknown_policy["data_hash_status"],
        "target_book_hash_status": unknown_policy["target_book_hash_status"],
        "cash_cost_contract_status": unknown_policy[
            "cash_cost_contract_status"
        ],
        "performance_evaluated": False,
        "performance_metrics": None,
        "promotion_use_allowed": False,
        "performance_claim_allowed": False,
        "exact_head_reuse_blocked": True,
        "do_not_repeat_key": canonical_sha256(
            {
                "canonical_trial_id": canonical_trial_id(head_sha),
                "capability_family_candidates": group_capability_families,
                "matched_do_not_repeat_ids": group_registry_ids,
            }
        ),
        "legacy_result_promotion_blockers": sorted(set(blockers)),
    }


def build_recovery_census(
    census: dict[str, Any],
    inventory: dict[str, Any],
    contract: dict[str, Any],
) -> dict[str, Any]:
    census = validate_source_census(census)
    contract = validate_contract(contract)
    inventory_by_id, registry_attempts = validate_inventory(inventory)
    candidates = census["experiment_candidates"]
    rows_by_head: dict[str, list[dict[str, Any]]] = {}
    for row in candidates:
        rows_by_head.setdefault(str(row["head_sha"]).lower(), []).append(row)

    recovered: list[dict[str, Any]] = []
    for head_sha, rows in sorted(rows_by_head.items()):
        record_ids = sorted(str(row["record_id"]) for row in rows)
        primary = record_ids[0]
        group_registry_ids = sorted(
            {
                registry_id
                for row in rows
                for registry_id in (row.get("matched_do_not_repeat_ids") or [])
            }
        )
        if any(item not in inventory_by_id for item in group_registry_ids):
            raise ValueError("candidate registry linkage is invalid")
        group_capability_families = sorted(
            {
                family
                for row in rows
                for family in (row.get("capability_family_candidates") or [])
            }
        )
        group_changed_paths_incomplete = any(
            row.get("record_type") == "BRANCH"
            or row.get("changed_paths_complete") is not True
            for row in rows
        )
        group_ancestry_unverified = any(
            row.get("ancestry") == "UNVERIFIED_BLOCKED" for row in rows
        )
        for row in sorted(rows, key=lambda item: str(item["record_id"])):
            recovered.append(
                classification_for(
                    row,
                    primary_record_id=primary,
                    group_record_ids=record_ids,
                    group_registry_ids=group_registry_ids,
                    group_capability_families=group_capability_families,
                    group_changed_paths_incomplete=group_changed_paths_incomplete,
                    group_ancestry_unverified=group_ancestry_unverified,
                    inventory_by_id=inventory_by_id,
                    unknown_policy=contract["unrecovered_candidate_policy"],
                )
            )

    trial_ids = {row["canonical_trial_id"] for row in recovered}
    primary_count = sum(int(row["multiplicity_weight"]) for row in recovered)
    if primary_count != len(trial_ids) or len(recovered) != len(candidates):
        raise ValueError("canonical trial deduplication invariant failed")
    classified_ids = {row["record_id"] for row in recovered}
    source_ids = {str(row["record_id"]) for row in candidates}
    completion_blockers: list[str] = []
    if classified_ids != source_ids:
        completion_blockers.append("candidate_mapping_incomplete")
    if any(row["performance_claim_allowed"] for row in recovered):
        completion_blockers.append("legacy_performance_claim_was_enabled")
    if any(row["promotion_use_allowed"] for row in recovered):
        completion_blockers.append("legacy_promotion_use_was_enabled")
    if any(row["multiplicity_weight"] not in {0, 1} for row in recovered):
        completion_blockers.append("invalid_multiplicity_weight")

    state_counts = Counter(
        state for row in recovered for state in row["evidence_states"]
    )
    family_counts = Counter(
        family
        for row in recovered
        if row["is_canonical_primary"]
        for family in row["capability_family_candidates"]
    )
    legacy_blocker_counts = Counter(
        blocker
        for row in recovered
        if row["is_canonical_primary"]
        for blocker in row["legacy_result_promotion_blockers"]
    )
    conservative_count = primary_count + registry_attempts
    return {
        "schema_version": OUTPUT_SCHEMA,
        "repository": census["repository"],
        "audit_default_branch_sha": census["audit_default_branch_sha"],
        "source_census_sha256": canonical_sha256(census),
        "source_inventory_sha256": canonical_sha256(inventory),
        "recovery_contract_sha256": canonical_sha256(contract),
        "source_schema_version": census["schema_version"],
        "source_census_blockers": sorted(
            set(census.get("promotion_blockers") or [])
        ),
        "safety": contract["safety"],
        "summary": {
            "source_experiment_candidate_count": len(candidates),
            "classified_candidate_count": len(recovered),
            "canonical_code_trial_count": primary_count,
            "duplicate_alias_count": len(recovered) - primary_count,
            "canonical_registry_entry_count": len(inventory_by_id),
            "canonical_registry_published_attempt_lower_bound": registry_attempts,
            "conservative_historical_trial_count_lower_bound": conservative_count,
            "evidence_state_counts": dict(sorted(state_counts.items())),
            "canonical_capability_family_counts": dict(sorted(family_counts.items())),
            "legacy_result_promotion_blocker_counts": dict(
                sorted(legacy_blocker_counts.items())
            ),
            "unverified_ancestry_canonical_trial_count": sum(
                row["is_canonical_primary"]
                and row["ancestry"] == "UNVERIFIED_BLOCKED"
                for row in recovered
            ),
            "unverified_assertion_candidate_count": sum(
                "UNVERIFIED_ASSERTION" in row["evidence_states"]
                for row in recovered
            ),
            "historical_experiment_census_complete": not completion_blockers,
            "historical_challenger_preregistration_ready": not completion_blockers,
            "historical_challenger_allowed": False,
        },
        "census_completion_blockers": completion_blockers,
        "acceptance_migration_blockers": [
            "u0_v3_not_yet_bound_to_canonical_acceptance_workflow",
            "expected_return_runner_not_yet_bound_to_u0_v3_multiplicity",
        ],
        "legacy_result_promotion_policy": {
            "all_recovered_legacy_rows_promotion_use_allowed": False,
            "all_recovered_legacy_rows_performance_claim_allowed": False,
            "missing_evidence_is_not_imputed": True,
            "summary_metrics_are_not_daily_returns": True,
        },
        "recovered_candidates": recovered,
    }


def write_candidate_csv(path: Path, payload: dict[str, Any]) -> None:
    fields = [
        "record_id",
        "record_type",
        "number",
        "name",
        "state",
        "head_sha",
        "canonical_trial_id",
        "canonical_primary_record_id",
        "is_canonical_primary",
        "multiplicity_weight",
        "classification_source",
        "capability_family_candidates",
        "source_record_matched_do_not_repeat_ids",
        "matched_do_not_repeat_ids",
        "evidence_states",
        "legacy_result_promotion_blockers",
        "url",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in payload["recovered_candidates"]:
            output = {field: row.get(field, "") for field in fields}
            for field in (
                "capability_family_candidates",
                "source_record_matched_do_not_repeat_ids",
                "matched_do_not_repeat_ids",
                "evidence_states",
                "legacy_result_promotion_blockers",
            ):
                output[field] = "|".join(output[field])
            writer.writerow(output)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-census", type=Path, required=True)
    parser.add_argument(
        "--inventory",
        type=Path,
        default=Path("docs/run287_u0_experiment_inventory.json"),
    )
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path("docs/run287_u0_v3_recovery_contract.json"),
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    census = read_json(args.source_census)
    inventory = read_json(args.inventory)
    contract = read_json(args.contract)
    recovered = build_recovery_census(census, inventory, contract)
    write_json(args.output_dir / "github_recovery_census.json", recovered)
    write_json(
        args.output_dir / "github_recovery_census_summary.json",
        {
            "schema_version": OUTPUT_SCHEMA,
            "repository": recovered["repository"],
            "audit_default_branch_sha": recovered["audit_default_branch_sha"],
            "source_census_sha256": recovered["source_census_sha256"],
            "recovery_census_sha256": canonical_sha256(recovered),
            "summary": recovered["summary"],
            "census_completion_blockers": recovered[
                "census_completion_blockers"
            ],
            "acceptance_migration_blockers": recovered[
                "acceptance_migration_blockers"
            ],
        },
    )
    write_candidate_csv(
        args.output_dir / "recovered_experiment_candidates.csv", recovered
    )
    print(json.dumps(recovered["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
