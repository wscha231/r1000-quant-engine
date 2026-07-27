#!/usr/bin/env python3
"""Audit the normalized Run287 U0 historical experiment inventory.

The audit distinguishes a structurally valid inventory from promotion
readiness.  Legacy evidence debt is an expected, explicit blocking state; it
must never be converted into a passing multiple-testing population by treating
summary metrics as daily after-cost return series.

Version 1 is an audit snapshot, not a recovery-schema validator: it has no
READY state and cannot remove a historical entry from the blocker set.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections import Counter
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONTRACT = (
    REPOSITORY_ROOT / "docs" / "run287_u0_experiment_audit_contract.json"
)
DEFAULT_REGISTRY = (
    REPOSITORY_ROOT / "docs" / "run287_do_not_repeat_registry.json"
)
DEFAULT_INVENTORY = (
    REPOSITORY_ROOT / "docs" / "run287_u0_experiment_inventory.json"
)

CONTRACT_SCHEMA = "run287-u0-experiment-audit-contract-v1"
INVENTORY_SCHEMA = "run287-u0-experiment-inventory-v1"
REGISTRY_SCHEMA = "run287-do-not-repeat-registry-v1"
AUDIT_STATUS = "VALID_INVENTORY_PROMOTION_BLOCKED"
PR_REF_PREFIX = "refs/run287-u0/pr"
BASE_REF = "refs/run287-u0/base"
KNOWN_OUT_OF_REGISTRY_PR_NUMBERS = {229, 230, 237}

HEX_40 = re.compile(r"[0-9a-f]{40}")
HEX_64 = re.compile(r"[0-9a-f]{64}")
REQUIRED_ENTRY_FIELDS = {
    "registry_entry_id",
    "evaluation_class",
    "selection_informed",
    "published_attempt_count_lower_bound",
    "exact_attempt_count_known",
    "evidence_state",
    "exact_trial_manifest_status",
    "after_cost_daily_return_series_status",
    "multiplicity_disposition",
    "overlap_group_ids",
    "evidence",
    "finding",
    "recovery_action",
}
OPTIONAL_ENTRY_FIELDS = {"published_results"}
REQUIRED_RULES = {
    "all_do_not_repeat_entries_classified_exactly_once": True,
    "canonical_registry_is_not_a_complete_historical_experiment_census": True,
    "known_out_of_registry_trials_must_be_explicit": True,
    "recovery_manifests_are_not_accepted_by_v1": True,
    "summary_metrics_are_not_daily_return_series": True,
    "portfolio_trials_require_exact_parameter_and_return_column_manifests": True,
    "portfolio_trials_require_synchronized_daily_after_cost_return_series": True,
    "source_screens_that_informed_selection_require_a_multiplicity_penalty": True,
    "overlap_resolution_requires_a_future_schema_migration": True,
    "orphaned_pull_request_evidence_must_bind_pr_ref_head_commit_and_git_blob": True,
    "missing_local_artifacts_must_be_explicit": True,
    "legacy_evidence_debt_blocks_preregistration_and_promotion": True,
    "audit_validity_does_not_imply_promotion_readiness": True,
    "automatic_champion_change_allowed": False,
    "fullrun_allowed_by_this_contract": False,
}


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: top-level JSON must be an object")
    return payload


def required_pr_numbers(inventory: dict[str, Any]) -> list[int]:
    numbers: set[int] = set()
    coverage = inventory.get("coverage")
    if isinstance(coverage, dict):
        for item in coverage.get("known_out_of_registry_backlog") or []:
            if isinstance(item, dict):
                evidence = item.get("evidence")
                if isinstance(evidence, dict):
                    number = evidence.get("pr_number")
                    if (
                        isinstance(number, int)
                        and not isinstance(number, bool)
                        and number > 0
                    ):
                        numbers.add(number)
    for entry in inventory.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        for evidence in entry.get("evidence") or []:
            if not isinstance(evidence, dict):
                continue
            if evidence.get("kind") != "github_pr":
                continue
            number = evidence.get("pr_number")
            if (
                isinstance(number, int)
                and not isinstance(number, bool)
                and number > 0
            ):
                numbers.add(number)
    return sorted(numbers)


def required_pr_refspecs(inventory: dict[str, Any]) -> list[str]:
    return [
        f"+refs/pull/{number}/head:{PR_REF_PREFIX}/{number}"
        for number in required_pr_numbers(inventory)
    ]


def required_base_refspec(inventory: dict[str, Any]) -> str:
    base_commit = str(inventory.get("base_commit") or "").lower()
    if not HEX_40.fullmatch(base_commit):
        raise ValueError("inventory base_commit must be a 40-character SHA")
    return f"+{base_commit}:{BASE_REF}"


def canonical_text_bytes(path: Path) -> bytes:
    text = path.read_text(encoding="utf-8")
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(canonical_text_bytes(path)).hexdigest()


def canonical_file_size(path: Path) -> int:
    return len(canonical_text_bytes(path))


@lru_cache(maxsize=None)
def git_output(repository_root: Path, *args: str) -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(repository_root), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


@lru_cache(maxsize=None)
def git_is_ancestor(
    repository_root: Path, ancestor: str, descendant: str
) -> bool | None:
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(repository_root),
            "merge-base",
            "--is-ancestor",
            ancestor,
            descendant,
        ],
        capture_output=True,
        check=False,
    )
    if completed.returncode == 0:
        return True
    if completed.returncode == 1:
        return False
    return None


@lru_cache(maxsize=None)
def committed_blob_bytes(
    repository_root: Path, repository_relative_path: str
) -> bytes | None:
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(repository_root),
            "show",
            f"HEAD:{repository_relative_path}",
        ],
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout


def repository_path(root: Path, value: Any) -> Path | None:
    text = str(value or "")
    if not text or "\\" in text:
        return None
    pure = PurePosixPath(text)
    if pure.is_absolute() or ".." in pure.parts:
        return None
    resolved = (root / Path(*pure.parts)).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return None
    return resolved


def validate_tracked_file_evidence(
    evidence: dict[str, Any],
    *,
    repository_root: Path,
    errors: list[str],
    entry_id: str,
    evidence_index: int,
) -> None:
    prefix = f"{entry_id}:evidence[{evidence_index}]"
    if set(evidence) != {"kind", "path", "sha256", "bytes"}:
        errors.append(f"{prefix}:tracked_file_fields_invalid")
        return
    path = repository_path(repository_root, evidence.get("path"))
    if path is None:
        errors.append(f"{prefix}:tracked_file_path_invalid")
        return
    path_text = str(evidence.get("path") or "")
    blob = committed_blob_bytes(repository_root, path_text)
    if blob is None:
        errors.append(f"{prefix}:tracked_file_blob_missing")
        return
    expected_sha = str(evidence.get("sha256") or "").lower()
    expected_bytes = evidence.get("bytes")
    if not HEX_64.fullmatch(expected_sha):
        errors.append(f"{prefix}:tracked_file_sha256_invalid")
    elif hashlib.sha256(blob).hexdigest() != expected_sha:
        errors.append(f"{prefix}:tracked_file_sha256_mismatch")
    if (
        isinstance(expected_bytes, bool)
        or not isinstance(expected_bytes, int)
        or expected_bytes <= 0
    ):
        errors.append(f"{prefix}:tracked_file_bytes_invalid")
    elif len(blob) != expected_bytes:
        errors.append(f"{prefix}:tracked_file_bytes_mismatch")


def validate_github_pr_evidence(
    evidence: dict[str, Any],
    *,
    repository_root: Path,
    errors: list[str],
    entry_id: str,
    evidence_index: int,
    allowed_ancestry: set[str],
) -> None:
    prefix = f"{entry_id}:evidence[{evidence_index}]"
    if set(evidence) != {
        "kind",
        "pr_number",
        "url",
        "head_commit",
        "ancestry",
        "artifacts",
    }:
        errors.append(f"{prefix}:github_pr_fields_invalid")
        return
    number = evidence.get("pr_number")
    valid_number = (
        isinstance(number, int)
        and not isinstance(number, bool)
        and number > 0
    )
    if not valid_number:
        errors.append(f"{prefix}:github_pr_number_invalid")
    expected_url = (
        "https://github.com/wscha231/r1000-quant-engine/pull/"
        f"{number}"
    )
    if evidence.get("url") != expected_url:
        errors.append(f"{prefix}:github_pr_url_invalid")
    head_commit = str(evidence.get("head_commit") or "").lower()
    valid_head = bool(HEX_40.fullmatch(head_commit))
    if not valid_head:
        errors.append(f"{prefix}:github_pr_head_commit_invalid")
    if valid_number and valid_head:
        pr_ref = f"{PR_REF_PREFIX}/{number}"
        observed_head = git_output(
            repository_root, "rev-parse", f"{pr_ref}^{{commit}}"
        )
        if observed_head is None:
            errors.append(f"{prefix}:github_pr_ref_missing")
        elif observed_head.lower() != head_commit:
            errors.append(f"{prefix}:github_pr_ref_head_mismatch")
        ancestry_observed = git_is_ancestor(
            repository_root, pr_ref, BASE_REF
        )
        if ancestry_observed is None:
            errors.append(f"{prefix}:github_pr_ancestry_unverifiable")
        else:
            expected_in_base = (
                evidence.get("ancestry") == "CURRENT_MASTER"
            )
            if ancestry_observed is not expected_in_base:
                errors.append(f"{prefix}:github_pr_ancestry_mismatch")
    if evidence.get("ancestry") not in allowed_ancestry:
        errors.append(f"{prefix}:github_pr_ancestry_invalid")
    artifacts = evidence.get("artifacts")
    if not isinstance(artifacts, list):
        errors.append(f"{prefix}:github_pr_artifacts_invalid")
        return
    seen_paths: set[str] = set()
    for artifact_index, artifact in enumerate(artifacts):
        artifact_prefix = f"{prefix}:artifact[{artifact_index}]"
        if not isinstance(artifact, dict) or set(artifact) != {
            "path",
            "git_blob_oid",
            "bytes",
        }:
            errors.append(f"{artifact_prefix}:fields_invalid")
            continue
        path_text = str(artifact.get("path") or "")
        if (
            repository_path(Path("/audit-root"), path_text) is None
            or path_text in seen_paths
        ):
            errors.append(f"{artifact_prefix}:path_invalid_or_duplicate")
        seen_paths.add(path_text)
        if not HEX_40.fullmatch(
            str(artifact.get("git_blob_oid") or "").lower()
        ):
            errors.append(f"{artifact_prefix}:git_blob_oid_invalid")
        elif valid_number and valid_head:
            pr_ref = f"{PR_REF_PREFIX}/{number}"
            observed_oid = git_output(
                repository_root,
                "rev-parse",
                f"{pr_ref}:{path_text}",
            )
            if observed_oid is None:
                errors.append(f"{artifact_prefix}:git_blob_missing")
            elif observed_oid.lower() != str(
                artifact.get("git_blob_oid")
            ).lower():
                errors.append(f"{artifact_prefix}:git_blob_oid_mismatch")
        size = artifact.get("bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            errors.append(f"{artifact_prefix}:bytes_invalid")
        elif valid_number and valid_head:
            observed_size = git_output(
                repository_root,
                "cat-file",
                "-s",
                str(artifact.get("git_blob_oid") or ""),
            )
            if observed_size is None or observed_size != str(size):
                errors.append(f"{artifact_prefix}:bytes_mismatch")


def validate_actions_evidence(
    evidence: dict[str, Any],
    *,
    errors: list[str],
    entry_id: str,
    evidence_index: int,
) -> None:
    prefix = f"{entry_id}:evidence[{evidence_index}]"
    if set(evidence) != {
        "kind",
        "run_id",
        "url",
        "commit_sha",
        "artifact_status",
    }:
        errors.append(f"{prefix}:github_actions_fields_invalid")
        return
    run_id = evidence.get("run_id")
    if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id <= 0:
        errors.append(f"{prefix}:github_actions_run_id_invalid")
    expected_url = (
        "https://github.com/wscha231/r1000-quant-engine/actions/runs/"
        f"{run_id}"
    )
    if evidence.get("url") != expected_url:
        errors.append(f"{prefix}:github_actions_url_invalid")
    if not HEX_40.fullmatch(
        str(evidence.get("commit_sha") or "").lower()
    ):
        errors.append(f"{prefix}:github_actions_commit_sha_invalid")
    if evidence.get("artifact_status") not in {
        "AVAILABLE_EXTERNALLY_NOT_PINNED",
        "MISSING_OR_EXPIRED",
        "SUMMARY_ONLY",
    }:
        errors.append(f"{prefix}:github_actions_artifact_status_invalid")


def validate_missing_evidence(
    evidence: dict[str, Any],
    *,
    repository_root: Path,
    errors: list[str],
    entry_id: str,
    evidence_index: int,
) -> None:
    prefix = f"{entry_id}:evidence[{evidence_index}]"
    if set(evidence) != {"kind", "path", "reason"}:
        errors.append(f"{prefix}:missing_local_artifact_fields_invalid")
        return
    path = repository_path(repository_root, evidence.get("path"))
    if path is None:
        errors.append(f"{prefix}:missing_local_artifact_path_invalid")
    elif path.exists():
        errors.append(f"{prefix}:missing_local_artifact_now_exists")
    if not str(evidence.get("reason") or "").strip():
        errors.append(f"{prefix}:missing_local_artifact_reason_missing")


def audit_inventory(
    *,
    contract: dict[str, Any],
    registry: dict[str, Any],
    inventory: dict[str, Any],
    repository_root: Path,
    registry_path: Path,
    inventory_path: Path,
) -> dict[str, Any]:
    errors: list[str] = []
    promotion_blockers: list[str] = []

    if contract.get("schema_version") != CONTRACT_SCHEMA:
        errors.append("contract_schema_invalid")
    if contract.get("inventory_schema_version") != INVENTORY_SCHEMA:
        errors.append("contract_inventory_schema_invalid")
    if inventory.get("schema_version") != INVENTORY_SCHEMA:
        errors.append("inventory_schema_invalid")
    if registry.get("schema_version") != REGISTRY_SCHEMA:
        errors.append("registry_schema_invalid")
    if contract.get("rules") != REQUIRED_RULES:
        errors.append("contract_rules_invalid")
    base_commit = str(inventory.get("base_commit") or "").lower()
    if not HEX_40.fullmatch(base_commit):
        errors.append("base_commit_invalid")
    else:
        observed_base = git_output(
            repository_root, "rev-parse", f"{BASE_REF}^{{commit}}"
        )
        if observed_base is None:
            errors.append("base_ref_missing")
        elif observed_base.lower() != base_commit:
            errors.append("base_ref_commit_mismatch")

    classes = set(contract.get("evaluation_classes") or [])
    evidence_states = set(contract.get("evidence_states") or [])
    manifest_states = set(contract.get("trial_manifest_states") or [])
    return_states = set(contract.get("daily_return_series_states") or [])
    dispositions = set(contract.get("multiplicity_dispositions") or [])
    allowed_ancestry = set(contract.get("github_pr_ancestry_states") or [])
    if not all(
        (
            classes,
            evidence_states,
            manifest_states,
            return_states,
            dispositions,
            allowed_ancestry,
        )
    ):
        errors.append("contract_enumerations_incomplete")

    coverage = inventory.get("coverage")
    coverage_scope = ""
    historical_census_complete: bool | None = None
    coverage_backlog: list[Any] = []
    backlog_pr_numbers: set[int] = set()
    if not isinstance(coverage, dict) or set(coverage) != {
        "scope",
        "historical_experiment_census_complete",
        "known_out_of_registry_backlog",
    }:
        errors.append("coverage_binding_invalid")
    else:
        coverage_scope = str(coverage.get("scope") or "")
        historical_census_complete = coverage.get(
            "historical_experiment_census_complete"
        )
        raw_backlog = coverage.get("known_out_of_registry_backlog")
        if (
            coverage_scope != contract.get("coverage_scope")
            or coverage_scope
            != "CANONICAL_DO_NOT_REPEAT_REGISTRY_ONLY"
        ):
            errors.append("coverage_scope_invalid")
        if historical_census_complete is not False:
            errors.append(
                "historical_experiment_census_must_remain_incomplete"
            )
        if not isinstance(raw_backlog, list) or not raw_backlog:
            errors.append("known_out_of_registry_backlog_invalid")
        else:
            coverage_backlog = raw_backlog
            for backlog_index, backlog_item in enumerate(coverage_backlog):
                prefix = f"coverage_backlog[{backlog_index}]"
                if (
                    not isinstance(backlog_item, dict)
                    or set(backlog_item) != {"reason", "evidence"}
                    or not str(backlog_item.get("reason") or "").strip()
                    or not isinstance(backlog_item.get("evidence"), dict)
                ):
                    errors.append(f"{prefix}:fields_invalid")
                    continue
                evidence = backlog_item["evidence"]
                validate_github_pr_evidence(
                    evidence,
                    repository_root=repository_root,
                    errors=errors,
                    entry_id=prefix,
                    evidence_index=0,
                    allowed_ancestry=allowed_ancestry,
                )
                pr_number = evidence.get("pr_number")
                if (
                    isinstance(pr_number, int)
                    and not isinstance(pr_number, bool)
                ):
                    if pr_number in backlog_pr_numbers:
                        errors.append(f"{prefix}:duplicate_pr_number")
                    backlog_pr_numbers.add(pr_number)
    contract_backlog_numbers = contract.get(
        "known_out_of_registry_pr_numbers"
    )
    if (
        not isinstance(contract_backlog_numbers, list)
        or set(contract_backlog_numbers)
        != KNOWN_OUT_OF_REGISTRY_PR_NUMBERS
        or len(contract_backlog_numbers)
        != len(KNOWN_OUT_OF_REGISTRY_PR_NUMBERS)
    ):
        errors.append("contract_known_backlog_pr_numbers_invalid")
    if backlog_pr_numbers != KNOWN_OUT_OF_REGISTRY_PR_NUMBERS:
        errors.append("known_out_of_registry_pr_numbers_mismatch")

    source = inventory.get("source_registry")
    source_registry_blob = committed_blob_bytes(
        repository_root, "docs/run287_do_not_repeat_registry.json"
    )
    if not isinstance(source, dict) or set(source) != {
        "path",
        "schema_version",
        "sha256",
        "bytes",
        "entry_count",
    }:
        errors.append("source_registry_binding_invalid")
    else:
        if source.get("path") != "docs/run287_do_not_repeat_registry.json":
            errors.append("source_registry_path_invalid")
        if source.get("schema_version") != REGISTRY_SCHEMA:
            errors.append("source_registry_schema_invalid")
        if source_registry_blob is None:
            errors.append("source_registry_blob_missing")
        elif source.get("sha256") != hashlib.sha256(
            source_registry_blob
        ).hexdigest():
            errors.append("source_registry_sha256_mismatch")
        if (
            source_registry_blob is not None
            and source.get("bytes") != len(source_registry_blob)
        ):
            errors.append("source_registry_bytes_mismatch")

    registry_entries = registry.get("entries")
    if not isinstance(registry_entries, list):
        registry_entries = []
        errors.append("registry_entries_invalid")
    registry_ids = [str(entry.get("id") or "") for entry in registry_entries]
    if any(not value for value in registry_ids):
        errors.append("registry_entry_id_missing")
    if len(registry_ids) != len(set(registry_ids)):
        errors.append("registry_entry_ids_not_unique")
    if isinstance(source, dict) and source.get("entry_count") != len(
        registry_ids
    ):
        errors.append("source_registry_entry_count_mismatch")

    entries = inventory.get("entries")
    if not isinstance(entries, list):
        entries = []
        errors.append("inventory_entries_invalid")
    inventory_ids = [
        str(entry.get("registry_entry_id") or "")
        for entry in entries
        if isinstance(entry, dict)
    ]
    if len(inventory_ids) != len(entries):
        errors.append("inventory_entry_object_invalid")
    if len(inventory_ids) != len(set(inventory_ids)):
        errors.append("inventory_entry_ids_not_unique")
    missing = sorted(set(registry_ids) - set(inventory_ids))
    extra = sorted(set(inventory_ids) - set(registry_ids))
    if missing:
        errors.append("inventory_registry_entries_missing:" + ",".join(missing))
    if extra:
        errors.append("inventory_registry_entries_extra:" + ",".join(extra))

    overlap_groups = inventory.get("overlap_groups")
    if not isinstance(overlap_groups, list):
        overlap_groups = []
        errors.append("overlap_groups_invalid")
    group_members: dict[str, set[str]] = {}
    unresolved_group_ids: set[str] = set()
    for index, group in enumerate(overlap_groups):
        prefix = f"overlap_group[{index}]"
        if not isinstance(group, dict) or set(group) != {
            "id",
            "deduplication_status",
            "canonical_trial_ids",
            "member_registry_entry_ids",
            "reason",
        }:
            errors.append(f"{prefix}:fields_invalid")
            continue
        group_id = str(group.get("id") or "")
        members = group.get("member_registry_entry_ids")
        canonical_trial_ids = group.get("canonical_trial_ids")
        if (
            not group_id
            or group_id in group_members
            or group.get("deduplication_status") != "UNRESOLVED"
            or canonical_trial_ids != []
            or not isinstance(members, list)
            or len(members) < 2
            or len(members) != len(set(members))
            or not set(members).issubset(set(registry_ids))
            or not str(group.get("reason") or "").strip()
        ):
            errors.append(f"{prefix}:definition_invalid")
            continue
        group_members[group_id] = set(members)
        unresolved_group_ids.add(group_id)

    class_counts: Counter[str] = Counter()
    evidence_state_counts: Counter[str] = Counter()
    orphaned_pr_evidence_count = 0
    blocked_ids: list[str] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        entry_id = str(entry.get("registry_entry_id") or f"index-{index}")
        keys = set(entry)
        if not REQUIRED_ENTRY_FIELDS.issubset(keys) or not keys.issubset(
            REQUIRED_ENTRY_FIELDS | OPTIONAL_ENTRY_FIELDS
        ):
            errors.append(f"{entry_id}:entry_fields_invalid")
            continue
        evaluation_class = str(entry.get("evaluation_class") or "")
        evidence_state = str(entry.get("evidence_state") or "")
        manifest_status = str(
            entry.get("exact_trial_manifest_status") or ""
        )
        return_status = str(
            entry.get("after_cost_daily_return_series_status") or ""
        )
        disposition = str(entry.get("multiplicity_disposition") or "")
        if evaluation_class not in classes:
            errors.append(f"{entry_id}:evaluation_class_invalid")
        if evidence_state not in evidence_states:
            errors.append(f"{entry_id}:evidence_state_invalid")
        if manifest_status not in manifest_states:
            errors.append(f"{entry_id}:trial_manifest_status_invalid")
        if return_status not in return_states:
            errors.append(f"{entry_id}:daily_return_series_status_invalid")
        if disposition not in dispositions:
            errors.append(f"{entry_id}:multiplicity_disposition_invalid")
        class_counts[evaluation_class] += 1
        evidence_state_counts[evidence_state] += 1

        lower_bound = entry.get("published_attempt_count_lower_bound")
        exact_count_known = entry.get("exact_attempt_count_known")
        if (
            isinstance(lower_bound, bool)
            or not isinstance(lower_bound, int)
            or lower_bound < 0
        ):
            errors.append(f"{entry_id}:attempt_count_lower_bound_invalid")
        if not isinstance(exact_count_known, bool):
            errors.append(f"{entry_id}:exact_attempt_count_known_invalid")
        if not isinstance(entry.get("selection_informed"), bool):
            errors.append(f"{entry_id}:selection_informed_invalid")
        if not str(entry.get("finding") or "").strip():
            errors.append(f"{entry_id}:finding_missing")
        if not str(entry.get("recovery_action") or "").strip():
            errors.append(f"{entry_id}:recovery_action_missing")

        cited_groups = entry.get("overlap_group_ids")
        if (
            not isinstance(cited_groups, list)
            or len(cited_groups) != len(set(cited_groups))
            or any(group_id not in group_members for group_id in cited_groups)
        ):
            errors.append(f"{entry_id}:overlap_group_ids_invalid")
        else:
            expected_groups = sorted(
                group_id
                for group_id, members in group_members.items()
                if entry_id in members
            )
            if sorted(cited_groups) != expected_groups:
                errors.append(f"{entry_id}:overlap_group_membership_mismatch")

        evidence_items = entry.get("evidence")
        if not isinstance(evidence_items, list) or not evidence_items:
            errors.append(f"{entry_id}:evidence_missing")
        else:
            for evidence_index, evidence in enumerate(evidence_items):
                if not isinstance(evidence, dict):
                    errors.append(
                        f"{entry_id}:evidence[{evidence_index}]:object_invalid"
                    )
                    continue
                kind = evidence.get("kind")
                if kind == "tracked_file":
                    validate_tracked_file_evidence(
                        evidence,
                        repository_root=repository_root,
                        errors=errors,
                        entry_id=entry_id,
                        evidence_index=evidence_index,
                    )
                elif kind == "github_pr":
                    validate_github_pr_evidence(
                        evidence,
                        repository_root=repository_root,
                        errors=errors,
                        entry_id=entry_id,
                        evidence_index=evidence_index,
                        allowed_ancestry=allowed_ancestry,
                    )
                    if (
                        evidence.get("ancestry")
                        == "ORPHANED_FROM_CURRENT_MASTER"
                    ):
                        orphaned_pr_evidence_count += 1
                elif kind == "github_actions_run":
                    validate_actions_evidence(
                        evidence,
                        errors=errors,
                        entry_id=entry_id,
                        evidence_index=evidence_index,
                    )
                elif kind == "missing_local_artifact":
                    validate_missing_evidence(
                        evidence,
                        repository_root=repository_root,
                        errors=errors,
                        entry_id=entry_id,
                        evidence_index=evidence_index,
                    )
                else:
                    errors.append(
                        f"{entry_id}:evidence[{evidence_index}]:kind_invalid"
                    )

        if not disposition.startswith("BLOCK_"):
            errors.append(f"{entry_id}:v1_disposition_must_block")
        blocked_ids.append(entry_id)
        promotion_blockers.append(f"{entry_id}:{disposition}")

    for group_id in sorted(unresolved_group_ids):
        promotion_blockers.append(
            f"overlap:{group_id}:DEDUPLICATION_UNRESOLVED"
        )

    summary = inventory.get("summary")
    computed_summary = {
        "registry_entry_count": len(registry_ids),
        "classified_entry_count": len(inventory_ids),
        "promotion_blocked_entry_count": len(blocked_ids),
        "orphaned_pr_evidence_count": orphaned_pr_evidence_count,
        "known_out_of_registry_backlog_count": len(coverage_backlog),
        "evaluation_class_counts": dict(sorted(class_counts.items())),
        "evidence_state_counts": dict(
            sorted(evidence_state_counts.items())
        ),
    }
    if summary != computed_summary:
        errors.append("inventory_summary_mismatch")

    declared_ready = inventory.get("promotion_ready")
    coverage_blocked = historical_census_complete is not True
    if coverage_blocked:
        promotion_blockers.append(
            "coverage:HISTORICAL_EXPERIMENT_CENSUS_INCOMPLETE"
        )
    computed_ready = not blocked_ids and not coverage_blocked and not errors
    if declared_ready is not computed_ready:
        errors.append("promotion_ready_declaration_mismatch")
    if inventory.get("performance_claim_allowed") is not False:
        errors.append("performance_claim_must_remain_blocked")
    if inventory.get("fullrun_authorized") is not False:
        errors.append("fullrun_must_remain_unauthorized")
    if inventory.get("champion_change_authorized") is not False:
        errors.append("champion_change_must_remain_unauthorized")
    if inventory.get("audit_status") != AUDIT_STATUS:
        errors.append("audit_status_invalid")
    if computed_ready:
        errors.append("legacy_inventory_unexpectedly_promotion_ready")

    valid = not errors
    return {
        "schema_version": "run287-u0-experiment-audit-result-v1",
        "status": (
            AUDIT_STATUS if valid else "INVALID_INVENTORY_PROMOTION_BLOCKED"
        ),
        "valid": valid,
        "promotion_ready": False,
        "performance_claim_allowed": False,
        "fullrun_authorized": False,
        "champion_change_authorized": False,
        "registry_entry_count": len(registry_ids),
        "classified_entry_count": len(inventory_ids),
        "promotion_blocked_entry_count": len(blocked_ids),
        "blocked_registry_entry_ids": sorted(blocked_ids),
        "coverage_scope": coverage_scope,
        "historical_experiment_census_complete": (
            historical_census_complete is True
        ),
        "known_out_of_registry_backlog_count": len(coverage_backlog),
        "overlap_group_count": len(group_members),
        "orphaned_pr_evidence_count": orphaned_pr_evidence_count,
        "errors": errors,
        "promotion_blockers": promotion_blockers,
        "inventory_path": inventory_path.as_posix(),
        "inventory_sha256": sha256_file(inventory_path),
        "source_registry_sha256": (
            hashlib.sha256(source_registry_blob).hexdigest()
            if source_registry_blob is not None
            else None
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--print-fetch-refspecs",
        action="store_true",
        help="Print the exact GitHub PR refspecs required by the audit.",
    )
    parser.add_argument(
        "--print-base-refspec",
        action="store_true",
        help="Print the exact historical audit base refspec.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.print_base_refspec:
        print(required_base_refspec(read_json(args.inventory)))
        return 0
    if args.print_fetch_refspecs:
        for refspec in required_pr_refspecs(read_json(args.inventory)):
            print(refspec)
        return 0
    result = audit_inventory(
        contract=read_json(args.contract),
        registry=read_json(args.registry),
        inventory=read_json(args.inventory),
        repository_root=args.repository_root.resolve(),
        registry_path=args.registry.resolve(),
        inventory_path=args.inventory.resolve(),
    )
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
