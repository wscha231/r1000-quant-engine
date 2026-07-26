#!/usr/bin/env python3
"""Freeze the restored Run287 risk-outcome parent before any resolver mutation.

The anchor is deliberately small.  It binds the exact restored summary and
event-log prefix, carries any legacy/unanchored prefix quarantine forward, and
never authorizes portfolio, order, target, production, or live mutations.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
ANCHOR_SCHEMA_VERSION = "run287-risk-outcome-parent-anchor-v1"
OUTCOME_CHAIN_SCHEMA_VERSION = "run287-risk-outcome-chain-v1"
ACCEPTED_MANIFEST_SCHEMA_VERSION = (
    "run287-accepted-publication-manifest-v1"
)
ACCEPTED_MANIFEST_READY_STATUS = (
    "READY_ACCEPTED_PUBLICATION_REVIEW_ONLY"
)
OUTCOME_ARCHIVE_SCHEMA_VERSION = "run287-risk-outcome-archive-v1"
PUBLISHABLE_OUTCOME_STATUSES = {
    "READY_RISK_OUTCOME_ARCHIVE_REVIEW_ONLY",
    "SKIPPED_NO_DECISION_OBSERVATIONS",
}
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
ANCHOR_STATUSES = {
    "GENESIS_EMPTY",
    "VERIFIED_EMPTY_PARENT",
    "VERIFIED_PARENT",
}
PARENT_ACCEPTANCE_STATUSES = {
    "NO_PRIOR_STATE",
    "VERIFIED_ACCEPTED_HEAD",
    "QUARANTINED_LEGACY",
}
ACCEPTED_MANIFEST_FALSE_SAFETY_FLAGS = (
    "automatic_champion_replacement_allowed",
    "production_activation_allowed",
    "live_trading_enabled",
    "fullrun_executed",
)
FALSE_SAFETY_FLAGS = (
    "mechanism_promotion_allowed",
    "threshold_tuning_allowed",
    "stop_or_exit_rule_created",
    "selector_weights_changed",
    "cash_policy_changed",
    "portfolio_transition_allowed",
    "orders_generated",
    "target_books_mutated",
    "historical_cagr_mdd_evidence_changed",
    "backtest_executed",
    "fullrun_executed",
    "production_activation_allowed",
    "live_trading_enabled",
)
ALLOWED_EVENT_TYPES = {
    "risk_signal_observed",
    "forward_outcome_observed",
}
LEGACY_SAFETY_MIGRATION_SCHEMA_VERSION = (
    "run287-known-legacy-safety-migration-v1"
)
KNOWN_LEGACY_SAFETY_MIGRATIONS: dict[str, dict[str, Any]] = {
    # Restored in workflow run 30146363501.  The byte hash is intentionally
    # the primary allowlist key: a semantically similar or reformatted
    # summary must remain fail-closed.
    "5a57e4becef19668dce45803eb77185bc6c60bcf9b58522df939e9a48a56654c": {
        "evidence_workflow_run_id": "30146363501",
        "as_of_date": "2026-07-17",
        "status": "SKIPPED_NO_DECISION_OBSERVATIONS",
        "missing_false_fields": (
            "mechanism_promotion_allowed",
            "threshold_tuning_allowed",
            "stop_or_exit_rule_created",
            "selector_weights_changed",
            "cash_policy_changed",
            "backtest_executed",
        ),
    },
}


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def strict_json_object(
    payload: str | bytes,
    *,
    label: str,
) -> dict[str, Any]:
    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label}_duplicate_json_key:{key}")
            result[key] = value
        return result

    try:
        decoded = json.loads(payload, object_pairs_hook=object_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label}_invalid_json") from exc
    if not isinstance(decoded, dict):
        raise ValueError(f"{label}_not_json_object")
    return decoded


def read_json_object(path: Path) -> dict[str, Any]:
    return strict_json_object(
        path.read_text(encoding="utf-8"),
        label=f"risk_outcome_parent:{path}",
    )


def event_log_metadata(payload: bytes, *, label: str) -> tuple[str, int, int]:
    """Return SHA, bytes, and strict nonblank JSON-object line count."""
    if not payload:
        return EMPTY_SHA256, 0, 0
    count = 0
    seen_event_ids: set[str] = set()
    for line_number, raw in enumerate(payload.splitlines(), start=1):
        if not raw.strip():
            raise ValueError(f"{label}_blank_jsonl_row:{line_number}")
        try:
            row = strict_json_object(
                raw,
                label=f"{label}_jsonl_row:{line_number}",
            )
        except ValueError as exc:
            raise ValueError(
                f"{label}_invalid_jsonl_row:{line_number}"
            ) from exc
        event_id = row.get("event_id")
        if not isinstance(event_id, str) or not event_id.strip():
            raise ValueError(f"{label}_missing_event_id:{line_number}")
        if event_id in seen_event_ids:
            raise ValueError(
                f"{label}_duplicate_event_id:{line_number}:{event_id}"
            )
        seen_event_ids.add(event_id)
        if row.get("event_type") not in ALLOWED_EVENT_TYPES:
            raise ValueError(f"{label}_invalid_event_type:{line_number}")
        count += 1
    return sha256_bytes(payload), len(payload), count


def _integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label}_invalid")
    return value


def _require_safe(
    payload: dict[str, Any],
    label: str,
    *,
    raw_summary_sha256: str,
    allow_quarantined_legacy_parent: bool,
) -> dict[str, Any] | None:
    if payload.get("review_only") is not True:
        raise ValueError(f"{label}_not_review_only")
    for field in FALSE_SAFETY_FLAGS:
        if field in payload and payload[field] is not False:
            raise ValueError(f"{label}_{field}_not_false")

    missing_fields = tuple(
        field for field in FALSE_SAFETY_FLAGS if field not in payload
    )
    if not missing_fields:
        return None

    migration = KNOWN_LEGACY_SAFETY_MIGRATIONS.get(
        raw_summary_sha256.lower()
    )
    expected_missing = (
        tuple(migration["missing_false_fields"])
        if migration is not None
        else ()
    )
    migration_matches = bool(
        allow_quarantined_legacy_parent
        and migration is not None
        and missing_fields == expected_missing
        and payload.get("as_of_date") == migration["as_of_date"]
        and payload.get("status") == migration["status"]
    )
    if not migration_matches:
        # Preserve the ordinary fail-closed error contract.  The explicit
        # quarantine flag alone never supplies defaults for an unknown
        # summary.
        raise ValueError(f"{label}_{missing_fields[0]}_not_false")

    for field in missing_fields:
        payload[field] = False
    return {
        "schema_version": LEGACY_SAFETY_MIGRATION_SCHEMA_VERSION,
        "evidence_workflow_run_id": migration[
            "evidence_workflow_run_id"
        ],
        "source_summary_sha256": raw_summary_sha256.lower(),
        "source_as_of_date": migration["as_of_date"],
        "source_status": migration["status"],
        "materialized_false_fields": list(missing_fields),
        "explicit_legacy_quarantine_authorization_required": True,
        "raw_parent_summary_bytes_preserved": True,
    }


def _validate_as_of(value: Any, label: str) -> str:
    text = str(value or "")
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"{label}_invalid") from exc
    if parsed.strftime("%Y-%m-%d") != text:
        raise ValueError(f"{label}_invalid")
    return text


def _valid_hash(value: Any, length: int) -> bool:
    text = str(value or "").lower()
    return len(text) == length and all(
        character in "0123456789abcdef" for character in text
    )


def _accepted_file_sha256(
    manifest: Mapping[str, Any],
    *,
    label: str,
    expected_path: str,
) -> str:
    files = manifest.get("files")
    record = files.get(label) if isinstance(files, dict) else None
    if (
        not isinstance(record, dict)
        or record.get("path") != expected_path
        or not _valid_hash(record.get("sha256"), 64)
    ):
        raise ValueError(
            f"parent_accepted_manifest_file_record_invalid:{label}"
        )
    return str(record["sha256"]).lower()


def _verify_parent_accepted_manifest(
    *,
    manifest_path: Path,
    expected_sha256: str,
    summary: Mapping[str, Any],
    summary_sha256: str,
    summary_bytes: int,
    event_log_sha256: str,
    event_count: int,
    parent_as_of_date: str,
) -> tuple[str, int, str]:
    if not _valid_hash(expected_sha256, 64):
        raise ValueError(
            "parent_accepted_manifest_expected_sha256_invalid"
        )
    manifest_bytes = manifest_path.read_bytes()
    manifest_sha256 = sha256_bytes(manifest_bytes)
    if manifest_sha256 != expected_sha256.lower():
        raise ValueError("parent_accepted_manifest_sha256_mismatch")
    manifest = strict_json_object(
        manifest_bytes,
        label="parent_accepted_manifest",
    )
    if (
        manifest.get("schema_version")
        != ACCEPTED_MANIFEST_SCHEMA_VERSION
        or manifest.get("status") != ACCEPTED_MANIFEST_READY_STATUS
        or manifest.get("review_only") is not True
    ):
        raise ValueError("parent_accepted_manifest_contract_invalid")
    for field in ACCEPTED_MANIFEST_FALSE_SAFETY_FLAGS:
        if manifest.get(field) is not False:
            raise ValueError(
                f"parent_accepted_manifest_{field}_not_false"
            )
    manifest_as_of = _validate_as_of(
        manifest.get("as_of_date"),
        "parent_accepted_manifest_as_of_date",
    )
    if manifest_as_of != parent_as_of_date:
        raise ValueError("parent_accepted_manifest_as_of_date_mismatch")
    if manifest.get("outcome_status") != summary.get("status"):
        raise ValueError("parent_accepted_manifest_outcome_status_mismatch")
    if (
        summary.get("schema_version") != OUTCOME_ARCHIVE_SCHEMA_VERSION
        or summary.get("status") not in PUBLISHABLE_OUTCOME_STATUSES
        or summary.get("blockers") != []
    ):
        raise ValueError(
            "parent_accepted_manifest_outcome_summary_contract_invalid"
        )
    if manifest.get("outcome_chain") != summary.get("outcome_chain"):
        raise ValueError("parent_accepted_manifest_outcome_chain_mismatch")
    outcome_chain = summary.get("outcome_chain")
    if (
        not isinstance(outcome_chain, dict)
        or outcome_chain.get("schema_version")
        != OUTCOME_CHAIN_SCHEMA_VERSION
        or outcome_chain.get("status") != "VERIFIED_APPEND_ONLY"
        or outcome_chain.get("exact_parent_prefix_verified") is not True
        or outcome_chain.get("append_only_verified") is not True
        or outcome_chain.get("current_event_log_sha256")
        != event_log_sha256
        or outcome_chain.get("current_event_count") != event_count
        or outcome_chain.get("current_as_of_date")
        != parent_as_of_date
    ):
        raise ValueError(
            "parent_accepted_manifest_outcome_chain_unverified"
        )

    source_identity = manifest.get("source_identity")
    if (
        not isinstance(source_identity, dict)
        or not _valid_hash(source_identity.get("commit_sha"), 40)
        or not str(source_identity.get("workflow") or "").strip()
        or not str(source_identity.get("run_id") or "").strip()
        or not str(source_identity.get("run_attempt") or "").strip()
        or not _valid_hash(
            source_identity.get("promotion_gate_sha256"),
            64,
        )
    ):
        raise ValueError(
            "parent_accepted_manifest_source_identity_invalid"
        )
    if (
        _accepted_file_sha256(
            manifest,
            label="promotion_gate",
            expected_path="run287_promotion_gate/promotion_gate.json",
        )
        != str(source_identity["promotion_gate_sha256"]).lower()
    ):
        raise ValueError(
            "parent_accepted_manifest_promotion_gate_binding_invalid"
        )
    paper_snapshot = manifest.get("paper_snapshot")
    previous_snapshot_hash = str(
        (paper_snapshot or {}).get("previous_snapshot_hash") or ""
    )
    ancestor_snapshot_hashes = (
        (paper_snapshot or {}).get("ancestor_snapshot_hashes")
    )
    if (
        not isinstance(paper_snapshot, dict)
        or not _valid_hash(paper_snapshot.get("snapshot_hash"), 64)
        or not _valid_hash(
            paper_snapshot.get("genesis_identity_sha256"),
            64,
        )
        or (
            previous_snapshot_hash
            and not _valid_hash(
                previous_snapshot_hash,
                64,
            )
        )
        or not isinstance(ancestor_snapshot_hashes, list)
        or any(
            not _valid_hash(value, 64)
            for value in ancestor_snapshot_hashes
        )
        or len(set(ancestor_snapshot_hashes))
        != len(ancestor_snapshot_hashes)
        or (
            previous_snapshot_hash
            and (
                not ancestor_snapshot_hashes
                or ancestor_snapshot_hashes[0]
                != previous_snapshot_hash
            )
        )
        or (
            not previous_snapshot_hash
            and ancestor_snapshot_hashes
        )
        or paper_snapshot.get("snapshot_hash")
        in ancestor_snapshot_hashes
        or _integer(
            paper_snapshot.get("file_count"),
            "parent_accepted_manifest_paper_file_count",
        )
        <= 0
        or paper_snapshot.get("transaction_mode")
        not in {"MARK_ONLY", "SELECTED_TARGET"}
    ):
        raise ValueError(
            "parent_accepted_manifest_paper_snapshot_invalid"
        )
    if (
        _accepted_file_sha256(
            manifest,
            label="risk_outcome_summary",
            expected_path="run287_risk_outcome_archive/summary.json",
        )
        != summary_sha256
    ):
        raise ValueError(
            "parent_accepted_manifest_summary_sha256_mismatch"
        )
    summary_record = (manifest.get("files") or {}).get(
        "risk_outcome_summary"
    )
    if (
        not isinstance(summary_record, dict)
        or _integer(
            summary_record.get("bytes"),
            "parent_accepted_manifest_summary_bytes",
        )
        != summary_bytes
    ):
        raise ValueError(
            "parent_accepted_manifest_summary_bytes_mismatch"
        )
    files = manifest.get("files")
    event_record = (
        files.get("risk_outcome_event_log")
        if isinstance(files, dict)
        else None
    )
    if event_count:
        if (
            _accepted_file_sha256(
                manifest,
                label="risk_outcome_event_log",
                expected_path=(
                    "run287_risk_outcome_archive/"
                    "risk_outcome_events.jsonl"
                ),
            )
            != event_log_sha256
        ):
            raise ValueError(
                "parent_accepted_manifest_event_log_sha256_mismatch"
            )
    elif event_record is not None:
        if (
            _accepted_file_sha256(
                manifest,
                label="risk_outcome_event_log",
                expected_path=(
                    "run287_risk_outcome_archive/"
                    "risk_outcome_events.jsonl"
                ),
            )
            != EMPTY_SHA256
        ):
            raise ValueError(
                "parent_accepted_manifest_empty_event_log_mismatch"
            )
    return manifest_sha256, len(manifest_bytes), manifest_as_of


def _carried_quarantine(
    summary: Mapping[str, Any],
    *,
    event_sha256: str,
    event_bytes: int,
    event_count: int,
) -> int:
    chain = summary.get("outcome_chain")
    if chain is None:
        return event_count
    if not isinstance(chain, dict):
        raise ValueError("parent_outcome_chain_invalid")
    if chain.get("schema_version") != OUTCOME_CHAIN_SCHEMA_VERSION:
        raise ValueError("parent_outcome_chain_schema_invalid")
    status = str(chain.get("status") or "")
    if status != "VERIFIED_APPEND_ONLY":
        # A previously unanchored or blocked chain is never retroactively
        # trusted merely because its bytes were restored.
        if status in {"UNANCHORED", "BLOCKED_PARENT_ANCHOR"}:
            return event_count
        raise ValueError("parent_outcome_chain_status_invalid")
    if (
        chain.get("exact_parent_prefix_verified") is not True
        or chain.get("append_only_verified") is not True
    ):
        raise ValueError("parent_outcome_chain_not_verified")
    expected = {
        "current_event_log_sha256": event_sha256,
        "current_event_log_bytes": event_bytes,
        "current_event_count": event_count,
    }
    for field, value in expected.items():
        if chain.get(field) != value:
            raise ValueError(f"parent_outcome_chain_{field}_mismatch")
    carried = _integer(
        chain.get("carried_quarantined_prefix_event_count"),
        "parent_outcome_chain_carried_quarantined_prefix_event_count",
    )
    if carried > event_count:
        raise ValueError("parent_outcome_chain_quarantine_exceeds_event_count")
    trusted = _integer(
        chain.get("trusted_event_count"),
        "parent_outcome_chain_trusted_event_count",
    )
    if trusted != event_count - carried:
        raise ValueError("parent_outcome_chain_trusted_event_count_mismatch")
    return carried


def build_anchor(
    summary_path: str | Path,
    event_log_path: str | Path,
    *,
    parent_accepted_manifest_path: str | Path | None = None,
    expected_parent_accepted_manifest_sha256: str = "",
    allow_quarantined_legacy_parent: bool = False,
    now_utc: str | None = None,
) -> dict[str, Any]:
    summary_file = repo_path(summary_path)
    event_file = repo_path(event_log_path)
    summary_exists = summary_file.is_file()
    event_exists = event_file.is_file()
    manifest_value = str(parent_accepted_manifest_path or "").strip()
    expected_manifest_sha256 = str(
        expected_parent_accepted_manifest_sha256 or ""
    ).strip().lower()
    if bool(manifest_value) != bool(expected_manifest_sha256):
        raise ValueError(
            "parent_accepted_manifest_path_and_sha256_must_be_paired"
        )

    if not summary_exists and event_exists:
        raise ValueError("risk_outcome_parent_partial_event_log_without_summary")

    generated_at = now_utc or utc_now()
    if not summary_exists:
        status = "GENESIS_EMPTY"
        summary_payload: dict[str, Any] = {}
        summary_bytes = b""
        legacy_safety_migration: dict[str, Any] | None = None
        event_bytes = b""
        event_sha256, event_size, event_count = EMPTY_SHA256, 0, 0
        parent_as_of_date = ""
        carried = 0
        parent_acceptance_status = "NO_PRIOR_STATE"
        parent_accepted_manifest_sha256 = ""
        parent_accepted_manifest_bytes = 0
        parent_accepted_manifest_as_of_date = ""
        if manifest_value:
            raise ValueError(
                "parent_accepted_manifest_present_without_parent_state"
            )
    else:
        summary_bytes = summary_file.read_bytes()
        summary_sha256 = sha256_bytes(summary_bytes)
        summary_payload = read_json_object(summary_file)
        if (
            summary_payload.get("schema_version")
            != OUTCOME_ARCHIVE_SCHEMA_VERSION
        ):
            raise ValueError("risk_outcome_parent_summary_schema_invalid")
        legacy_safety_migration = _require_safe(
            summary_payload,
            "risk_outcome_parent_summary",
            raw_summary_sha256=summary_sha256,
            allow_quarantined_legacy_parent=(
                allow_quarantined_legacy_parent
            ),
        )
        parent_as_of_date = _validate_as_of(
            summary_payload.get("as_of_date"),
            "risk_outcome_parent_as_of_date",
        )
        event_bytes = event_file.read_bytes() if event_exists else b""
        event_sha256, event_size, event_count = event_log_metadata(
            event_bytes,
            label="risk_outcome_parent_event_log",
        )
        if event_bytes and not event_bytes.endswith(b"\n"):
            raise ValueError(
                "risk_outcome_parent_event_log_missing_final_newline"
            )
        signal_count = _integer(
            summary_payload.get("signal_observation_count", 0),
            "risk_outcome_parent_signal_observation_count",
        )
        outcome_count = _integer(
            summary_payload.get("forward_outcome_event_count", 0),
            "risk_outcome_parent_forward_outcome_event_count",
        )
        if signal_count + outcome_count != event_count:
            raise ValueError("risk_outcome_parent_event_count_mismatch")
        declared_hash = str(
            (summary_payload.get("outputs") or {}).get("event_log_sha256") or ""
        )
        if event_count:
            if not event_exists:
                raise ValueError("risk_outcome_parent_event_log_missing")
            if declared_hash != event_sha256:
                raise ValueError("risk_outcome_parent_event_log_sha256_mismatch")
            status = "VERIFIED_PARENT"
        else:
            if declared_hash not in {"", EMPTY_SHA256}:
                raise ValueError(
                    "risk_outcome_empty_parent_event_log_sha256_mismatch"
                )
            status = "VERIFIED_EMPTY_PARENT"
        if manifest_value:
            if allow_quarantined_legacy_parent:
                raise ValueError(
                    "legacy_parent_override_conflicts_with_accepted_manifest"
                )
            manifest_path = repo_path(manifest_value)
            if not manifest_path.is_file():
                raise ValueError("parent_accepted_manifest_missing")
            (
                parent_accepted_manifest_sha256,
                parent_accepted_manifest_bytes,
                parent_accepted_manifest_as_of_date,
            ) = _verify_parent_accepted_manifest(
                manifest_path=manifest_path,
                expected_sha256=expected_manifest_sha256,
                summary=summary_payload,
                summary_sha256=summary_sha256,
                summary_bytes=len(summary_bytes),
                event_log_sha256=event_sha256,
                event_count=event_count,
                parent_as_of_date=parent_as_of_date,
            )
            parent_acceptance_status = "VERIFIED_ACCEPTED_HEAD"
            carried = _carried_quarantine(
                summary_payload,
                event_sha256=event_sha256,
                event_bytes=event_size,
                event_count=event_count,
            )
        elif allow_quarantined_legacy_parent:
            parent_acceptance_status = "QUARANTINED_LEGACY"
            parent_accepted_manifest_sha256 = ""
            parent_accepted_manifest_bytes = 0
            parent_accepted_manifest_as_of_date = ""
            carried = event_count
        else:
            raise ValueError(
                "parent_accepted_manifest_required_for_existing_state"
            )

    anchor: dict[str, Any] = {
        "schema_version": ANCHOR_SCHEMA_VERSION,
        "status": status,
        "generated_at_utc": generated_at,
        "parent_summary_sha256": (
            sha256_bytes(summary_bytes) if summary_bytes else ""
        ),
        "parent_summary_bytes": len(summary_bytes),
        "parent_event_log_sha256": event_sha256,
        "parent_event_log_bytes": event_size,
        "parent_event_count": event_count,
        "parent_as_of_date": parent_as_of_date,
        "carried_quarantined_prefix_event_count": carried,
        "parent_acceptance_status": parent_acceptance_status,
        "parent_accepted_manifest_sha256": (
            parent_accepted_manifest_sha256
        ),
        "parent_accepted_manifest_bytes": (
            parent_accepted_manifest_bytes
        ),
        "parent_accepted_manifest_as_of_date": (
            parent_accepted_manifest_as_of_date
        ),
        "review_only": True,
    }
    anchor.update({field: False for field in FALSE_SAFETY_FLAGS})
    if legacy_safety_migration is not None:
        anchor["legacy_safety_migration"] = legacy_safety_migration
    return anchor


def write_anchor(path: str | Path, payload: Mapping[str, Any]) -> None:
    output = repo_path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            dict(payload),
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--summary",
        default="outputs/run287_risk_outcome_archive/summary.json",
    )
    parser.add_argument(
        "--event-log",
        default=(
            "outputs/run287_risk_outcome_archive/"
            "risk_outcome_events.jsonl"
        ),
    )
    parser.add_argument(
        "--output",
        default="outputs/run287_risk_outcome_parent_anchor/anchor.json",
    )
    parser.add_argument(
        "--parent-accepted-manifest",
        default="",
        help=(
            "immutable prior accepted-publication manifest that binds the "
            "restored outcome summary and event log"
        ),
    )
    parser.add_argument(
        "--expected-parent-accepted-manifest-sha256",
        default="",
        help=(
            "trusted immutable-head SHA-256 for --parent-accepted-manifest"
        ),
    )
    parser.add_argument(
        "--allow-quarantined-legacy-parent",
        action="store_true",
        help=(
            "one-time migration only: retain an unattested existing prefix "
            "but quarantine every prior event from promotion evidence"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    anchor = build_anchor(
        args.summary,
        args.event_log,
        parent_accepted_manifest_path=(
            args.parent_accepted_manifest or None
        ),
        expected_parent_accepted_manifest_sha256=(
            args.expected_parent_accepted_manifest_sha256
        ),
        allow_quarantined_legacy_parent=(
            args.allow_quarantined_legacy_parent
        ),
    )
    write_anchor(args.output, anchor)
    print(json.dumps(anchor, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
