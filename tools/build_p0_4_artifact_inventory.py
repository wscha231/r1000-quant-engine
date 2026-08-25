#!/usr/bin/env python3
"""Build the frozen, read-only Run287 P0-4 artifact inventory.

The collector inputs are intentionally frozen in the repository.  This tool
does not contact GitHub or Google Drive.  It renders to an ephemeral sibling
directory and swaps the complete requested bundle only after every output has
been written.  Live enumeration is a separate, bounded evidence-gathering step;
incomplete provider views must be recorded as blocked in the source snapshot
rather than silently refreshed here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "docs" / "run287_p0_4_artifact_inventory" / "source_inventory_snapshot.json"
DEFAULT_OUTPUT = ROOT / "docs" / "run287_p0_4_artifact_inventory"
SCHEMA_VERSION = "run287-p0-4-inventory-source-v1"
REGISTRY_SCHEMA_VERSION = "run287-p0-4-registry-v1"
FROZEN_SOURCE_PUBLICATION_COMMIT = "5b6748fa4bd0ad5454eb2af4986324d724496bf8"
FROZEN_SOURCE_GIT_BLOB_SHA1 = "0b2037328b3a4d77231e0600c4829a549d99bc89"
FROZEN_SOURCE_SHA256 = "d13b1cc3c3dc46026257fb116f5e4180d0c5bd4165aec9e920d0e9da596279f3"
FROZEN_PUBLICATION_COMMIT = "f7fadfa4e7814c6453bf96ebf3a1ff4d39eadfae"
FROZEN_PROTECTED_PUBLICATION_COMMIT = "318fa1827d6796b577a1487a420233cacfc0d618"
GENERATOR_PATH = "tools/build_p0_4_artifact_inventory.py"
PROTECTED_PUBLICATION_PATHS = (
    ".github/workflows/pr_validation.yml",
    "docs/run287_p0_4_artifact_inventory",
    "tools/run_pr_validation.py",
)
UNBOUND_SOURCE_PUBLICATION = "UNBOUND_CUSTOM_SOURCE"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
OBJECT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]+$")
ALIAS_STATUSES = {
    "VERIFIED_IMMUTABLE",
    "BLOCKED_DIVERGENT",
    "BLOCKED_NO_IMMUTABLE_SOURCE",
    "BLOCKED_MULTIPLE_WRITERS",
    "NOT_APPLICABLE",
}
GENERATED_FILENAMES = {
    "README.md",
    "summary.json",
    "dataset_registry.yaml",
    "model_registry.yaml",
    "artifact_registry.parquet",
    "durable_state_registry.yaml",
    "latest_to_immutable_map.yaml",
    "migration_map.md",
}
BUNDLE_FILENAMES = GENERATED_FILENAMES | {
    "source_inventory_snapshot.json",
    "requirements.txt",
}
SAFETY_FALSE_FIELDS = (
    "live_trading_enabled",
    "production_activation_allowed",
    "target_order_ledger_mutation",
    "model_promotion",
)
REQUIRED_FIXED_ALIAS_OBJECTS = {
    "artifact.drive.operating-main-target-book": (
        "outputs/reports/operating_main_target_book.csv"
    ),
    "artifact.drive.operating-concentrated-target-book": (
        "outputs/reports/operating_concentrated_target_book.csv"
    ),
    "artifact.drive.portfolio-latest": "outputs/portfolio_latest.csv",
    "artifact.drive.concentrated-portfolio-latest": (
        "outputs/concentrated_portfolio_latest.csv"
    ),
}
REQUIRED_MUTABLE_ARCHIVE_OBJECTS = {
    "artifact.drive.paper-holding-risk-watch-archive": (
        "paper_archive/run287_holding_risk_watch/"
    ),
    "artifact.drive.paper-decision-observation-archive": (
        "paper_archive/run287_decision_observation_archive/"
    ),
    "artifact.drive.paper-risk-outcome-archive": (
        "paper_archive/run287_risk_outcome_archive/"
    ),
    "artifact.drive.paper-risk-outcome-price-cache": (
        "paper_archive/run287_risk_outcome_price_cache/"
    ),
}
OFFICIAL_TARGET_WORKFLOW = ".github/workflows/daily_operating_selection_refresh.yml"
PINNED_PUBLICATION_FILE_SHA256 = {
    ".github/workflows/pr_validation.yml": (
        "cbefba4c7362b3ca7c14e058d1e95831ff06c18fb85341e24245ae61c61bd17f"
    )
}
RISK_OUTCOME_FAILED_STEP = "Restore verified risk-outcome accepted head"
RISK_OUTCOME_SKIPPED_STEPS = {
    26: "Build operating target books",
    34: "Run transactional paper ledger and same-close selector",
    46: "Persist validated forward paper ledger state",
}
REQUIRED_OBJECT_FIELDS = {
    "object_id",
    "schema_version",
    "market",
    "logical_role",
    "producer",
    "storage_kind",
    "exact_location",
    "immutable_location",
    "mutable_alias",
    "as_of",
    "available_from",
    "decision_time_cutoff",
    "code_sha",
    "config_hash",
    "data_hash",
    "universe_hash",
    "source_artifact_hashes",
    "size_bytes",
    "row_count",
    "file_count",
    "content_sha256",
    "manifest_sha256",
    "writer_workflow",
    "writer_job",
    "write_authority",
    "pit_classification",
    "survivorship_classification",
    "corporate_action_classification",
    "license_classification",
    "secret_pii_classification",
    "retention_classification",
    "downstream_consumers",
    "rollback_restore",
    "mapping_status",
    "discovery_status",
    "blockers",
}
ARTIFACT_COLUMNS = [
    "object_id",
    "schema_version",
    "market",
    "object_class",
    "logical_role",
    "producer",
    "storage_kind",
    "exact_location",
    "immutable_location",
    "mutable_alias",
    "as_of",
    "available_from",
    "created_at",
    "decision_time_cutoff",
    "code_sha",
    "config_hash",
    "data_hash",
    "universe_hash",
    "source_artifact_hashes",
    "size_bytes",
    "row_count",
    "file_count",
    "content_sha256",
    "manifest_sha256",
    "writer_workflow",
    "writer_job",
    "write_authority",
    "pit_classification",
    "survivorship_classification",
    "corporate_action_classification",
    "license_classification",
    "secret_pii_classification",
    "retention_classification",
    "downstream_consumers",
    "rollback_restore",
    "mapping_status",
    "discovery_status",
    "blockers",
    "observed_at_utc",
    "baseline_code_sha",
    "source_snapshot_sha256",
    "source_publication_commit",
]


class InventoryError(ValueError):
    """Stable fail-closed inventory validation error."""


def canonical_source_bytes(value: bytes) -> bytes:
    return value.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def verify_frozen_source_publication(source_bytes: bytes) -> None:
    relative_source = DEFAULT_SOURCE.relative_to(ROOT).as_posix()
    ancestor = subprocess.run(
        [
            "git",
            "merge-base",
            "--is-ancestor",
            FROZEN_SOURCE_PUBLICATION_COMMIT,
            "HEAD",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    if ancestor.returncode != 0:
        raise InventoryError("frozen_source_publication_is_not_head_ancestor")
    try:
        blob_sha = subprocess.check_output(
            [
                "git",
                "rev-parse",
                f"{FROZEN_SOURCE_PUBLICATION_COMMIT}:{relative_source}",
            ],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
        ).strip()
        publication_bytes = subprocess.check_output(
            [
                "git",
                "show",
                f"{FROZEN_SOURCE_PUBLICATION_COMMIT}:{relative_source}",
            ],
            cwd=ROOT,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise InventoryError("frozen_source_publication_unavailable") from exc
    if blob_sha != FROZEN_SOURCE_GIT_BLOB_SHA1:
        raise InventoryError("frozen_source_publication_blob_mismatch")
    if hashlib.sha256(publication_bytes).hexdigest() != FROZEN_SOURCE_SHA256:
        raise InventoryError("frozen_source_publication_sha256_mismatch")
    if canonical_source_bytes(source_bytes) != publication_bytes:
        raise InventoryError("canonical_source_differs_from_frozen_publication")


def read_source(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise InventoryError(f"source_invalid_json:{type(exc).__name__}") from exc
    if not isinstance(payload, dict):
        raise InventoryError("source_not_object")
    return payload


def nonblank(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_hash(value: Any, *, field: str, allow_blank: bool = True) -> None:
    if value in (None, "") and allow_blank:
        return
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise InventoryError(f"invalid_sha256:{field}")


def validate_object(row: dict[str, Any], *, object_class: str) -> None:
    missing = sorted(REQUIRED_OBJECT_FIELDS - set(row))
    if missing:
        raise InventoryError(
            f"object_missing_fields:{object_class}:{row.get('object_id')}:{','.join(missing)}"
        )
    object_id = str(row.get("object_id") or "")
    if not OBJECT_ID_RE.fullmatch(object_id):
        raise InventoryError(f"object_id_invalid:{object_id}")
    if row.get("market") != "US":
        raise InventoryError(f"market_not_us:{object_id}")
    for field in (
        "schema_version",
        "logical_role",
        "producer",
        "storage_kind",
        "exact_location",
        "write_authority",
        "pit_classification",
        "survivorship_classification",
        "corporate_action_classification",
        "license_classification",
        "secret_pii_classification",
        "retention_classification",
        "rollback_restore",
        "mapping_status",
        "discovery_status",
    ):
        if not nonblank(row.get(field)):
            raise InventoryError(f"object_blank_field:{object_id}:{field}")
    for field in (
        "config_hash",
        "data_hash",
        "universe_hash",
        "content_sha256",
        "manifest_sha256",
    ):
        validate_hash(row.get(field), field=f"{object_id}.{field}")
    code_sha = row.get("code_sha")
    if code_sha not in (None, "") and (
        not isinstance(code_sha, str) or not SHA1_RE.fullmatch(code_sha)
    ):
        raise InventoryError(f"invalid_code_sha:{object_id}")
    source_hashes = row.get("source_artifact_hashes")
    if not isinstance(source_hashes, list):
        raise InventoryError(f"source_hashes_not_list:{object_id}")
    for index, value in enumerate(source_hashes):
        text = str(value)
        candidate = text.split(":", 1)[1] if text.startswith("sha256:") else text
        if not SHA256_RE.fullmatch(candidate):
            raise InventoryError(f"source_hash_invalid:{object_id}:{index}")
    for field in ("downstream_consumers", "blockers"):
        if not isinstance(row.get(field), list):
            raise InventoryError(f"object_field_not_list:{object_id}:{field}")
    if row.get("mapping_status") not in ALIAS_STATUSES:
        raise InventoryError(f"mapping_status_invalid:{object_id}")
    if row.get("mutable_alias") and row.get("mapping_status") == "NOT_APPLICABLE":
        raise InventoryError(f"mutable_alias_not_applicable:{object_id}")
    blocked = str(row.get("mapping_status")).startswith("BLOCKED_")
    if blocked and not row.get("blockers"):
        raise InventoryError(f"blocked_without_reason:{object_id}")
    if row.get("mutable_alias") and not (
        row.get("immutable_location") or blocked
    ):
        raise InventoryError(f"mutable_alias_not_bound_or_blocked:{object_id}")
    if (
        row.get("mapping_status") == "VERIFIED_IMMUTABLE"
        and row.get("storage_kind") == "git_tree"
        and row.get("mutable_alias")
        and not row.get("manifest_sha256")
    ):
        raise InventoryError(f"verified_git_tree_without_manifest_sha256:{object_id}")


def baseline_workflow_text(baseline: str) -> str:
    try:
        return subprocess.check_output(
            ["git", "show", f"{baseline}:{OFFICIAL_TARGET_WORKFLOW}"],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise InventoryError("official_target_workflow_not_available_at_baseline") from exc


def validate_failure_evidence(payload: dict[str, Any]) -> None:
    health = payload.get("pipeline_health")
    if not isinstance(health, dict):
        raise InventoryError("pipeline_health_missing")
    run_ids = health.get("daily_operating_recent_run_ids")
    evidence = health.get("daily_operating_failure_evidence")
    if not isinstance(run_ids, list) or not isinstance(evidence, list):
        raise InventoryError("risk_outcome_failure_evidence_missing")
    if [row.get("run_id") for row in evidence if isinstance(row, dict)] != run_ids:
        raise InventoryError("risk_outcome_failure_evidence_run_order")
    if len(evidence) != 3 or len(set(run_ids)) != 3:
        raise InventoryError("risk_outcome_failure_evidence_count")
    for row in evidence:
        if not isinstance(row, dict):
            raise InventoryError("risk_outcome_failure_evidence_not_object")
        run_id = row.get("run_id")
        if not isinstance(run_id, int) or run_id <= 0:
            raise InventoryError("risk_outcome_failure_evidence_run_id")
        if not isinstance(row.get("job_id"), int) or row["job_id"] <= 0:
            raise InventoryError(f"risk_outcome_failure_evidence_job_id:{run_id}")
        if row.get("event") != "schedule" or row.get("conclusion") != "failure":
            raise InventoryError(f"risk_outcome_failure_evidence_run_state:{run_id}")
        if row.get("failed_step") != RISK_OUTCOME_FAILED_STEP:
            raise InventoryError(f"risk_outcome_failure_evidence_step:{run_id}")
        if row.get("failed_step_number") != 19 or row.get("exit_code") != 2:
            raise InventoryError(f"risk_outcome_failure_evidence_exit:{run_id}")
        head_sha = str(row.get("head_sha") or "")
        if not SHA1_RE.fullmatch(head_sha):
            raise InventoryError(f"risk_outcome_failure_evidence_head:{run_id}")
        excerpt = row.get("terminal_excerpt_lines")
        if (
            not isinstance(excerpt, list)
            or len(excerpt) != 2
            or not all(nonblank(line) for line in excerpt)
        ):
            raise InventoryError(f"risk_outcome_failure_evidence_excerpt:{run_id}")
        canonical = ("\n".join(excerpt) + "\n").encode("utf-8")
        if hashlib.sha256(canonical).hexdigest() != row.get(
            "terminal_excerpt_sha256"
        ):
            raise InventoryError(f"risk_outcome_failure_evidence_excerpt_hash:{run_id}")
        skipped = row.get("downstream_skipped_steps")
        if not isinstance(skipped, list):
            raise InventoryError(f"risk_outcome_failure_evidence_skips:{run_id}")
        normalized = {
            item.get("step_number"): (item.get("name"), item.get("conclusion"))
            for item in skipped
            if isinstance(item, dict)
        }
        expected = {
            number: (name, "skipped")
            for number, name in RISK_OUTCOME_SKIPPED_STEPS.items()
        }
        if normalized != expected:
            raise InventoryError(f"risk_outcome_failure_evidence_skips:{run_id}")


def validate_source(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise InventoryError("source_schema_version")
    if payload.get("market") != "US":
        raise InventoryError("source_market")
    baseline = str(payload.get("baseline_code_sha") or "")
    if not SHA1_RE.fullmatch(baseline):
        raise InventoryError("baseline_code_sha")
    safety = payload.get("safety")
    if not isinstance(safety, dict):
        raise InventoryError("source_safety_missing")
    if safety.get("mutations_performed") != []:
        raise InventoryError("source_claims_mutations")
    for field in SAFETY_FALSE_FIELDS:
        if safety.get(field) is not False:
            raise InventoryError(f"source_claims_authority:{field}")
    defaults = payload.get("object_defaults")
    if not isinstance(defaults, dict):
        raise InventoryError("object_defaults_missing")
    objects_seen: set[str] = set()
    for collection, object_class in (
        ("datasets", "dataset"),
        ("models", "model"),
        ("durable_states", "durable_state"),
        ("artifacts", "artifact"),
    ):
        rows = payload.get(collection)
        if not isinstance(rows, list) or not rows:
            raise InventoryError(f"source_collection_empty:{collection}")
        normalized_rows: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                raise InventoryError(f"source_row_not_object:{collection}")
            normalized = {**defaults, **row}
            validate_object(normalized, object_class=object_class)
            object_id = normalized["object_id"]
            if object_id in objects_seen:
                raise InventoryError(f"duplicate_object_id:{object_id}")
            objects_seen.add(object_id)
            normalized_rows.append(normalized)
        payload[collection] = normalized_rows
    object_index = {
        row["object_id"]: row
        for collection in ("datasets", "models", "durable_states", "artifacts")
        for row in payload[collection]
    }
    aliases = payload.get("latest_to_immutable")
    if not isinstance(aliases, list) or not aliases:
        raise InventoryError("latest_map_empty")
    alias_ids: set[str] = set()
    for row in aliases:
        if not isinstance(row, dict):
            raise InventoryError("latest_map_row_not_object")
        object_id = str(row.get("object_id") or "")
        if object_id not in objects_seen:
            raise InventoryError(f"latest_map_unknown_object:{object_id}")
        if object_id in alias_ids:
            raise InventoryError(f"latest_map_duplicate:{object_id}")
        alias_ids.add(object_id)
        status = row.get("status")
        if status not in ALIAS_STATUSES:
            raise InventoryError(f"latest_map_status:{object_id}")
        if status == "NOT_APPLICABLE":
            raise InventoryError(f"latest_map_mutable_alias_not_applicable:{object_id}")
        object_row = object_index[object_id]
        if row.get("mutable_alias") != object_row.get("mutable_alias"):
            raise InventoryError(f"latest_map_alias_mismatch:{object_id}")
        if status != object_row.get("mapping_status"):
            raise InventoryError(f"latest_map_object_status_mismatch:{object_id}")
        blockers = row.get("blockers")
        if not isinstance(blockers, list):
            raise InventoryError(f"latest_map_blockers_not_list:{object_id}")
        if str(status).startswith("BLOCKED_") and not blockers:
            raise InventoryError(f"latest_map_blocked_without_reason:{object_id}")
        if status == "VERIFIED_IMMUTABLE":
            if not nonblank(row.get("immutable_source")):
                raise InventoryError(
                    f"latest_map_verified_without_immutable_source:{object_id}"
                )
            if blockers:
                raise InventoryError(f"latest_map_verified_with_blockers:{object_id}")
    mutable_ids = {
        row["object_id"]
        for collection in ("datasets", "models", "durable_states", "artifacts")
        for row in payload[collection]
        if row.get("mutable_alias")
    }
    missing_aliases = sorted(mutable_ids - alias_ids)
    if missing_aliases:
        raise InventoryError("latest_map_missing_aliases:" + ",".join(missing_aliases))
    workflow_text = baseline_workflow_text(baseline)
    for object_id, alias in REQUIRED_FIXED_ALIAS_OBJECTS.items():
        if alias not in workflow_text:
            raise InventoryError(f"fixed_alias_not_in_baseline_workflow:{alias}")
        row = object_index.get(object_id)
        if row is None:
            raise InventoryError(f"required_fixed_alias_object_missing:{object_id}")
        if row.get("mutable_alias") != alias:
            raise InventoryError(f"required_fixed_alias_mismatch:{object_id}")
        if object_id not in alias_ids:
            raise InventoryError(f"required_fixed_alias_map_missing:{object_id}")
    for object_id, alias in REQUIRED_MUTABLE_ARCHIVE_OBJECTS.items():
        if alias not in workflow_text:
            raise InventoryError(f"mutable_archive_not_in_baseline_workflow:{alias}")
        row = object_index.get(object_id)
        if row is None:
            raise InventoryError(f"required_mutable_archive_missing:{object_id}")
        if row.get("mutable_alias") != alias:
            raise InventoryError(f"required_mutable_archive_mismatch:{object_id}")
        if object_id not in alias_ids:
            raise InventoryError(f"required_mutable_archive_map_missing:{object_id}")
    validate_failure_evidence(payload)
    if not isinstance(payload.get("migration_items"), list) or not payload["migration_items"]:
        raise InventoryError("migration_items_empty")
    if not isinstance(payload.get("findings"), list) or not payload["findings"]:
        raise InventoryError("findings_empty")


def registry_document(payload: dict[str, Any], key: str) -> dict[str, Any]:
    return {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "source_schema_version": payload["schema_version"],
        "market": "US",
        "baseline_code_sha": payload["baseline_code_sha"],
        "observed_at_utc": payload["observed_at_utc"],
        "source_snapshot_sha256": payload["_source_sha256"],
        "discovery_limits": payload["discovery_limits"],
        key: payload[key],
    }


def write_yaml(path: Path, payload: dict[str, Any]) -> None:
    text = yaml.safe_dump(
        payload,
        allow_unicode=True,
        sort_keys=False,
        width=120,
    )
    path.write_text(text, encoding="utf-8", newline="\n")


def serialise_cell(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return value


def artifact_rows(
    payload: dict[str, Any], *, source_publication_commit: str
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    observed = payload["observed_at_utc"]
    for collection, object_class in (
        ("datasets", "dataset"),
        ("models", "model"),
        ("durable_states", "durable_state"),
        ("artifacts", "artifact"),
    ):
        for source in payload[collection]:
            row = {column: source.get(column, "") for column in ARTIFACT_COLUMNS}
            row["object_class"] = object_class
            row["observed_at_utc"] = observed
            row["baseline_code_sha"] = payload["baseline_code_sha"]
            row["source_snapshot_sha256"] = payload["_source_sha256"]
            row["source_publication_commit"] = source_publication_commit
            rows.append({key: serialise_cell(value) for key, value in row.items()})
    return sorted(rows, key=lambda item: item["object_id"])


def write_parquet(path: Path, rows: list[dict[str, Any]]) -> None:
    frame = pd.DataFrame(rows, columns=ARTIFACT_COLUMNS)
    for field in ("size_bytes", "row_count", "file_count"):
        frame[field] = pd.array(frame[field], dtype="Int64")
    frame.to_parquet(
        path,
        index=False,
        engine="pyarrow",
        compression="zstd",
        version="2.6",
    )


def render_migration(payload: dict[str, Any]) -> str:
    lines = [
        "# Run287 P0-4 migration map",
        "",
        f"Frozen at `{payload['observed_at_utc']}` on `{payload['baseline_code_sha']}`.",
        "This is a read-only remediation plan; it grants no workflow dispatch, target/ledger write, promotion, production, or live authority.",
        "",
    ]
    priorities = ("P0", "P1", "P2")
    for priority in priorities:
        lines.extend([f"## {priority}", ""])
        for item in payload["migration_items"]:
            if item.get("priority") != priority:
                continue
            lines.extend(
                [
                    f"### {item['item_id']} — {item['title']}",
                    "",
                    f"- Current state: {item['current_state']}",
                    f"- Required change: {item['required_change']}",
                    f"- Acceptance evidence: {item['acceptance_evidence']}",
                    f"- Safety boundary: {item['safety_boundary']}",
                    f"- Depends on: {', '.join(item.get('depends_on') or ['none'])}",
                    "",
                ]
            )
    return "\n".join(lines).rstrip() + "\n"


def render_latest_map(payload: dict[str, Any]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for row in payload["latest_to_immutable"]:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return {
        "schema_version": "run287-p0-4-latest-map-v1",
        "market": "US",
        "baseline_code_sha": payload["baseline_code_sha"],
        "observed_at_utc": payload["observed_at_utc"],
        "source_snapshot_sha256": payload["_source_sha256"],
        "status_counts": dict(sorted(counts.items())),
        "mappings": payload["latest_to_immutable"],
    }


def render_readme(payload: dict[str, Any], row_count: int) -> str:
    health = payload["pipeline_health"]
    lines = [
        "# Run287 P0-4 artifact inventory",
        "",
        f"This is the read-only inventory required by Issue #372, frozen at `{payload['observed_at_utc']}` and bound to `master` `{payload['baseline_code_sha']}`.",
        "",
        "## Outcome",
        "",
        f"- Dataset classes: `{len(payload['datasets'])}`",
        f"- Model objects: `{len(payload['models'])}`",
        f"- Durable-state objects: `{len(payload['durable_states'])}`",
        f"- Infrastructure/artifact objects: `{len(payload['artifacts'])}`",
        f"- Total normalized Parquet rows: `{row_count}`",
        f"- Latest aliases verified: `{sum(1 for row in payload['latest_to_immutable'] if row['status'] == 'VERIFIED_IMMUTABLE')}`",
        f"- Latest aliases blocked: `{sum(1 for row in payload['latest_to_immutable'] if str(row['status']).startswith('BLOCKED_'))}`",
        "",
        "## Current pipeline connection",
        "",
        "```text",
        "SEC / earnings / free prices / macro collectors",
        "                    |",
        "                    v",
        "       Drive caches + mutable manifests",
        "                    |",
        "                    v",
        "         Data Readiness Preflight (green)",
        "                    |",
        "                    v",
        " Daily Operating Selection Refresh (BLOCKED)",
        "                    |",
        "       missing verified risk-outcome parent",
        "                    X",
        "  market snapshot -> target -> paper ledger -> accepted head",
        "```",
        "",
        f"The latest three operating runs `{', '.join(str(x) for x in health['daily_operating_recent_run_ids'])}` all failed at the same step: `{health['daily_operating_failed_step']}`. Collection, readiness, SEC, smart-money, crisis-monitor, and autolearning jobs were green in the latest observed runs; green sidecars do not clear this state-lineage blocker.",
        "",
        "## Highest-impact findings",
        "",
    ]
    for finding in payload["findings"]:
        lines.append(
            f"- **{finding['severity']} {finding['finding_id']}** — {finding['summary']}"
        )
    lines.extend(
        [
            "",
            "## Files",
            "",
            "- `dataset_registry.yaml`: data and feature classes, producer/consumer/PIT/hash contracts",
            "- `model_registry.yaml`: model binaries and metadata, including immutable-binding blockers",
            "- `artifact_registry.parquet`: normalized row for every registered object",
            "- `durable_state_registry.yaml`: accepted paper state, ledgers, state chains, and recovery procedures",
            "- `latest_to_immutable_map.yaml`: every discovered mutable alias is either verified or blocked",
            "- `migration_map.md`: ordered remediation without any mutation authority",
            "- `source_inventory_snapshot.json`: frozen GitHub/Drive/local evidence used for deterministic regeneration",
            "",
            "## Fail-closed limits",
            "",
        ]
    )
    for item in payload["discovery_limits"]:
        lines.append(f"- {item}")
    lines.extend(
        [
            "- No Drive upload/move/delete, local cleanup, workflow dispatch, fullrun, target/order/ledger mutation, champion change, production enablement, or live trading occurred.",
            "- A blank hash means it was not available from the bounded provider view; it is never interpreted as verified.",
            "",
            "## Rebuild",
            "",
            "```bash",
            "python -m venv .venv-p0-4",
            ".venv-p0-4/bin/python -m pip install --requirement docs/run287_p0_4_artifact_inventory/requirements.txt",
            ".venv-p0-4/bin/python tools/build_p0_4_artifact_inventory.py --verify-live-head",
            ".venv-p0-4/bin/python tests/test_p0_4_artifact_inventory.py",
            "```",
            "",
            "On Windows PowerShell, use `.\\.venv-p0-4\\Scripts\\python.exe` in place of `.venv-p0-4/bin/python`. The exact dependency pins are part of the frozen bundle.",
            "The protected-publication constant is verifier code: advancing it requires an explicit verifier diff and a new external exact-head Codex review plus the repository review-complete gate; regeneration alone grants no trust.",
            "",
        ]
    )
    return "\n".join(lines)


def render_summary(payload: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    mapping_counts: dict[str, int] = {}
    discovery_counts: dict[str, int] = {}
    for row in rows:
        mapping_counts[str(row["mapping_status"])] = mapping_counts.get(str(row["mapping_status"]), 0) + 1
        discovery_counts[str(row["discovery_status"])] = discovery_counts.get(str(row["discovery_status"]), 0) + 1
    return {
        "schema_version": "run287-p0-4-inventory-summary-v1",
        "market": "US",
        "baseline_code_sha": payload["baseline_code_sha"],
        "observed_at_utc": payload["observed_at_utc"],
        "source_snapshot_sha256": payload["_source_sha256"],
        "counts": {
            "datasets": len(payload["datasets"]),
            "models": len(payload["models"]),
            "durable_states": len(payload["durable_states"]),
            "artifacts": len(payload["artifacts"]),
            "artifact_registry_rows": len(rows),
        },
        "mapping_status_counts": dict(sorted(mapping_counts.items())),
        "discovery_status_counts": dict(sorted(discovery_counts.items())),
        "finding_ids": [row["finding_id"] for row in payload["findings"]],
        "pipeline_health": payload["pipeline_health"],
        "safety": payload["safety"],
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def verify_protected_publication_lineage(protected_commit: str) -> None:
    if not SHA1_RE.fullmatch(protected_commit):
        raise InventoryError("protected_publication_commit_invalid")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", protected_commit, "HEAD"],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    if ancestor.returncode != 0:
        raise InventoryError("protected_publication_is_not_live_head_ancestor")
    changed = subprocess.check_output(
        [
            "git",
            "diff",
            "--name-only",
            f"{protected_commit}..HEAD",
            "--",
            *PROTECTED_PUBLICATION_PATHS,
        ],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
    ).splitlines()
    if changed:
        raise InventoryError(
            "post_publication_protected_delta:" + ",".join(sorted(changed))
        )


def verify_live_publication_lineage(
    baseline: str, *, protected_commit: str | None = None
) -> None:
    baseline_ancestor = subprocess.run(
        [
            "git",
            "merge-base",
            "--is-ancestor",
            baseline,
            FROZEN_PUBLICATION_COMMIT,
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if baseline_ancestor.returncode != 0:
        raise InventoryError("frozen_baseline_is_not_publication_ancestor")
    publication_ancestor = subprocess.run(
        [
            "git",
            "merge-base",
            "--is-ancestor",
            FROZEN_PUBLICATION_COMMIT,
            "HEAD",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if publication_ancestor.returncode != 0:
        raise InventoryError("frozen_publication_is_not_live_head_ancestor")
    changed = subprocess.check_output(
        [
            "git",
            "diff",
            "--name-only",
            f"{baseline}..{FROZEN_PUBLICATION_COMMIT}",
        ],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
    ).splitlines()
    allowed_exact = {
        ".github/workflows/pr_validation.yml",
        "docs/AGENT_SHARED_LESSONS_LEDGER.md",
        "tests/test_p0_4_artifact_inventory.py",
        "tools/build_p0_4_artifact_inventory.py",
        "tools/run_pr_validation.py",
    }
    unexpected = sorted(
        path
        for path in changed
        if not path.startswith("docs/run287_p0_4_artifact_inventory/")
        and path not in allowed_exact
    )
    if unexpected:
        raise InventoryError(
            "live_head_has_nonpublication_delta:" + ",".join(unexpected)
        )
    for path, expected_sha256 in PINNED_PUBLICATION_FILE_SHA256.items():
        if path not in changed:
            continue
        actual = canonical_source_bytes(
            subprocess.check_output(
                ["git", "show", f"{FROZEN_PUBLICATION_COMMIT}:{path}"],
                cwd=ROOT,
            )
        )
        if hashlib.sha256(actual).hexdigest() != expected_sha256:
            raise InventoryError(f"pinned_publication_file_mismatch:{path}")
    if protected_commit is None:
        protected_commit = FROZEN_PROTECTED_PUBLICATION_COMMIT
    verify_protected_publication_lineage(protected_commit)
    require_clean_tracked_path(GENERATOR_PATH)


def require_clean_tracked_path(path: str) -> None:
    for cached, label in ((False, "worktree"), (True, "index")):
        command = ["git", "diff", "--quiet"]
        if cached:
            command.append("--cached")
        command.extend(["--", path])
        result = subprocess.run(
            command,
            cwd=ROOT,
            check=False,
            capture_output=True,
        )
        if result.returncode != 0:
            raise InventoryError(f"tracked_path_dirty:{label}:{path}")
    try:
        head_bytes = subprocess.check_output(
            ["git", "show", f"HEAD:{path}"],
            cwd=ROOT,
        )
        worktree_bytes = (ROOT / path).read_bytes()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise InventoryError(f"tracked_path_unavailable:{path}") from exc
    if canonical_source_bytes(worktree_bytes) != head_bytes:
        raise InventoryError(f"tracked_path_differs_from_head:{path}")


def render_bundle(
    staging: Path,
    payload: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    source_bytes: bytes,
    requirements_bytes: bytes,
) -> None:
    (staging / "source_inventory_snapshot.json").write_bytes(source_bytes)
    (staging / "requirements.txt").write_bytes(requirements_bytes)
    write_yaml(staging / "dataset_registry.yaml", registry_document(payload, "datasets"))
    write_yaml(staging / "model_registry.yaml", registry_document(payload, "models"))
    write_yaml(
        staging / "durable_state_registry.yaml",
        registry_document(payload, "durable_states"),
    )
    write_yaml(staging / "latest_to_immutable_map.yaml", render_latest_map(payload))
    write_parquet(staging / "artifact_registry.parquet", rows)
    (staging / "migration_map.md").write_text(
        render_migration(payload), encoding="utf-8", newline="\n"
    )
    (staging / "README.md").write_text(
        render_readme(payload, len(rows)), encoding="utf-8", newline="\n"
    )
    write_json(staging / "summary.json", render_summary(payload, rows))


def publish_bundle_atomically(output: Path, render) -> None:
    if output.is_symlink():
        raise InventoryError("output_directory_symlink_rejected")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.stage-", dir=str(output.parent))
    )
    backup: Path | None = None
    try:
        if output.exists():
            if not output.is_dir():
                raise InventoryError("output_path_not_directory")
            shutil.copytree(output, staging, dirs_exist_ok=True, symlinks=True)
        linked = sorted(
            name for name in BUNDLE_FILENAMES if (staging / name).is_symlink()
        )
        if linked:
            raise InventoryError("staged_bundle_symlink:" + ",".join(linked))
        render(staging)
        missing = sorted(name for name in BUNDLE_FILENAMES if not (staging / name).is_file())
        if missing:
            raise InventoryError("staged_bundle_incomplete:" + ",".join(missing))
        if output.exists():
            backup = output.parent / f".{output.name}.backup-{uuid.uuid4().hex}"
            os.replace(output, backup)
        try:
            os.replace(staging, output)
        except Exception:
            if backup is not None and backup.exists() and not output.exists():
                os.replace(backup, output)
                backup = None
            raise
        if backup is not None:
            shutil.rmtree(backup)
            backup = None
    finally:
        if staging.exists():
            shutil.rmtree(staging)
        if backup is not None and backup.exists() and not output.exists():
            os.replace(backup, output)


def build(source: Path, output: Path, *, verify_live_head: bool = False) -> None:
    source_bytes = canonical_source_bytes(source.read_bytes())
    is_canonical_source = source.resolve() == DEFAULT_SOURCE.resolve()
    is_canonical_output = output.resolve() == DEFAULT_OUTPUT.resolve()
    if is_canonical_output and not is_canonical_source:
        raise InventoryError("canonical_output_requires_canonical_source")
    if is_canonical_source:
        verify_frozen_source_publication(source_bytes)
    elif verify_live_head:
        raise InventoryError("verify_live_head_requires_canonical_source")
    payload = read_source(source)
    payload["_source_sha256"] = hashlib.sha256(source_bytes).hexdigest()
    validate_source(payload)
    if verify_live_head:
        verify_live_publication_lineage(payload["baseline_code_sha"])
    rows = artifact_rows(
        payload,
        source_publication_commit=(
            FROZEN_SOURCE_PUBLICATION_COMMIT
            if is_canonical_source
            else UNBOUND_SOURCE_PUBLICATION
        ),
    )
    requirements_bytes = canonical_source_bytes(
        (DEFAULT_OUTPUT / "requirements.txt").read_bytes()
    )
    publish_bundle_atomically(
        output,
        lambda staging: render_bundle(
            staging,
            payload,
            rows,
            source_bytes=source_bytes,
            requirements_bytes=requirements_bytes,
        ),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--verify-live-head", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    build(args.source.resolve(), args.output_dir.resolve(), verify_live_head=args.verify_live_head)
    print(f"[p0-4-inventory] wrote {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
