#!/usr/bin/env python3
"""Build a durable, read-only preflight receipt for a risk-outcome root.

The preflight runs before target construction or a paper-ledger transaction.
It proves whether an immutable accepted outcome head is absent, validates the
one byte-exact legacy parent (or true genesis absence), and records whether an
explicit workflow-dispatch authorization is present.  It never creates an
accepted head, parent anchor, target, order, ledger event, or durable state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(REPO_ROOT))

from tools.build_run287_risk_outcome_parent_anchor import (  # noqa: E402
    KNOWN_LEGACY_SAFETY_MIGRATIONS,
    build_anchor,
    strict_json_object,
)
from tools.run287_paper_ledger_integrity import (  # noqa: E402
    INTEGRITY_FILE,
    PAPER_INTEGRITY_VERIFIER_RECEIPT_SCHEMA,
    PAPER_INTEGRITY_VERIFIER_RECEIPT_STATUS,
    PaperLedgerIntegrityError,
    build_integrity_verifier_receipt,
    integrity_verifier_receipt_bytes,
)


SCHEMA_VERSION = "run287-risk-outcome-parent-preflight-v1"
LEGACY_PRESENT = "PRESENT_FETCHED"
LEGACY_ABSENT = "PROVEN_ABSENT"
ALLOWED_LEGACY_STATES = {LEGACY_PRESENT, LEGACY_ABSENT}
ALLOWED_EVENTS = {"schedule", "workflow_dispatch"}
FALSE_SAFETY_FLAGS = (
    "accepted_head_created",
    "parent_anchor_created",
    "target_books_mutated",
    "orders_generated",
    "ledger_mutated",
    "historical_cagr_mdd_evidence_changed",
    "fullrun_executed",
    "production_activation_allowed",
    "live_trading_enabled",
    "automatic_promotion_allowed",
)


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


def valid_hash(value: Any, length: int) -> bool:
    text = str(value or "").lower()
    return len(text) == length and all(
        character in "0123456789abcdef" for character in text
    )


def strict_nonnegative_integer(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label}_invalid")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}_invalid") from exc
    if parsed < 0 or str(parsed) != str(value).strip():
        raise ValueError(f"{label}_invalid")
    return parsed


def validate_source_identity(
    *,
    event_name: str,
    source_commit_sha: str,
    source_run_id: str,
    source_run_attempt: str,
    source_job_key: str,
    session_date: str,
) -> dict[str, str]:
    if event_name not in ALLOWED_EVENTS:
        raise ValueError("event_name_invalid")
    if not valid_hash(source_commit_sha, 40):
        raise ValueError("source_commit_sha_invalid")
    if not str(source_run_id or "").isdigit() or int(source_run_id) <= 0:
        raise ValueError("source_run_id_invalid")
    if (
        not str(source_run_attempt or "").isdigit()
        or int(source_run_attempt) <= 0
    ):
        raise ValueError("source_run_attempt_invalid")
    if (
        not str(source_job_key or "").strip()
        or any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
            for character in str(source_job_key)
        )
    ):
        raise ValueError("source_job_key_invalid")
    try:
        parsed = datetime.strptime(session_date, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("session_date_invalid") from exc
    if parsed.strftime("%Y-%m-%d") != session_date:
        raise ValueError("session_date_invalid")
    return {
        "event_name": event_name,
        "source_commit_sha": source_commit_sha.lower(),
        "source_run_id": str(source_run_id),
        "source_run_attempt": str(source_run_attempt),
        "source_job_key": str(source_job_key),
        "session_date": session_date,
    }


def validate_paper_integrity(
    path: str | Path,
    *,
    verifier_receipt_path: str | Path,
    immutable_head_selection_path: str | Path,
) -> dict[str, Any]:
    paper_path = repo_path(path)
    verifier_receipt = repo_path(verifier_receipt_path)
    selection_path = repo_path(immutable_head_selection_path)
    if (
        paper_path.name != INTEGRITY_FILE
        or paper_path.is_symlink()
        or not paper_path.is_file()
    ):
        raise ValueError("paper_integrity_missing")
    if selection_path.is_symlink() or not selection_path.is_file():
        raise ValueError("paper_immutable_head_selection_missing")
    try:
        expected_receipt = build_integrity_verifier_receipt(
            paper_path.parent,
            immutable_head_selection=selection_path,
        )
    except PaperLedgerIntegrityError as exc:
        raise ValueError(
            "paper_integrity_verification_failed:"
            f"{exc.status}:{exc.reason}"
        ) from exc
    if verifier_receipt.is_symlink() or not verifier_receipt.is_file():
        raise ValueError("paper_integrity_verifier_receipt_missing")
    receipt_raw = verifier_receipt.read_bytes()
    supplied_receipt = strict_json_object(
        receipt_raw,
        label="paper_integrity_verifier_receipt",
    )
    if (
        expected_receipt.get("schema_version")
        != PAPER_INTEGRITY_VERIFIER_RECEIPT_SCHEMA
        or expected_receipt.get("status")
        != PAPER_INTEGRITY_VERIFIER_RECEIPT_STATUS
        or supplied_receipt != expected_receipt
        or receipt_raw
        != integrity_verifier_receipt_bytes(expected_receipt)
    ):
        raise ValueError("paper_integrity_verifier_receipt_mismatch")
    raw_manifest = expected_receipt["raw_manifest"]
    selection = expected_receipt["immutable_head_selection"]
    return {
        "schema_version": raw_manifest["schema_version"],
        "status": expected_receipt["status"],
        "file_sha256": raw_manifest["sha256"],
        "file_bytes": raw_manifest["bytes"],
        "file_count": raw_manifest["file_count"],
        "files_sha256": raw_manifest["files_sha256"],
        "snapshot_hash": raw_manifest["snapshot_hash"],
        "previous_snapshot_hash": raw_manifest[
            "previous_snapshot_hash"
        ],
        "ancestor_snapshot_count": len(
            raw_manifest["ancestor_snapshot_hashes"]
        ),
        "genesis_identity_sha256": raw_manifest[
            "genesis_identity_sha256"
        ],
        "as_of_date": raw_manifest["as_of_date"],
        "verifier_receipt_schema_version": expected_receipt[
            "schema_version"
        ],
        "verifier_receipt_sha256": sha256_bytes(receipt_raw),
        "verifier_receipt_bytes": len(receipt_raw),
        "immutable_head_selection_sha256": selection["sha256"],
        "immutable_head_count": selection["immutable_head_count"],
        "immutable_root_snapshot_hash": selection[
            "root_snapshot_hash"
        ],
        "immutable_terminal_snapshot_hash": selection[
            "terminal_snapshot_hash"
        ],
        "immutable_chain_snapshot_hashes": list(
            selection["chain_snapshot_hashes"]
        ),
    }


def validate_legacy_parent(
    summary_path: str | Path,
    event_log_path: str | Path,
) -> dict[str, Any]:
    summary = repo_path(summary_path)
    event_log = repo_path(event_log_path)
    if not summary.is_file():
        raise ValueError("legacy_summary_missing")
    raw = summary.read_bytes()
    digest = sha256_bytes(raw)
    if digest not in KNOWN_LEGACY_SAFETY_MIGRATIONS:
        raise ValueError(f"legacy_summary_sha256_not_allowlisted:{digest}")
    anchor = build_anchor(
        summary,
        event_log,
        allow_quarantined_legacy_parent=True,
        now_utc="1970-01-01T00:00:00Z",
    )
    migration = anchor.get("legacy_safety_migration")
    if (
        anchor.get("parent_acceptance_status") != "QUARANTINED_LEGACY"
        or not isinstance(migration, dict)
        or migration.get("source_summary_sha256") != digest
    ):
        raise ValueError("legacy_summary_quarantine_contract_invalid")
    return {
        "state": LEGACY_PRESENT,
        "summary_sha256": digest,
        "summary_bytes": len(raw),
        "as_of_date": anchor["parent_as_of_date"],
        "status": migration["source_status"],
        "event_log_sha256": anchor["parent_event_log_sha256"],
        "event_log_bytes": anchor["parent_event_log_bytes"],
        "event_count": anchor["parent_event_count"],
        "allowlist_evidence_workflow_run_id": migration[
            "evidence_workflow_run_id"
        ],
        "byte_exact_allowlist_match": True,
        "review_only": True,
    }


def build_receipt(
    *,
    event_name: str,
    source_commit_sha: str,
    source_run_id: str,
    source_run_attempt: str,
    source_job_key: str,
    session_date: str,
    remote_head_discovery_confirmed: bool,
    remote_committed_head_count: int,
    remote_legacy_outcome_state: str,
    legacy_summary_path: str | Path,
    legacy_event_log_path: str | Path,
    paper_integrity_path: str | Path,
    paper_integrity_verifier_receipt_path: str | Path,
    paper_immutable_head_selection_path: str | Path,
    allow_risk_outcome_genesis_bootstrap: bool,
    allow_quarantined_legacy_outcome_parent: bool,
    generated_at_utc: str | None = None,
) -> tuple[dict[str, Any], int]:
    source = validate_source_identity(
        event_name=event_name,
        source_commit_sha=source_commit_sha,
        source_run_id=source_run_id,
        source_run_attempt=source_run_attempt,
        source_job_key=source_job_key,
        session_date=session_date,
    )
    head_count = strict_nonnegative_integer(
        remote_committed_head_count,
        "remote_committed_head_count",
    )
    if remote_legacy_outcome_state not in ALLOWED_LEGACY_STATES:
        raise ValueError("remote_legacy_outcome_state_invalid")
    if remote_head_discovery_confirmed is not True:
        raise ValueError("remote_accepted_head_discovery_not_confirmed")
    if head_count != 0:
        raise ValueError("remote_accepted_head_absence_not_proven")

    paper = validate_paper_integrity(
        paper_integrity_path,
        verifier_receipt_path=paper_integrity_verifier_receipt_path,
        immutable_head_selection_path=(
            paper_immutable_head_selection_path
        ),
    )
    legacy: dict[str, Any]
    if remote_legacy_outcome_state == LEGACY_PRESENT:
        legacy = validate_legacy_parent(
            legacy_summary_path,
            legacy_event_log_path,
        )
        mode = "legacy_quarantine"
        required_input = "allow_quarantined_legacy_outcome_parent"
        requested = allow_quarantined_legacy_outcome_parent
        conflicting = allow_risk_outcome_genesis_bootstrap
        ready_status = "READY_ONE_TIME_LEGACY_QUARANTINE"
        blocked_status = (
            "BLOCKED_ONE_TIME_LEGACY_QUARANTINE_AUTHORIZATION_REQUIRED"
        )
    else:
        if repo_path(legacy_summary_path).exists() or repo_path(
            legacy_event_log_path
        ).exists():
            raise ValueError("legacy_remote_absence_conflicts_with_local_state")
        legacy = {
            "state": LEGACY_ABSENT,
            "summary_sha256": "",
            "summary_bytes": 0,
            "event_log_sha256": hashlib.sha256(b"").hexdigest(),
            "event_log_bytes": 0,
            "event_count": 0,
            "byte_exact_allowlist_match": False,
            "review_only": True,
        }
        mode = "genesis"
        required_input = "allow_risk_outcome_genesis_bootstrap"
        requested = allow_risk_outcome_genesis_bootstrap
        conflicting = allow_quarantined_legacy_outcome_parent
        ready_status = "READY_ONE_TIME_GENESIS"
        blocked_status = "BLOCKED_ONE_TIME_GENESIS_AUTHORIZATION_REQUIRED"

    blockers: list[str] = []
    if requested and conflicting:
        blockers.append("bootstrap_authorizations_mutually_exclusive")
        status = "BLOCKED_MUTUALLY_EXCLUSIVE_BOOTSTRAP_AUTHORIZATIONS"
    elif conflicting:
        blockers.append("authorization_does_not_match_observed_parent_mode")
        status = "BLOCKED_PARENT_MODE_AUTHORIZATION_MISMATCH"
    elif event_name != "workflow_dispatch" or not requested:
        blockers.append("explicit_workflow_dispatch_authorization_required")
        status = blocked_status
    else:
        status = ready_status

    exit_code = 0 if not blockers else 2
    authorization_satisfied = exit_code == 0
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "generated_at_utc": generated_at_utc or utc_now(),
        "source": source,
        "observed_state": {
            "remote_accepted_head_discovery_confirmed": True,
            "remote_committed_accepted_head_count": head_count,
            "remote_committed_accepted_head_absence_proven": True,
            "legacy_parent": legacy,
            "paper_ledger": paper,
        },
        "authorization": {
            "mode": mode,
            "required_event_name": "workflow_dispatch",
            "required_input": required_input,
            "requested": requested,
            "conflicting_authorization_requested": conflicting,
            "satisfied": authorization_satisfied,
            "one_time_only": True,
            "separate_user_approval_required": True,
        },
        "blockers": blockers,
        "exit_code": exit_code,
        "next_action": (
            "continue_to_existing_one_time_parent_anchor_boundary"
            if authorization_satisfied
            else "obtain_separate_user_approval_before_workflow_dispatch"
        ),
        "review_only": True,
    }
    receipt.update({field: False for field in FALSE_SAFETY_FLAGS})
    return receipt, exit_code


def blocked_receipt(
    *,
    args: argparse.Namespace,
    reason: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "BLOCKED_PREFLIGHT_EVIDENCE_INVALID",
        "generated_at_utc": args.generated_at_utc or utc_now(),
        "source": {
            "event_name": args.event_name,
            "source_commit_sha": args.source_commit_sha,
            "source_run_id": args.source_run_id,
            "source_run_attempt": args.source_run_attempt,
            "source_job_key": args.source_job_key,
            "session_date": args.session_date,
        },
        "observed_state": {
            "remote_accepted_head_discovery_confirmed": (
                args.remote_head_discovery_confirmed
            ),
            "remote_committed_accepted_head_count": (
                args.remote_committed_head_count
            ),
            "remote_legacy_outcome_state": (
                args.remote_legacy_outcome_state
            ),
        },
        "authorization": {
            "allow_risk_outcome_genesis_bootstrap": (
                args.allow_risk_outcome_genesis_bootstrap
            ),
            "allow_quarantined_legacy_outcome_parent": (
                args.allow_quarantined_legacy_outcome_parent
            ),
            "satisfied": False,
            "one_time_only": True,
            "separate_user_approval_required": True,
        },
        "blockers": [reason],
        "exit_code": 2,
        "next_action": "repair_or_recollect_read_only_preflight_evidence",
        "review_only": True,
    }
    payload.update({field: False for field in FALSE_SAFETY_FLAGS})
    return payload


def write_receipt(path: str | Path, payload: Mapping[str, Any]) -> None:
    output = repo_path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    raw = (
        json.dumps(
            dict(payload),
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_bytes(raw)
    os.replace(temporary, output)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--source-commit-sha", required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--source-run-attempt", required=True)
    parser.add_argument("--source-job-key", required=True)
    parser.add_argument("--session-date", required=True)
    parser.add_argument(
        "--remote-head-discovery-confirmed",
        action="store_true",
    )
    parser.add_argument("--remote-committed-head-count", required=True)
    parser.add_argument("--remote-legacy-outcome-state", required=True)
    parser.add_argument(
        "--legacy-summary",
        default="outputs/run287_risk_outcome_archive/summary.json",
    )
    parser.add_argument(
        "--legacy-event-log",
        default=(
            "outputs/run287_risk_outcome_archive/"
            "risk_outcome_events.jsonl"
        ),
    )
    parser.add_argument(
        "--paper-integrity",
        default=(
            "outputs/daily_simulated_fill_ledger/"
            "snapshot_integrity.json"
        ),
    )
    parser.add_argument(
        "--paper-integrity-verifier-receipt",
        default=(
            "outputs/full_rebuild_logs/"
            "daily_paper_integrity_verifier_receipt.json"
        ),
    )
    parser.add_argument(
        "--paper-immutable-head-selection",
        default=(
            "outputs/full_rebuild_logs/"
            "daily_paper_immutable_head_selection.json"
        ),
    )
    parser.add_argument(
        "--allow-risk-outcome-genesis-bootstrap",
        action="store_true",
    )
    parser.add_argument(
        "--allow-quarantined-legacy-outcome-parent",
        action="store_true",
    )
    parser.add_argument(
        "--output",
        default=(
            "outputs/run287_risk_outcome_parent_preflight/receipt.json"
        ),
    )
    parser.add_argument("--generated-at-utc", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        receipt, exit_code = build_receipt(
            event_name=args.event_name,
            source_commit_sha=args.source_commit_sha,
            source_run_id=args.source_run_id,
            source_run_attempt=args.source_run_attempt,
            source_job_key=args.source_job_key,
            session_date=args.session_date,
            remote_head_discovery_confirmed=(
                args.remote_head_discovery_confirmed
            ),
            remote_committed_head_count=(
                args.remote_committed_head_count
            ),
            remote_legacy_outcome_state=(
                args.remote_legacy_outcome_state
            ),
            legacy_summary_path=args.legacy_summary,
            legacy_event_log_path=args.legacy_event_log,
            paper_integrity_path=args.paper_integrity,
            paper_integrity_verifier_receipt_path=(
                args.paper_integrity_verifier_receipt
            ),
            paper_immutable_head_selection_path=(
                args.paper_immutable_head_selection
            ),
            allow_risk_outcome_genesis_bootstrap=(
                args.allow_risk_outcome_genesis_bootstrap
            ),
            allow_quarantined_legacy_outcome_parent=(
                args.allow_quarantined_legacy_outcome_parent
            ),
            generated_at_utc=args.generated_at_utc or None,
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        receipt = blocked_receipt(args=args, reason=str(exc))
        exit_code = 2
    write_receipt(args.output, receipt)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
