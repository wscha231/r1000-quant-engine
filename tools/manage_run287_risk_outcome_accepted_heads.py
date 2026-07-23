#!/usr/bin/env python3
"""Select, verify, and stage immutable Run287 risk-outcome accepted heads."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
ACCEPTED_MANIFEST_SCHEMA = "run287-accepted-publication-manifest-v1"
ACCEPTED_MANIFEST_STATUS = "READY_ACCEPTED_PUBLICATION_REVIEW_ONLY"
OUTCOME_ARCHIVE_SCHEMA = "run287-risk-outcome-archive-v1"
OUTCOME_CHAIN_SCHEMA = "run287-risk-outcome-chain-v1"
SELECTION_SCHEMA = "run287-risk-outcome-accepted-head-selection-v1"
VERIFY_SCHEMA = "run287-risk-outcome-accepted-head-verification-v1"
STAGE_SCHEMA = "run287-risk-outcome-accepted-head-stage-v1"
SELECTION_STATUS = "VERIFIED_LINEAR_ACCEPTED_HEAD_SELECTED"
VERIFY_STATUS = "VERIFIED_ACCEPTED_HEAD"
ROOT_ACCEPTANCE_STATUSES = {"NO_PRIOR_STATE", "QUARANTINED_LEGACY"}
CHILD_ACCEPTANCE_STATUS = "VERIFIED_ACCEPTED_HEAD"
PUBLISHABLE_OUTCOME_STATUSES = {
    "READY_RISK_OUTCOME_ARCHIVE_REVIEW_ONLY",
    "SKIPPED_NO_DECISION_OBSERVATIONS",
}
PAPER_TRANSACTION_MODES = {"MARK_ONLY", "SELECTED_TARGET"}
OUTCOME_PARENT_STATUSES = {
    "GENESIS_EMPTY",
    "VERIFIED_EMPTY_PARENT",
    "VERIFIED_PARENT",
}
OUTCOME_EVENT_TYPES = {
    "risk_signal_observed",
    "forward_outcome_observed",
}
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
HEX_40 = re.compile(r"^[0-9a-f]{40}$")
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
SUMMARY_RELATIVE_PATH = Path("run287_risk_outcome_archive/summary.json")
EVENT_LOG_RELATIVE_PATH = Path(
    "run287_risk_outcome_archive/risk_outcome_events.jsonl"
)
PROMOTION_GATE_RELATIVE_PATH = Path(
    "run287_promotion_gate/promotion_gate.json"
)
MANIFEST_RELATIVE_PATH = Path("manifest.json")
MANIFEST_FALSE_SAFETY_FIELDS = (
    "automatic_champion_replacement_allowed",
    "production_activation_allowed",
    "live_trading_enabled",
    "fullrun_executed",
)
OUTCOME_FALSE_SAFETY_FIELDS = (
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
def _repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _valid_sha256(value: Any) -> bool:
    return isinstance(value, str) and HEX_64.fullmatch(value) is not None


def _valid_commit_sha(value: Any) -> bool:
    return isinstance(value, str) and HEX_40.fullmatch(value) is not None


def _valid_date(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return parsed.strftime("%Y-%m-%d") == value


def _json_object_no_duplicates(path: Path) -> dict[str, Any]:
    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate_json_key:{path}:{key}")
            result[key] = value
        return result

    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=object_pairs,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid_json:{path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"json_object_required:{path}")
    return payload


def _integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label}_invalid")
    return value


def _require_regular_file(path: Path, label: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label}_missing_or_not_regular:{path}")


def _require_false_fields(
    payload: Mapping[str, Any],
    fields: tuple[str, ...],
    label: str,
) -> None:
    for field in fields:
        if payload.get(field) is not False:
            raise ValueError(f"{label}_unsafe_flag:{field}")


def _validate_paper_snapshot(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("accepted_head_paper_snapshot_invalid")
    snapshot_hash = payload.get("snapshot_hash")
    genesis_identity_sha256 = payload.get("genesis_identity_sha256")
    previous_snapshot_hash = payload.get("previous_snapshot_hash")
    ancestor_snapshot_hashes = payload.get("ancestor_snapshot_hashes")
    file_count = _integer(
        payload.get("file_count"),
        "accepted_head_paper_snapshot_file_count",
    )
    if (
        not _valid_sha256(snapshot_hash)
        or not _valid_sha256(genesis_identity_sha256)
        or (
            previous_snapshot_hash != ""
            and not _valid_sha256(previous_snapshot_hash)
        )
        or not isinstance(ancestor_snapshot_hashes, list)
        or any(
            not _valid_sha256(value)
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
        or snapshot_hash in ancestor_snapshot_hashes
        or file_count <= 0
        or payload.get("transaction_mode") not in PAPER_TRANSACTION_MODES
    ):
        raise ValueError("accepted_head_paper_snapshot_invalid")
    return dict(payload)


def _validate_outcome_chain(
    payload: Any,
    *,
    accepted_manifest_sha256: str,
    accepted_as_of_date: str,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("accepted_head_outcome_chain_invalid")
    if (
        payload.get("schema_version") != OUTCOME_CHAIN_SCHEMA
        or payload.get("status") != "VERIFIED_APPEND_ONLY"
        or payload.get("exact_parent_prefix_verified") is not True
        or payload.get("append_only_verified") is not True
        or payload.get("current_as_of_date") != accepted_as_of_date
        or payload.get("parent_anchor_status") not in OUTCOME_PARENT_STATUSES
        or not _valid_sha256(payload.get("parent_anchor_sha256"))
        or not _valid_sha256(payload.get("parent_event_log_sha256"))
        or not _valid_sha256(payload.get("current_event_log_sha256"))
    ):
        raise ValueError("accepted_head_outcome_chain_invalid")

    parent_bytes = _integer(
        payload.get("parent_event_log_bytes"),
        "accepted_head_parent_event_log_bytes",
    )
    parent_count = _integer(
        payload.get("parent_event_count"),
        "accepted_head_parent_event_count",
    )
    quarantined = _integer(
        payload.get("carried_quarantined_prefix_event_count"),
        "accepted_head_quarantined_event_count",
    )
    current_bytes = _integer(
        payload.get("current_event_log_bytes"),
        "accepted_head_current_event_log_bytes",
    )
    current_count = _integer(
        payload.get("current_event_count"),
        "accepted_head_current_event_count",
    )
    trusted_count = _integer(
        payload.get("trusted_event_count"),
        "accepted_head_trusted_event_count",
    )
    if (
        parent_bytes > current_bytes
        or parent_count > current_count
        or quarantined > parent_count
        or trusted_count != current_count - quarantined
    ):
        raise ValueError("accepted_head_outcome_chain_count_invalid")

    parent_anchor_status = payload["parent_anchor_status"]
    parent_summary_sha256 = payload.get("parent_summary_sha256")
    parent_summary_bytes = _integer(
        payload.get("parent_summary_bytes"),
        "accepted_head_parent_summary_bytes",
    )
    parent_as_of_date = payload.get("parent_as_of_date")
    if parent_anchor_status == "GENESIS_EMPTY":
        if (
            parent_summary_sha256 != ""
            or parent_summary_bytes != 0
            or payload.get("parent_event_log_sha256") != EMPTY_SHA256
            or parent_bytes != 0
            or parent_count != 0
            or parent_as_of_date != ""
        ):
            raise ValueError("accepted_head_genesis_anchor_invalid")
    elif parent_anchor_status == "VERIFIED_EMPTY_PARENT":
        if (
            not _valid_sha256(parent_summary_sha256)
            or parent_summary_bytes <= 0
            or not _valid_date(parent_as_of_date)
            or payload.get("parent_event_log_sha256") != EMPTY_SHA256
            or parent_bytes != 0
            or parent_count != 0
        ):
            raise ValueError("accepted_head_empty_parent_anchor_invalid")
    elif (
        not _valid_sha256(parent_summary_sha256)
        or parent_summary_bytes <= 0
        or not _valid_date(parent_as_of_date)
        or parent_bytes <= 0
        or parent_count <= 0
    ):
        raise ValueError("accepted_head_parent_anchor_invalid")
    if (
        parent_as_of_date
        and accepted_as_of_date < parent_as_of_date
    ):
        raise ValueError("accepted_head_as_of_precedes_parent")

    acceptance_status = payload.get("parent_acceptance_status")
    parent_accepted_sha256 = payload.get(
        "parent_accepted_manifest_sha256"
    )
    parent_accepted_bytes = _integer(
        payload.get("parent_accepted_manifest_bytes"),
        "accepted_head_parent_accepted_manifest_bytes",
    )
    parent_accepted_as_of_date = payload.get(
        "parent_accepted_manifest_as_of_date"
    )
    accepted_parent_empty = (
        parent_accepted_sha256 == ""
        and parent_accepted_bytes == 0
        and parent_accepted_as_of_date == ""
    )
    if acceptance_status == "NO_PRIOR_STATE":
        if (
            parent_anchor_status != "GENESIS_EMPTY"
            or not accepted_parent_empty
        ):
            raise ValueError("accepted_head_root_parent_sha256_not_empty")
    elif acceptance_status == "QUARANTINED_LEGACY":
        if (
            parent_anchor_status == "GENESIS_EMPTY"
            or not accepted_parent_empty
            or quarantined != parent_count
        ):
            raise ValueError(
                "accepted_head_legacy_quarantine_contract_invalid"
            )
    elif acceptance_status == CHILD_ACCEPTANCE_STATUS:
        if (
            not _valid_sha256(parent_accepted_sha256)
            or parent_accepted_sha256 == accepted_manifest_sha256
            or parent_accepted_bytes <= 0
            or not _valid_date(parent_accepted_as_of_date)
            or parent_accepted_as_of_date != parent_as_of_date
        ):
            raise ValueError("accepted_head_parent_manifest_sha256_invalid")
    else:
        raise ValueError("accepted_head_parent_acceptance_status_invalid")
    return dict(payload)


def _validate_accepted_manifest(
    manifest: Mapping[str, Any],
    *,
    accepted_manifest_sha256: str,
) -> dict[str, Any]:
    if (
        manifest.get("schema_version") != ACCEPTED_MANIFEST_SCHEMA
        or manifest.get("status") != ACCEPTED_MANIFEST_STATUS
        or manifest.get("review_only") is not True
    ):
        raise ValueError("accepted_head_manifest_contract_invalid")
    _require_false_fields(
        manifest,
        MANIFEST_FALSE_SAFETY_FIELDS,
        "accepted_head_manifest",
    )
    source_identity = manifest.get("source_identity")
    if (
        not isinstance(source_identity, dict)
        or not _valid_commit_sha(source_identity.get("commit_sha"))
        or not str(source_identity.get("workflow") or "").strip()
        or not str(source_identity.get("run_id") or "").strip()
        or not str(source_identity.get("run_attempt") or "").strip()
        or not _valid_sha256(
            source_identity.get("promotion_gate_sha256")
        )
    ):
        raise ValueError("accepted_head_source_identity_invalid")
    as_of_date = manifest.get("as_of_date")
    if not _valid_date(as_of_date):
        raise ValueError("accepted_head_as_of_date_invalid")
    outcome_status = manifest.get("outcome_status")
    if outcome_status not in PUBLISHABLE_OUTCOME_STATUSES:
        raise ValueError("accepted_head_outcome_status_invalid")
    _validate_paper_snapshot(manifest.get("paper_snapshot"))
    chain = _validate_outcome_chain(
        manifest.get("outcome_chain"),
        accepted_manifest_sha256=accepted_manifest_sha256,
        accepted_as_of_date=as_of_date,
    )
    files = manifest.get("files")
    promotion_gate_record = (
        files.get("promotion_gate")
        if isinstance(files, dict)
        else None
    )
    if (
        not isinstance(promotion_gate_record, dict)
        or promotion_gate_record.get("path")
        != PROMOTION_GATE_RELATIVE_PATH.as_posix()
        or promotion_gate_record.get("sha256")
        != source_identity["promotion_gate_sha256"]
    ):
        raise ValueError(
            "accepted_head_promotion_gate_binding_invalid"
        )
    summary_record = (
        files.get("risk_outcome_summary")
        if isinstance(files, dict)
        else None
    )
    if (
        not isinstance(summary_record, dict)
        or summary_record.get("path")
        != SUMMARY_RELATIVE_PATH.as_posix()
        or not _valid_sha256(summary_record.get("sha256"))
        or _integer(
            summary_record.get("bytes"),
            "accepted_head_summary_record_bytes",
        )
        <= 0
    ):
        raise ValueError("accepted_head_summary_record_invalid")
    event_record = (
        files.get("risk_outcome_event_log")
        if isinstance(files, dict)
        else None
    )
    if outcome_status == "READY_RISK_OUTCOME_ARCHIVE_REVIEW_ONLY":
        if (
            not isinstance(event_record, dict)
            or event_record.get("path")
            != EVENT_LOG_RELATIVE_PATH.as_posix()
            or event_record.get("sha256")
            != chain["current_event_log_sha256"]
        ):
            raise ValueError("accepted_head_event_record_invalid")
    elif (
        chain["current_event_log_sha256"] != EMPTY_SHA256
        or chain["current_event_log_bytes"] != 0
        or chain["current_event_count"] != 0
        or (
            event_record is not None
            and (
                not isinstance(event_record, dict)
                or event_record.get("path")
                != EVENT_LOG_RELATIVE_PATH.as_posix()
                or event_record.get("sha256") != EMPTY_SHA256
            )
        )
    ):
        raise ValueError("accepted_head_skipped_event_record_invalid")
    return dict(manifest)


def _strict_event_log_metadata(
    payload: bytes,
) -> tuple[str, int, int, int, int]:
    if not payload:
        return EMPTY_SHA256, 0, 0, 0, 0
    if not payload.endswith(b"\n"):
        raise ValueError("accepted_head_event_log_missing_final_newline")
    count = 0
    signal_observation_count = 0
    forward_outcome_event_count = 0
    event_ids: set[str] = set()
    for line_number, raw in enumerate(payload.splitlines(), start=1):
        if not raw.strip():
            raise ValueError(
                f"accepted_head_event_log_blank_row:{line_number}"
            )

        def object_pairs(
            pairs: list[tuple[str, Any]],
        ) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError(
                        "accepted_head_event_log_duplicate_json_key:"
                        f"{line_number}:{key}"
                    )
                result[key] = value
            return result

        try:
            row = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=object_pairs,
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"accepted_head_event_log_invalid_row:{line_number}"
            ) from exc
        if not isinstance(row, dict):
            raise ValueError(
                f"accepted_head_event_log_non_object_row:{line_number}"
            )
        event_id = row.get("event_id")
        if not isinstance(event_id, str) or not event_id.strip():
            raise ValueError(
                f"accepted_head_event_id_invalid:{line_number}"
            )
        if event_id in event_ids:
            raise ValueError(
                f"accepted_head_event_id_duplicate:{line_number}:{event_id}"
            )
        event_ids.add(event_id)
        event_type = row.get("event_type")
        if event_type not in OUTCOME_EVENT_TYPES:
            raise ValueError(
                f"accepted_head_event_type_invalid:{line_number}"
            )
        if event_type == "risk_signal_observed":
            signal_observation_count += 1
        else:
            forward_outcome_event_count += 1
        count += 1
    return (
        _sha256_bytes(payload),
        len(payload),
        count,
        signal_observation_count,
        forward_outcome_event_count,
    )


def _manifest_file_record(
    manifest: Mapping[str, Any],
    *,
    label: str,
    expected_relative_path: Path,
    require_bytes: bool = False,
) -> dict[str, Any]:
    files = manifest.get("files")
    record = files.get(label) if isinstance(files, dict) else None
    expected_path = expected_relative_path.as_posix()
    if (
        not isinstance(record, dict)
        or record.get("path") != expected_path
        or not _valid_sha256(record.get("sha256"))
    ):
        raise ValueError(f"accepted_head_manifest_file_record_invalid:{label}")
    result: dict[str, Any] = {
        "path": expected_path,
        "sha256": record["sha256"],
    }
    if require_bytes:
        declared_bytes = _integer(
            record.get("bytes"),
            f"accepted_head_manifest_file_bytes:{label}",
        )
        if declared_bytes <= 0:
            raise ValueError(
                f"accepted_head_manifest_file_bytes_invalid:{label}"
            )
        result["bytes"] = declared_bytes
    return result


def _verify_bundle(
    *,
    bundle_root: Path,
    manifest_path: Path,
    expected_manifest_sha256: str,
    require_hash_named_directory: bool,
) -> dict[str, Any]:
    if not _valid_sha256(expected_manifest_sha256):
        raise ValueError("expected_accepted_manifest_sha256_invalid")
    if bundle_root.is_symlink() or not bundle_root.is_dir():
        raise ValueError("accepted_head_bundle_root_missing_or_not_directory")
    _require_regular_file(manifest_path, "accepted_head_manifest")
    bundle_root = bundle_root.resolve()
    manifest_path = manifest_path.resolve()
    try:
        manifest_path.relative_to(bundle_root)
    except ValueError as exc:
        raise ValueError("accepted_head_manifest_outside_bundle") from exc
    if require_hash_named_directory and bundle_root.name != expected_manifest_sha256:
        raise ValueError("accepted_head_directory_name_mismatch")
    actual_manifest_sha256 = _sha256_file(manifest_path)
    if actual_manifest_sha256 != expected_manifest_sha256:
        raise ValueError("accepted_head_manifest_sha256_mismatch")
    manifest = _json_object_no_duplicates(manifest_path)
    _validate_accepted_manifest(
        manifest,
        accepted_manifest_sha256=actual_manifest_sha256,
    )
    manifest_files = manifest.get("files")
    has_event_record = (
        isinstance(manifest_files, dict)
        and "risk_outcome_event_log" in manifest_files
    )
    if require_hash_named_directory:
        expected_files = {
            MANIFEST_RELATIVE_PATH,
            SUMMARY_RELATIVE_PATH,
        }
        if has_event_record:
            expected_files.add(EVENT_LOG_RELATIVE_PATH)
        actual_files = _bundle_file_set(bundle_root)
        if actual_files != expected_files:
            missing = sorted(
                path.as_posix() for path in expected_files - actual_files
            )
            extra = sorted(
                path.as_posix() for path in actual_files - expected_files
            )
            raise ValueError(
                "accepted_head_bundle_file_set_mismatch:"
                f"missing={','.join(missing)}:"
                f"extra={','.join(extra)}"
            )

    summary_candidate = bundle_root / SUMMARY_RELATIVE_PATH
    event_candidate = bundle_root / EVENT_LOG_RELATIVE_PATH
    _require_regular_file(
        summary_candidate,
        "accepted_head_outcome_summary",
    )
    summary_path = summary_candidate.resolve()
    try:
        summary_path.relative_to(bundle_root)
    except ValueError as exc:
        raise ValueError(
            "accepted_head_outcome_summary_outside_bundle"
        ) from exc

    outcome_status = manifest["outcome_status"]
    event_exists = event_candidate.exists() or event_candidate.is_symlink()
    if outcome_status == "READY_RISK_OUTCOME_ARCHIVE_REVIEW_ONLY":
        _require_regular_file(
            event_candidate,
            "accepted_head_outcome_event_log",
        )
    elif event_candidate.is_symlink():
        raise ValueError(
            "accepted_head_outcome_event_log_missing_or_not_regular:"
            f"{event_candidate}"
        )
    if event_exists:
        _require_regular_file(
            event_candidate,
            "accepted_head_outcome_event_log",
        )
        event_path = event_candidate.resolve()
        try:
            event_path.relative_to(bundle_root)
        except ValueError as exc:
            raise ValueError(
                "accepted_head_outcome_event_log_outside_bundle"
            ) from exc
        event_payload = event_path.read_bytes()
    else:
        event_payload = b""

    summary_record = _manifest_file_record(
        manifest,
        label="risk_outcome_summary",
        expected_relative_path=SUMMARY_RELATIVE_PATH,
        require_bytes=True,
    )
    if (
        outcome_status == "READY_RISK_OUTCOME_ARCHIVE_REVIEW_ONLY"
        or has_event_record
    ):
        event_record = _manifest_file_record(
            manifest,
            label="risk_outcome_event_log",
            expected_relative_path=EVENT_LOG_RELATIVE_PATH,
        )
    else:
        event_record = None
    if has_event_record and not event_exists:
        raise ValueError("accepted_head_attested_event_log_missing")
    summary_sha256 = _sha256_file(summary_path)
    raw_event_sha256 = _sha256_bytes(event_payload)
    if (
        event_record is not None
        and event_record["sha256"] != raw_event_sha256
    ):
        raise ValueError("accepted_head_outcome_event_log_sha256_mismatch")
    (
        event_sha256,
        event_bytes,
        event_count,
        signal_observation_count,
        forward_outcome_event_count,
    ) = _strict_event_log_metadata(event_payload)
    if summary_record["sha256"] != summary_sha256:
        raise ValueError("accepted_head_outcome_summary_sha256_mismatch")
    if summary_record["bytes"] != summary_path.stat().st_size:
        raise ValueError("accepted_head_outcome_summary_bytes_mismatch")
    if (
        outcome_status == "SKIPPED_NO_DECISION_OBSERVATIONS"
        and event_payload
    ):
        raise ValueError("accepted_head_skipped_event_log_not_empty")

    summary = _json_object_no_duplicates(summary_path)
    if (
        summary.get("schema_version") != OUTCOME_ARCHIVE_SCHEMA
        or summary.get("status") != manifest.get("outcome_status")
        or summary.get("as_of_date") != manifest.get("as_of_date")
        or summary.get("review_only") is not True
        or summary.get("blockers") != []
    ):
        raise ValueError("accepted_head_outcome_summary_contract_invalid")
    _require_false_fields(
        summary,
        OUTCOME_FALSE_SAFETY_FIELDS,
        "accepted_head_outcome_summary",
    )
    declared_signal_observation_count = _integer(
        summary.get("signal_observation_count"),
        "accepted_head_summary_signal_observation_count",
    )
    declared_forward_outcome_event_count = _integer(
        summary.get("forward_outcome_event_count"),
        "accepted_head_summary_forward_outcome_event_count",
    )
    if (
        declared_signal_observation_count != signal_observation_count
        or declared_forward_outcome_event_count
        != forward_outcome_event_count
        or declared_signal_observation_count
        + declared_forward_outcome_event_count
        != event_count
    ):
        raise ValueError("accepted_head_summary_event_count_mismatch")
    if summary.get("outcome_chain") != manifest.get("outcome_chain"):
        raise ValueError("accepted_head_outcome_chain_binding_mismatch")
    chain = _validate_outcome_chain(
        summary.get("outcome_chain"),
        accepted_manifest_sha256=actual_manifest_sha256,
        accepted_as_of_date=manifest["as_of_date"],
    )
    if (
        chain.get("current_event_log_sha256") != event_sha256
        or chain.get("current_event_log_bytes") != event_bytes
        or chain.get("current_event_count") != event_count
    ):
        raise ValueError("accepted_head_current_event_log_metadata_mismatch")
    parent_event_bytes = chain["parent_event_log_bytes"]
    parent_event_count = chain["parent_event_count"]
    parent_prefix = event_payload[:parent_event_bytes]
    parent_prefix_sha256, _, parent_prefix_count, _, _ = (
        _strict_event_log_metadata(parent_prefix)
    )
    if (
        parent_event_bytes > event_bytes
        or parent_prefix_sha256 != chain["parent_event_log_sha256"]
        or parent_prefix_count != parent_event_count
    ):
        raise ValueError("accepted_head_parent_event_prefix_mismatch")
    if summary["status"] == "READY_RISK_OUTCOME_ARCHIVE_REVIEW_ONLY":
        outputs = summary.get("outputs")
        if (
            not isinstance(outputs, dict)
            or outputs.get("event_log_sha256") != event_sha256
        ):
            raise ValueError("accepted_head_summary_event_output_mismatch")

    return {
        "schema_version": VERIFY_SCHEMA,
        "status": VERIFY_STATUS,
        "accepted_manifest_sha256": actual_manifest_sha256,
        "as_of_date": manifest["as_of_date"],
        "outcome_status": manifest["outcome_status"],
        "parent_acceptance_status": chain["parent_acceptance_status"],
        "parent_accepted_manifest_sha256": chain[
            "parent_accepted_manifest_sha256"
        ],
        "paper_snapshot_hash": manifest["paper_snapshot"]["snapshot_hash"],
        "outcome_summary_sha256": summary_sha256,
        "outcome_event_log_sha256": event_sha256,
        "outcome_event_log_bytes": event_bytes,
        "outcome_event_count": event_count,
        "signal_observation_count": signal_observation_count,
        "forward_outcome_event_count": forward_outcome_event_count,
        "review_only": True,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
    }


def verify_head(
    *,
    head_dir: str | Path,
    expected_manifest_sha256: str,
) -> dict[str, Any]:
    """Verify an immutable accepted-head bundle by its expected manifest SHA."""
    directory = _repo_path(head_dir)
    return _verify_bundle(
        bundle_root=directory,
        manifest_path=directory / MANIFEST_RELATIVE_PATH,
        expected_manifest_sha256=expected_manifest_sha256,
        require_hash_named_directory=True,
    )


def _manifest_nodes(heads_root: Path) -> dict[str, dict[str, Any]]:
    if heads_root.is_symlink() or not heads_root.is_dir():
        raise ValueError("accepted_heads_root_missing_or_not_directory")
    nodes: dict[str, dict[str, Any]] = {}
    for entry in sorted(heads_root.iterdir(), key=lambda path: path.name):
        if HEX_64.fullmatch(entry.name) is None:
            continue
        if entry.is_symlink() or not entry.is_dir():
            raise ValueError(f"accepted_head_not_directory:{entry.name}")
        manifest_path = entry / MANIFEST_RELATIVE_PATH
        _require_regular_file(manifest_path, "accepted_head_manifest")
        manifest_sha256 = _sha256_file(manifest_path)
        if manifest_sha256 != entry.name:
            raise ValueError(
                f"accepted_head_directory_manifest_sha256_mismatch:{entry.name}"
            )
        manifest = _json_object_no_duplicates(manifest_path)
        _validate_accepted_manifest(
            manifest,
            accepted_manifest_sha256=manifest_sha256,
        )
        manifest["_accepted_head_manifest_bytes"] = (
            manifest_path.stat().st_size
        )
        nodes[manifest_sha256] = manifest
    if not nodes:
        raise ValueError("accepted_heads_empty")
    return nodes


def _linear_chain(
    nodes: Mapping[str, Mapping[str, Any]],
) -> tuple[str, str, list[str]]:
    parents: dict[str, str] = {}
    roots: list[str] = []
    children: dict[str, list[str]] = {sha256: [] for sha256 in nodes}
    for sha256, manifest in nodes.items():
        chain = manifest["outcome_chain"]
        acceptance_status = chain["parent_acceptance_status"]
        parent = chain["parent_accepted_manifest_sha256"]
        if acceptance_status in ROOT_ACCEPTANCE_STATUSES:
            roots.append(sha256)
            parents[sha256] = ""
            continue
        if parent not in nodes:
            raise ValueError(f"accepted_head_parent_missing:{sha256}:{parent}")
        if (
            chain.get("parent_accepted_manifest_bytes")
            != nodes[parent].get("_accepted_head_manifest_bytes")
            or chain.get("parent_accepted_manifest_as_of_date")
            != nodes[parent].get("as_of_date")
        ):
            raise ValueError(
                f"accepted_head_parent_identity_mismatch:{sha256}:{parent}"
            )
        parent_manifest = nodes[parent]
        parent_chain = parent_manifest["outcome_chain"]
        child_paper = manifest["paper_snapshot"]
        parent_paper = parent_manifest["paper_snapshot"]
        if (
            child_paper["genesis_identity_sha256"]
            != parent_paper["genesis_identity_sha256"]
        ):
            raise ValueError(
                f"accepted_head_parent_paper_genesis_mismatch:"
                f"{sha256}:{parent}"
            )
        if child_paper["snapshot_hash"] == parent_paper["snapshot_hash"]:
            if child_paper != parent_paper:
                raise ValueError(
                    f"accepted_head_parent_paper_state_mismatch:"
                    f"{sha256}:{parent}"
                )
        else:
            child_ancestors = child_paper["ancestor_snapshot_hashes"]
            if parent_paper["snapshot_hash"] not in child_ancestors:
                raise ValueError(
                    f"accepted_head_parent_paper_not_ancestor:"
                    f"{sha256}:{parent}"
                )
            parent_index = child_ancestors.index(
                parent_paper["snapshot_hash"]
            )
            if (
                child_ancestors[parent_index + 1 :]
                != parent_paper["ancestor_snapshot_hashes"]
            ):
                raise ValueError(
                    f"accepted_head_parent_paper_chain_mismatch:"
                    f"{sha256}:{parent}"
                )
        parent_summary_record = parent_manifest["files"][
            "risk_outcome_summary"
        ]
        expected_parent_anchor_status = (
            "VERIFIED_PARENT"
            if parent_chain["current_event_count"] > 0
            else "VERIFIED_EMPTY_PARENT"
        )
        expected_parent_fields = {
            "parent_anchor_status": expected_parent_anchor_status,
            "parent_summary_sha256": parent_summary_record["sha256"],
            "parent_summary_bytes": parent_summary_record["bytes"],
            "parent_event_log_sha256":
                parent_chain["current_event_log_sha256"],
            "parent_event_log_bytes":
                parent_chain["current_event_log_bytes"],
            "parent_event_count": parent_chain["current_event_count"],
            "parent_as_of_date": parent_manifest["as_of_date"],
            "carried_quarantined_prefix_event_count":
                parent_chain["carried_quarantined_prefix_event_count"],
        }
        mismatched = [
            field
            for field, expected in expected_parent_fields.items()
            if chain.get(field) != expected
        ]
        if mismatched:
            raise ValueError(
                f"accepted_head_parent_state_mismatch:{sha256}:{parent}:"
                + ",".join(sorted(mismatched))
            )
        parents[sha256] = parent
        children[parent].append(sha256)

    # Detect cycles independently of root/terminal checks so a disconnected
    # cycle can never hide behind an otherwise valid rooted component. Keep
    # this iterative because a healthy durable history can exceed Python's
    # recursion limit.
    colours: dict[str, int] = {sha256: 0 for sha256 in nodes}
    for start in sorted(nodes):
        if colours[start] == 2:
            continue
        cursor = start
        active: list[str] = []
        while cursor and colours[cursor] == 0:
            colours[cursor] = 1
            active.append(cursor)
            cursor = parents[cursor]
        if cursor and colours[cursor] == 1:
            raise ValueError(f"accepted_head_cycle_detected:{cursor}")
        for sha256 in reversed(active):
            colours[sha256] = 2

    if len(roots) != 1:
        raise ValueError(f"accepted_head_root_count_invalid:{len(roots)}")
    for parent, child_rows in children.items():
        if len(child_rows) > 1:
            raise ValueError(
                f"accepted_head_fork_detected:{parent}:"
                + ",".join(sorted(child_rows))
            )
    terminals = sorted(
        sha256 for sha256, child_rows in children.items() if not child_rows
    )
    if len(terminals) != 1:
        raise ValueError(
            f"accepted_head_terminal_count_invalid:{len(terminals)}"
        )

    root = roots[0]
    chain_order = [root]
    cursor = root
    while children[cursor]:
        cursor = children[cursor][0]
        chain_order.append(cursor)
    if len(chain_order) != len(nodes):
        raise ValueError("accepted_head_chain_disconnected")
    return root, terminals[0], chain_order


def select_heads(
    *,
    heads_root: str | Path,
    now_utc: str | None = None,
) -> dict[str, Any]:
    """Select the unique terminal of one complete, linear accepted-head chain."""
    root_path = _repo_path(heads_root).resolve()
    nodes = _manifest_nodes(root_path)
    root_sha256, terminal_sha256, chain_order = _linear_chain(nodes)
    terminal = nodes[terminal_sha256]
    return {
        "schema_version": SELECTION_SCHEMA,
        "status": SELECTION_STATUS,
        "generated_at_utc": now_utc or _utc_now(),
        "heads_root": str(root_path),
        "accepted_head_count": len(chain_order),
        "root_accepted_manifest_sha256": root_sha256,
        "terminal_accepted_manifest_sha256": terminal_sha256,
        "selected_accepted_manifest_sha256": terminal_sha256,
        "selected_as_of_date": terminal["as_of_date"],
        "chain_accepted_manifest_sha256s": chain_order,
        "review_only": True,
        "automatic_head_mutation_allowed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
    }


def _bundle_file_set(directory: Path) -> set[Path]:
    files: set[Path] = set()
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"accepted_head_bundle_symlink_forbidden:{path}")
        if path.is_file():
            files.add(path.relative_to(directory))
    return files


def _write_bytes_durable(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _existing_bundle_exact(
    target: Path,
    expected_payloads: Mapping[Path, bytes],
    expected_manifest_sha256: str,
) -> bool:
    if target.is_symlink() or not target.is_dir():
        return False
    if _bundle_file_set(target) != set(expected_payloads):
        return False
    for relative, payload in expected_payloads.items():
        path = target / relative
        if path.read_bytes() != payload:
            return False
    verify_head(
        head_dir=target,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    return True


def stage_head(
    *,
    latest_run: str | Path,
    expected_manifest_sha256: str,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Stage the accepted manifest and outcome archive as an immutable bundle."""
    source_root = _repo_path(latest_run).resolve()
    target = _repo_path(output_dir)
    if not _valid_sha256(expected_manifest_sha256):
        raise ValueError("expected_accepted_manifest_sha256_invalid")
    if target.name != expected_manifest_sha256:
        raise ValueError("accepted_head_output_directory_name_mismatch")

    source_manifest = (
        source_root / "run287_accepted_publication" / "manifest.json"
    )
    verification = _verify_bundle(
        bundle_root=source_root,
        manifest_path=source_manifest,
        expected_manifest_sha256=expected_manifest_sha256,
        require_hash_named_directory=False,
    )
    source_paths: dict[Path, Path] = {
        MANIFEST_RELATIVE_PATH: source_manifest,
        SUMMARY_RELATIVE_PATH: source_root / SUMMARY_RELATIVE_PATH,
    }
    source_event_path = source_root / EVENT_LOG_RELATIVE_PATH
    if source_event_path.is_file():
        source_paths[EVENT_LOG_RELATIVE_PATH] = source_event_path
    payloads = {
        relative: path.read_bytes() for relative, path in source_paths.items()
    }

    if target.exists() or target.is_symlink():
        if _existing_bundle_exact(
            target,
            payloads,
            expected_manifest_sha256,
        ):
            stage_status = "ALREADY_STAGED_EXACT_MATCH"
        else:
            raise ValueError("accepted_head_output_exists_not_exact_match")
    else:
        target_parent = target.parent
        target_parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(
            tempfile.mkdtemp(
                prefix=f".{expected_manifest_sha256}.stage-",
                dir=target_parent,
            )
        )
        try:
            for relative, payload in payloads.items():
                _write_bytes_durable(temporary / relative, payload)
            _verify_bundle(
                bundle_root=temporary,
                manifest_path=temporary / MANIFEST_RELATIVE_PATH,
                expected_manifest_sha256=expected_manifest_sha256,
                require_hash_named_directory=False,
            )
            try:
                os.replace(temporary, target)
            except OSError:
                if not _existing_bundle_exact(
                    target,
                    payloads,
                    expected_manifest_sha256,
                ):
                    raise
            stage_status = "STAGED_NEW_ACCEPTED_HEAD"
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)

    staged_verification = verify_head(
        head_dir=target,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    return {
        "schema_version": STAGE_SCHEMA,
        "status": stage_status,
        "accepted_manifest_sha256": expected_manifest_sha256,
        "output_dir": str(target.resolve()),
        "outcome_summary_sha256": verification["outcome_summary_sha256"],
        "outcome_event_log_sha256": verification[
            "outcome_event_log_sha256"
        ],
        "staged_verification_status": staged_verification["status"],
        "review_only": True,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
    }


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(
                payload,
                handle,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _emit(payload: Mapping[str, Any], output: str | None) -> None:
    if output:
        _write_json_atomic(_repo_path(output), payload)
    print(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    select_parser = subparsers.add_parser(
        "select",
        help="validate all local heads and select the unique terminal",
    )
    select_parser.add_argument("--heads-root", required=True)
    select_parser.add_argument("--output", required=True)

    verify_parser = subparsers.add_parser(
        "verify",
        help="verify one hash-named accepted-head bundle",
    )
    verify_parser.add_argument("--head-dir", required=True)
    verify_parser.add_argument(
        "--expected-manifest-sha256",
        required=True,
    )
    verify_parser.add_argument("--output")

    stage_parser = subparsers.add_parser(
        "stage",
        help="stage the latest accepted publication as an immutable head",
    )
    stage_parser.add_argument("--latest-run", default="outputs")
    stage_parser.add_argument(
        "--expected-manifest-sha256",
        required=True,
    )
    stage_parser.add_argument(
        "--output-dir",
        required=True,
        help="new hash-named head directory (basename must equal manifest SHA)",
    )
    stage_parser.add_argument("--output")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "select":
            payload = select_heads(heads_root=args.heads_root)
            _emit(payload, args.output)
        elif args.command == "verify":
            payload = verify_head(
                head_dir=args.head_dir,
                expected_manifest_sha256=args.expected_manifest_sha256,
            )
            _emit(payload, args.output)
        else:
            payload = stage_head(
                latest_run=args.latest_run,
                expected_manifest_sha256=args.expected_manifest_sha256,
                output_dir=args.output_dir,
            )
            _emit(payload, args.output)
    except (OSError, ValueError) as exc:
        print(f"run287_risk_outcome_accepted_heads_error:{exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
