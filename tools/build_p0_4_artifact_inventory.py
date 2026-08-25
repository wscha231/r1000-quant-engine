#!/usr/bin/env python3
"""Build the frozen, read-only Run287 P0-4 artifact inventory.

The collector inputs are intentionally frozen in the repository.  This tool
does not contact GitHub or Google Drive and never writes outside the requested
output directory.  Live enumeration is a separate, bounded evidence-gathering
step; incomplete provider views must be recorded as blocked in the source
snapshot rather than silently refreshed here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "docs" / "run287_p0_4_artifact_inventory" / "source_inventory_snapshot.json"
DEFAULT_OUTPUT = ROOT / "docs" / "run287_p0_4_artifact_inventory"
SCHEMA_VERSION = "run287-p0-4-inventory-source-v1"
REGISTRY_SCHEMA_VERSION = "run287-p0-4-registry-v1"
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
]


class InventoryError(ValueError):
    """Stable fail-closed inventory validation error."""


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
    blocked = str(row.get("mapping_status")).startswith("BLOCKED_")
    if blocked and not row.get("blockers"):
        raise InventoryError(f"blocked_without_reason:{object_id}")
    if row.get("mutable_alias") and not (
        row.get("immutable_location") or blocked
    ):
        raise InventoryError(f"mutable_alias_not_bound_or_blocked:{object_id}")


def validate_source(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise InventoryError("source_schema_version")
    if payload.get("market") != "US":
        raise InventoryError("source_market")
    baseline = str(payload.get("baseline_code_sha") or "")
    if not SHA1_RE.fullmatch(baseline):
        raise InventoryError("baseline_code_sha")
    if payload.get("safety", {}).get("mutations_performed") != []:
        raise InventoryError("source_claims_mutations")
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
        if row.get("status") not in ALIAS_STATUSES:
            raise InventoryError(f"latest_map_status:{object_id}")
        if str(row.get("status")).startswith("BLOCKED_") and not row.get("blockers"):
            raise InventoryError(f"latest_map_blocked_without_reason:{object_id}")
    mutable_ids = {
        row["object_id"]
        for collection in ("datasets", "models", "durable_states", "artifacts")
        for row in payload[collection]
        if row.get("mutable_alias")
    }
    missing_aliases = sorted(mutable_ids - alias_ids)
    if missing_aliases:
        raise InventoryError("latest_map_missing_aliases:" + ",".join(missing_aliases))
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


def artifact_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
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
            "python tools/build_p0_4_artifact_inventory.py",
            "pytest -q tests/test_p0_4_artifact_inventory.py",
            "```",
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


def verify_live_publication_lineage(baseline: str) -> None:
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", baseline, "HEAD"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if ancestor.returncode != 0:
        raise InventoryError("frozen_baseline_is_not_live_head_ancestor")
    changed = subprocess.check_output(
        ["git", "diff", "--name-only", f"{baseline}..HEAD"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
    ).splitlines()
    allowed_exact = {
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


def build(source: Path, output: Path, *, verify_live_head: bool = False) -> None:
    source_bytes = source.read_bytes()
    payload = read_source(source)
    payload["_source_sha256"] = hashlib.sha256(source_bytes).hexdigest()
    validate_source(payload)
    if verify_live_head:
        verify_live_publication_lineage(payload["baseline_code_sha"])
    output.mkdir(parents=True, exist_ok=True)
    rows = artifact_rows(payload)
    write_yaml(output / "dataset_registry.yaml", registry_document(payload, "datasets"))
    write_yaml(output / "model_registry.yaml", registry_document(payload, "models"))
    write_yaml(
        output / "durable_state_registry.yaml",
        registry_document(payload, "durable_states"),
    )
    write_yaml(output / "latest_to_immutable_map.yaml", render_latest_map(payload))
    write_parquet(output / "artifact_registry.parquet", rows)
    (output / "migration_map.md").write_text(
        render_migration(payload), encoding="utf-8", newline="\n"
    )
    (output / "README.md").write_text(
        render_readme(payload, len(rows)), encoding="utf-8", newline="\n"
    )
    write_json(output / "summary.json", render_summary(payload, rows))


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
