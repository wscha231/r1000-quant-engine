#!/usr/bin/env python3
"""Audit the normalized Run287 U0 historical experiment inventory.

The audit distinguishes a structurally valid inventory from promotion
readiness.  Legacy evidence debt is an expected, explicit blocking state; it
must never be converted into a passing multiple-testing population by treating
summary metrics as daily after-cost return series.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
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
OPTIONAL_ENTRY_FIELDS = {
    "published_results",
    "trial_manifest",
    "daily_return_series_manifest",
}


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: top-level JSON must be an object")
    return payload


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    if not path.is_file():
        errors.append(f"{prefix}:tracked_file_missing")
        return
    expected_sha = str(evidence.get("sha256") or "").lower()
    expected_bytes = evidence.get("bytes")
    if not HEX_64.fullmatch(expected_sha):
        errors.append(f"{prefix}:tracked_file_sha256_invalid")
    elif sha256_file(path) != expected_sha:
        errors.append(f"{prefix}:tracked_file_sha256_mismatch")
    if (
        isinstance(expected_bytes, bool)
        or not isinstance(expected_bytes, int)
        or expected_bytes <= 0
    ):
        errors.append(f"{prefix}:tracked_file_bytes_invalid")
    elif path.stat().st_size != expected_bytes:
        errors.append(f"{prefix}:tracked_file_bytes_mismatch")


def validate_github_pr_evidence(
    evidence: dict[str, Any],
    *,
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
    if isinstance(number, bool) or not isinstance(number, int) or number <= 0:
        errors.append(f"{prefix}:github_pr_number_invalid")
    expected_url = (
        "https://github.com/wscha231/r1000-quant-engine/pull/"
        f"{number}"
    )
    if evidence.get("url") != expected_url:
        errors.append(f"{prefix}:github_pr_url_invalid")
    if not HEX_40.fullmatch(
        str(evidence.get("head_commit") or "").lower()
    ):
        errors.append(f"{prefix}:github_pr_head_commit_invalid")
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
        size = artifact.get("bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            errors.append(f"{artifact_prefix}:bytes_invalid")


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

    source = inventory.get("source_registry")
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
        if source.get("sha256") != sha256_file(registry_path):
            errors.append("source_registry_sha256_mismatch")
        if source.get("bytes") != registry_path.stat().st_size:
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
    for index, group in enumerate(overlap_groups):
        prefix = f"overlap_group[{index}]"
        if not isinstance(group, dict) or set(group) != {
            "id",
            "member_registry_entry_ids",
            "reason",
        }:
            errors.append(f"{prefix}:fields_invalid")
            continue
        group_id = str(group.get("id") or "")
        members = group.get("member_registry_entry_ids")
        if (
            not group_id
            or group_id in group_members
            or not isinstance(members, list)
            or len(members) < 2
            or len(members) != len(set(members))
            or not set(members).issubset(set(registry_ids))
            or not str(group.get("reason") or "").strip()
        ):
            errors.append(f"{prefix}:definition_invalid")
            continue
        group_members[group_id] = set(members)

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

        trial_manifest = entry.get("trial_manifest")
        if manifest_status == "READY":
            if (
                not isinstance(trial_manifest, dict)
                or set(trial_manifest)
                != {
                    "schema_version",
                    "sha256",
                    "trial_count",
                    "trial_specifications",
                }
                or trial_manifest.get("schema_version")
                != "run287-prior-trial-manifest-v1"
                or not HEX_64.fullmatch(
                    str(trial_manifest.get("sha256") or "").lower()
                )
                or isinstance(trial_manifest.get("trial_count"), bool)
                or not isinstance(trial_manifest.get("trial_count"), int)
                or trial_manifest.get("trial_count") <= 0
                or not isinstance(
                    trial_manifest.get("trial_specifications"), dict
                )
                or len(trial_manifest.get("trial_specifications"))
                != trial_manifest.get("trial_count")
            ):
                errors.append(f"{entry_id}:ready_trial_manifest_invalid")
        elif trial_manifest is not None:
            errors.append(f"{entry_id}:nonready_trial_manifest_present")

        return_manifest = entry.get("daily_return_series_manifest")
        if return_status == "READY":
            if (
                not isinstance(return_manifest, dict)
                or set(return_manifest)
                != {
                    "path",
                    "sha256",
                    "date_column",
                    "first_session",
                    "last_session",
                    "session_count",
                    "return_columns",
                    "cost_model_sha256",
                }
                or repository_path(
                    repository_root, return_manifest.get("path")
                )
                is None
                or not HEX_64.fullmatch(
                    str(return_manifest.get("sha256") or "").lower()
                )
                or return_manifest.get("date_column") != "date"
                or not re.fullmatch(
                    r"\d{4}-\d{2}-\d{2}",
                    str(return_manifest.get("first_session") or ""),
                )
                or not re.fullmatch(
                    r"\d{4}-\d{2}-\d{2}",
                    str(return_manifest.get("last_session") or ""),
                )
                or isinstance(return_manifest.get("session_count"), bool)
                or not isinstance(return_manifest.get("session_count"), int)
                or return_manifest.get("session_count") <= 0
                or not isinstance(return_manifest.get("return_columns"), list)
                or not return_manifest.get("return_columns")
                or len(return_manifest.get("return_columns"))
                != len(set(return_manifest.get("return_columns")))
                or not HEX_64.fullmatch(
                    str(
                        return_manifest.get("cost_model_sha256") or ""
                    ).lower()
                )
            ):
                errors.append(
                    f"{entry_id}:ready_daily_return_manifest_invalid"
                )
        elif return_manifest is not None:
            errors.append(
                f"{entry_id}:nonready_daily_return_manifest_present"
            )

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

        portfolio_like = evaluation_class in {
            "PORTFOLIO_RETURN",
            "MIXED_SOURCE_AND_PORTFOLIO",
            "NO_OP_PORTFOLIO",
        }
        source_like = evaluation_class in {
            "SOURCE_RETURN_SCREEN",
            "NO_SIGNAL",
        }
        ready = (
            portfolio_like
            and manifest_status == "READY"
            and return_status == "READY"
            and disposition == "INCLUDE_EXACT_RETURN_TRIALS"
        )
        if source_like and entry.get("selection_informed") is True:
            ready = (
                disposition == "SELECTION_MULTIPLICITY_PENALTY_IMPLEMENTED"
            )
        if evaluation_class in {
            "INVALID_OR_INCOMPLETE",
            "UNVERIFIED_LEGACY",
        }:
            ready = False
        if not ready:
            blocked_ids.append(entry_id)
            promotion_blockers.append(
                f"{entry_id}:{disposition}"
            )

    summary = inventory.get("summary")
    computed_summary = {
        "registry_entry_count": len(registry_ids),
        "classified_entry_count": len(inventory_ids),
        "promotion_blocked_entry_count": len(blocked_ids),
        "orphaned_pr_evidence_count": orphaned_pr_evidence_count,
        "evaluation_class_counts": dict(sorted(class_counts.items())),
        "evidence_state_counts": dict(
            sorted(evidence_state_counts.items())
        ),
    }
    if summary != computed_summary:
        errors.append("inventory_summary_mismatch")

    declared_ready = inventory.get("promotion_ready")
    computed_ready = not blocked_ids and not errors
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
        "overlap_group_count": len(group_members),
        "orphaned_pr_evidence_count": orphaned_pr_evidence_count,
        "errors": errors,
        "promotion_blockers": promotion_blockers,
        "inventory_path": inventory_path.as_posix(),
        "inventory_sha256": sha256_file(inventory_path),
        "source_registry_sha256": sha256_file(registry_path),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
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
