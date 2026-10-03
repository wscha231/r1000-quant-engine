#!/usr/bin/env python3
"""Build a manifest and append-only index for earnings estimate archives."""
from __future__ import annotations

import argparse
import base64
import binascii
import csv
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "earnings-estimate-archive-manifest-v1"
TRANSACTION_MARKER_NAME = "collector_transaction.json"
TRANSACTION_MARKER_SCHEMA = "earnings-estimate-publication-marker-v1"


def require_complete_collector_transaction(directory: Path) -> dict[str, Any]:
    """A retained marker travels with the archive/checkpoint in cache and Drive.

    Pending or malformed evidence is never cleared by a retry. Recovery needs
    an explicitly verified state repair; timestamps or an old summary are not proof.
    """
    path = directory / TRANSACTION_MARKER_NAME
    if not path.exists():
        return {}
    try:
        marker = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(marker, dict)
                or marker.get("schema_version") != TRANSACTION_MARKER_SCHEMA
                or marker.get("status") not in {"committed", "rolled_back"}
                or not marker.get("commit_id")):
            raise ValueError("incomplete marker")
        return marker
    except (OSError, ValueError) as exc:
        raise ValueError("incomplete_collector_transaction") from exc


def require_consistent_collection_acknowledgement(
    checkpoint_path: Path,
    queue_path: Path,
    *,
    verify_planned_queue: bool = False,
) -> None:
    """Reject checkpoint/queue splits before replay or collection.

    A planner may legitimately regenerate a missing queue from a separately
    verified accepted checkpoint. Once a plan exists, however, the collector
    must bind the queue bytes to the checkpoint that produced them.
    """
    if verify_planned_queue and checkpoint_path.is_file() and not queue_path.is_file():
        raise ValueError("planned_collection_queue_missing")
    if not checkpoint_path.is_file() or not queue_path.is_file():
        return
    checkpoint = load_json(checkpoint_path)
    if verify_planned_queue:
        planned_hash = str(checkpoint.get("planned_queue_sha256") or "")
        if planned_hash and sha256_file(queue_path) != planned_hash:
            raise ValueError("planned_collection_queue_hash_mismatch")
    ack = checkpoint.get("last_collection_attempt_ack") or {}
    if not isinstance(ack, dict) or ack.get("status") != "acknowledged":
        return
    with queue_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    states = {str(row.get("ticker") or "").upper().strip(): row
              for row in checkpoint.get("ticker_states", [])}
    for row in rows:
        prior = states.get(str(row.get("ticker") or "").upper().strip())
        if prior is not None and (
            int(prior.get("selection_count") or 0) != int(row.get("selection_count") or 0)
            or str(prior.get("last_selected_at_utc") or "") != str(row.get("last_selected_at_utc") or "")
        ):
            raise ValueError("incomplete_legacy_collector_transaction")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    record: dict[str, Any] = {
        "path": display_path(path),
        "exists": path.exists(),
    }
    if path.exists() and path.is_file():
        record.update(
            {
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return record


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def require_verified_collector_state(
    directory: Path,
    *,
    summary_path: Path,
    checkpoint_path: Path,
    queue_path: Path,
    signals_path: Path | None = None,
    allow_missing_queue: bool = False,
) -> dict[str, Any]:
    """Bind restart/planner state to the last durable collector transaction."""
    marker = require_complete_collector_transaction(directory)
    summary_payload = load_json(summary_path) if summary_path.is_file() else {}
    checkpoint_payload = load_json(checkpoint_path) if checkpoint_path.is_file() else {}
    ack = (
        checkpoint_payload.get("last_collection_attempt_ack")
        if isinstance(checkpoint_payload, dict)
        else None
    )
    transaction_hint = (
        summary_payload.get("transaction_commit")
        if isinstance(summary_payload, dict)
        else None
    )

    if not marker:
        if (
            isinstance(transaction_hint, dict) and transaction_hint
        ) or (
            isinstance(ack, dict) and ack.get("status") == "acknowledged"
        ):
            raise ValueError("missing_collector_transaction_marker")
        return {
            "state": "legacy_or_empty",
            "commit_id": "",
            "summary_sha256": "",
            "attempt_id": "",
            "checkpoint_sha256": "",
        }

    if marker.get("status") == "rolled_back":
        return {
            "state": "rolled_back",
            "commit_id": str(marker.get("commit_id") or ""),
            "summary_sha256": str(marker.get("summary_sha256") or ""),
            "attempt_id": "",
            "checkpoint_sha256": "",
        }

    if marker.get("status") != "committed":
        raise ValueError("incomplete_collector_transaction")
    if (
        not summary_path.is_file()
        or not isinstance(summary_payload, dict)
        or not str(summary_payload.get("status") or "")
    ):
        raise ValueError("missing_or_invalid_collector_summary")
    if (
        not marker.get("summary_sha256")
        or sha256_file(summary_path) != str(marker.get("summary_sha256"))
    ):
        raise ValueError("collector_summary_hash_mismatch")

    transaction = summary_payload.get("transaction_commit")
    if (
        not isinstance(transaction, dict)
        or transaction.get("schema_version") != "earnings-estimate-collector-transaction-v2"
        or str(transaction.get("commit_id") or "") != str(marker.get("commit_id") or "")
    ):
        raise ValueError("collector_transaction_identity_mismatch")

    expected_snapshot_hash = str(transaction.get("snapshot_sha256") or "")
    if expected_snapshot_hash:
        snapshot_name = Path(str(summary_payload.get("snapshot_path") or "")).name
        snapshot_path = directory / snapshot_name if snapshot_name else Path()
        if (
            not snapshot_name
            or not snapshot_path.is_file()
            or sha256_file(snapshot_path) != expected_snapshot_hash
        ):
            raise ValueError("collector_snapshot_hash_mismatch")

    expected_signals_hash = str(transaction.get("signals_sha256") or "")
    if expected_signals_hash:
        if (
            signals_path is None
            or not signals_path.is_file()
            or sha256_file(signals_path) != expected_signals_hash
        ):
            raise ValueError("collector_signals_hash_mismatch")

    expected_checkpoint_hash = str(transaction.get("checkpoint_sha256") or "")
    expected_queue_hash = str(transaction.get("queue_sha256") or "")
    checkpoint_hash = sha256_file(checkpoint_path) if checkpoint_path.is_file() else ""
    queue_hash = sha256_file(queue_path) if queue_path.is_file() else ""
    expected_attempt = str(transaction.get("attempt_id") or "")

    def acknowledgement_matches() -> bool:
        if not expected_attempt:
            return True
        return bool(
            isinstance(ack, dict)
            and ack.get("status") == "acknowledged"
            and str(ack.get("attempt_id") or "") == expected_attempt
        )

    accepted_checkpoint = (
        not expected_checkpoint_hash or checkpoint_hash == expected_checkpoint_hash
    )
    accepted_queue = (
        not expected_queue_hash
        or queue_hash == expected_queue_hash
        or (allow_missing_queue and not queue_path.is_file())
    )
    if accepted_checkpoint and accepted_queue:
        if not acknowledgement_matches():
            raise ValueError("collector_checkpoint_attempt_mismatch")
        return {
            "state": "accepted",
            "commit_id": str(marker.get("commit_id") or ""),
            "summary_sha256": str(marker.get("summary_sha256") or ""),
            "attempt_id": expected_attempt,
            "checkpoint_sha256": expected_checkpoint_hash,
            "checkpoint_bytes_base64": (
                base64.b64encode(checkpoint_path.read_bytes()).decode("ascii")
                if expected_checkpoint_hash else ""
            ),
        }

    if checkpoint_path.is_file() and queue_path.is_file():
        parent = checkpoint_payload.get("planning_parent_transaction")
        planned_queue_hash = str(checkpoint_payload.get("planned_queue_sha256") or "")
        if (
            isinstance(parent, dict)
            and str(parent.get("commit_id") or "") == str(marker.get("commit_id") or "")
            and str(parent.get("summary_sha256") or "") == str(marker.get("summary_sha256") or "")
            and str(parent.get("checkpoint_sha256") or "") == expected_checkpoint_hash
            and str(parent.get("attempt_id") or "") == expected_attempt
            and planned_queue_hash
            and planned_queue_hash == queue_hash
            and acknowledgement_matches()
        ):
            # A copied parent hash is not the accepted checkpoint. Preserve
            # its actual bytes across planning, then bind unchanged collection
            # acknowledgement/state to those bytes before consuming the plan.
            encoded_parent = parent.get("checkpoint_bytes_base64")
            try:
                if not isinstance(encoded_parent, str) or not expected_checkpoint_hash:
                    raise ValueError("missing accepted checkpoint bytes")
                accepted_bytes = base64.b64decode(encoded_parent, validate=True)
                if hashlib.sha256(accepted_bytes).hexdigest() != expected_checkpoint_hash:
                    raise ValueError("accepted checkpoint hash mismatch")
                accepted_payload = json.loads(accepted_bytes)
                if not isinstance(accepted_payload, dict):
                    raise ValueError("invalid accepted checkpoint")
                if checkpoint_payload.get("last_collection_attempt_ack") != accepted_payload.get("last_collection_attempt_ack"):
                    raise ValueError("planning changed acknowledgement")

                def selection_state(payload: dict[str, Any]) -> dict[str, tuple[int, str]]:
                    rows = payload.get("ticker_states")
                    if not isinstance(rows, list):
                        raise ValueError("invalid checkpoint states")
                    states: dict[str, tuple[int, str]] = {}
                    for row in rows:
                        if not isinstance(row, dict) or not isinstance(row.get("ticker"), str):
                            raise ValueError("invalid checkpoint ticker")
                        ticker = row["ticker"].upper().strip()
                        count = row.get("selection_count")
                        last = row.get("last_selected_at_utc")
                        if (not ticker or ticker in states or type(count) is not int
                                or count < 0 or not isinstance(last, str)):
                            raise ValueError("invalid checkpoint selection state")
                        states[ticker] = (count, last)
                    return states

                accepted_states = selection_state(accepted_payload)
                planned_states = selection_state(checkpoint_payload)
                if any(value != accepted_states.get(ticker, (0, ""))
                       for ticker, value in planned_states.items()):
                    raise ValueError("planning changed collection state")
            except (ValueError, TypeError, binascii.Error) as exc:
                raise ValueError("collector_planning_parent_state_mismatch") from exc
            return {
                "state": "planned",
                "commit_id": str(marker.get("commit_id") or ""),
                "summary_sha256": str(marker.get("summary_sha256") or ""),
                "attempt_id": expected_attempt,
                "checkpoint_sha256": expected_checkpoint_hash,
                "checkpoint_bytes_base64": encoded_parent,
            }

    raise ValueError("collector_transaction_state_mismatch")


def latest_snapshot(snapshot_dir: Path, summary: dict[str, Any]) -> Path:
    summary_path = str(summary.get("snapshot_path") or "")
    if summary_path:
        path = repo_path(summary_path)
        if path.exists():
            return path
    candidates = sorted(snapshot_dir.glob("estimates_*.parquet"))
    return candidates[-1] if candidates else snapshot_dir / "estimates_missing.parquet"


def has_unmasked_secret_text(text: str) -> bool:
    patterns = [
        r"(?i)(?:apikey|token)=((?!\*\*\*)[A-Za-z0-9._-]{6,})",
        r"(?i)api key as\s+((?!\*\*\*)[A-Za-z0-9._-]{6,})",
        r"gh[opsu]_[A-Za-z0-9_]{12,}",
    ]
    return any(re.search(pattern, text) for pattern in patterns)


def scan_text_file(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {"path": display_path(path), "exists": path.exists(), "unmasked_secret_pattern_found": False}
    text = path.read_text(encoding="utf-8", errors="replace")
    return {
        "path": display_path(path),
        "exists": True,
        "unmasked_secret_pattern_found": has_unmasked_secret_text(text),
        "masked_url_credential_markers_present": bool(re.search(r"(?i)(apikey|token)=\*\*\*", text)),
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def append_index(index_path: Path, entry: dict[str, Any]) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    key = (entry.get("run_id"), entry.get("run_attempt"), entry.get("fetch_date"))
    rows: list[dict[str, Any]] = []
    if index_path.exists():
        for line in index_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            row_key = (row.get("run_id"), row.get("run_attempt"), row.get("fetch_date"))
            if row_key != key:
                rows.append(row)
    rows.append(entry)
    index_path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")


def build_manifest(
    *,
    snapshot_dir: str,
    signals: str,
    summary: str,
    collector_log: str,
    manifest: str,
    index: str,
    run_id: str,
    run_attempt: str,
    head_sha: str,
    ref: str,
    workflow: str,
    artifact_name: str,
    shard_id: str = "",
    shard_file: str = "",
    shard_mode: str = "",
    queue_summary: str = "outputs/earnings_estimates_daily/incremental_universe_summary.json",
    queue_checkpoint: str = "data_pit/events/earnings_estimates/collection_checkpoint.json",
    queue_csv: str = "outputs/earnings_estimates_daily/collection_queue.csv",
    queue_report: str = "outputs/earnings_estimates_daily/collection_queue_report.md",
) -> dict[str, Any]:
    snapshot_dir_path = repo_path(snapshot_dir)
    signals_path = repo_path(signals)
    summary_path = repo_path(summary)
    collector_log_path = repo_path(collector_log)
    manifest_path = repo_path(manifest)
    index_path = repo_path(index)
    queue_summary_path = repo_path(queue_summary)
    queue_checkpoint_path = repo_path(queue_checkpoint)
    queue_csv_path = repo_path(queue_csv)
    queue_report_path = repo_path(queue_report)
    summary_payload = load_json(summary_path)
    queue_payload = load_json(queue_summary_path)
    snapshot_path = latest_snapshot(snapshot_dir_path, summary_payload)
    text_scans = [
        scan_text_file(summary_path),
        scan_text_file(collector_log_path),
        scan_text_file(queue_summary_path),
        scan_text_file(queue_report_path),
    ]
    unmasked_secret = any(scan.get("unmasked_secret_pattern_found") for scan in text_scans)
    fetch_date = str(summary_payload.get("feature_summary", {}).get("as_of_date") or "")
    if not fetch_date:
        snapshot_name = snapshot_path.stem
        if snapshot_name.startswith("estimates_") and len(snapshot_name) >= len("estimates_YYYYMMDD"):
            raw_date = snapshot_name.replace("estimates_", "")[:8]
            fetch_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "research_only": True,
        "forward_only": True,
        "backtest_acceptance_allowed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "fullrun_dispatched": False,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "head_sha": head_sha,
        "ref": ref,
        "workflow": workflow,
        "artifact_name": artifact_name,
        "shard_id": shard_id,
        "shard_file": shard_file,
        "shard_mode": shard_mode,
        "fetch_date": fetch_date,
        "collector_status": summary_payload.get("status", "missing_summary"),
        "collector_reason": summary_payload.get("reason", ""),
        "ticker_count_requested": summary_payload.get("ticker_count_requested", 0),
        "request_snapshot_rows": summary_payload.get("request_snapshot_rows", summary_payload.get("snapshot_rows", 0)),
        "request_has_forward_estimate_rows": summary_payload.get(
            "request_has_forward_estimate_rows",
            summary_payload.get("has_forward_estimate_rows", 0),
        ),
        "request_estimate_coverage_ratio": summary_payload.get(
            "request_estimate_coverage_ratio",
            summary_payload.get("estimate_coverage_ratio", 0.0),
        ),
        "snapshot_rows": summary_payload.get("snapshot_rows", 0),
        "has_forward_estimate_rows": summary_payload.get("has_forward_estimate_rows", 0),
        "estimate_coverage_ratio": summary_payload.get("estimate_coverage_ratio", 0.0),
        "stored_estimate_coverage_ratio": summary_payload.get(
            "stored_estimate_coverage_ratio",
            summary_payload.get("estimate_coverage_ratio", 0.0),
        ),
        "same_day_snapshot_merged": summary_payload.get("same_day_snapshot_merged", False),
        "same_day_existing_rows": summary_payload.get("same_day_existing_rows", 0),
        "same_day_current_rows": summary_payload.get("same_day_current_rows", 0),
        "same_day_merged_rows": summary_payload.get("same_day_merged_rows", summary_payload.get("snapshot_rows", 0)),
        "coverage_ratio": summary_payload.get("coverage_ratio", 0.0),
        "fetch_sources": summary_payload.get("fetch_sources", []),
        "vendor_order": summary_payload.get("vendor_order", []),
        "collector_max_errors": summary_payload.get("max_errors", ""),
        "entitlement_circuit_threshold": summary_payload.get("entitlement_circuit_threshold", 0),
        "vendor_entitlement_circuit": summary_payload.get("vendor_entitlement_circuit", {}),
        "vendor_estimate_access": summary_payload.get("vendor_estimate_access", False),
        "vendor_blocked_errors": summary_payload.get("vendor_blocked_errors", False),
        "error_count": summary_payload.get("error_count", 0),
        "error_budget_count": summary_payload.get("error_budget_count", summary_payload.get("error_count", 0)),
        "entitlement_error_warn_only_count": summary_payload.get("entitlement_error_warn_only_count", 0),
        "entitlement_error_probe_count": summary_payload.get("entitlement_error_probe_count", 0),
        "ticker_count_attempted": summary_payload.get("ticker_count_attempted", 0),
        "collection_attempt_ack": summary_payload.get("collection_attempt_ack", {}),
        "collection_queue_status": queue_payload.get("status", "missing_queue_summary"),
        "collection_queue_schema_version": queue_payload.get("schema_version", ""),
        "collection_queue_selected_ticker_count": queue_payload.get("output_ticker_count", 0),
        "collection_universe_ticker_count": queue_payload.get("current_universe_ticker_count", 0),
        "collection_eligible_ticker_count": queue_payload.get("eligible_universe_ticker_count", 0),
        "collection_non_equity_placeholder_ticker_count": queue_payload.get(
            "non_equity_placeholder_ticker_count", 0
        ),
        "collection_universe_source_mode": queue_payload.get("universe_source_mode", ""),
        "collection_universe_sha256": queue_payload.get("canonical_universe", {}).get("sha256", ""),
        "collection_snapshot_source_aggregate_sha256": queue_payload.get(
            "snapshot_source_aggregate_sha256", ""
        ),
        "collection_queue_state_counts": queue_payload.get("queue_state_counts", {}),
        "collection_selection_reason_counts": queue_payload.get("selection_reason_counts", {}),
        "missing_vendor_coverage_policy": "neutral",
        "persistence": {
            "github_artifact_uploaded_by_workflow": True,
            "github_artifact_retention_days": 30,
            "gdrive_sync_attempted_by_workflow": True,
            "cache_saved_by_workflow": True,
            "index_path": display_path(index_path),
        },
        "files": {
            "snapshot": file_record(snapshot_path),
            "signals": file_record(signals_path),
            "summary": file_record(summary_path),
            "collector_transaction": file_record(snapshot_dir_path / TRANSACTION_MARKER_NAME),
            "collector_log": file_record(collector_log_path),
            "collection_queue_summary": file_record(queue_summary_path),
            "collection_queue_checkpoint": file_record(queue_checkpoint_path),
            "collection_queue_csv": file_record(queue_csv_path),
            "collection_queue_report": file_record(queue_report_path),
        },
        "text_secret_scan": {
            "unmasked_secret_pattern_found": unmasked_secret,
            "scans": text_scans,
        },
        "verdict": "archive_manifest_written" if not unmasked_secret else "blocked_unmasked_secret_pattern",
    }

    ack = summary_payload.get("collection_attempt_ack") or {}
    transaction = summary_payload.get("transaction_commit") or {}
    transaction_failures: list[str] = []
    summary_valid = bool(
        summary_path.is_file()
        and isinstance(summary_payload, dict)
        and str(summary_payload.get("status") or "")
    )
    summary_failures: list[str] = []
    if not summary_path.is_file():
        summary_failures.append("missing_summary")
    elif not summary_valid:
        summary_failures.append("invalid_summary")
    marker: dict[str, Any] = {}
    for directory in {snapshot_dir_path, queue_checkpoint_path.parent}:
        try:
            observed = require_complete_collector_transaction(directory)
            if observed.get("status") == "rolled_back":
                transaction_failures.append("collector_transaction_rolled_back")
            if directory == snapshot_dir_path:
                marker = observed
        except ValueError:
            transaction_failures.append("incomplete_collector_transaction")
    transaction_present = bool(
        isinstance(transaction, dict)
        and transaction.get("schema_version") == "earnings-estimate-collector-transaction-v2"
    )
    transaction_required = bool(
        transaction_present
        or (isinstance(ack, dict) and ack.get("status") == "acknowledged")
        or marker.get("status") == "committed"
    )
    if transaction_present:
        if (marker.get("status") != "committed"
                or marker.get("commit_id") != transaction.get("commit_id")
                or marker.get("summary_sha256") != payload["files"]["summary"].get("sha256")):
            transaction_failures.append("collector_final_marker_mismatch")
    if transaction_required:
        if not isinstance(transaction, dict) or not transaction:
            transaction_failures.append("missing_transaction_commit")
            transaction = {}
        expected_attempt = str(summary_payload.get("collection_attempt_id") or "")
        ack_attempt = str(ack.get("attempt_id") or "") if isinstance(ack, dict) else ""
        tx_attempt = str(transaction.get("attempt_id") or "")
        if not expected_attempt or ack_attempt != expected_attempt or tx_attempt != expected_attempt:
            transaction_failures.append("attempt_id_mismatch")
        logical_id = str(summary_payload.get("collection_attempt_logical_id") or "")
        tx_logical_id = str(transaction.get("logical_attempt_id") or "")
        if logical_id != tx_logical_id:
            transaction_failures.append("logical_attempt_id_mismatch")
        if run_id and logical_id != str(run_id):
            transaction_failures.append("run_id_mismatch")

        expected_hashes = {
            "snapshot_sha256": payload["files"]["snapshot"].get("sha256", ""),
            "signals_sha256": payload["files"]["signals"].get("sha256", ""),
            "checkpoint_sha256": payload["files"]["collection_queue_checkpoint"].get("sha256", ""),
            "queue_sha256": payload["files"]["collection_queue_csv"].get("sha256", ""),
        }
        for field, actual_hash in expected_hashes.items():
            expected_hash = str(transaction.get(field) or "")
            if expected_hash and (not actual_hash or expected_hash != actual_hash):
                transaction_failures.append(f"{field}_mismatch")

        if str(transaction.get("checkpoint_sha256") or ""):
            checkpoint_payload = load_json(queue_checkpoint_path)
            checkpoint_ack = (
                checkpoint_payload.get("last_collection_attempt_ack")
                if isinstance(checkpoint_payload, dict)
                else None
            )
            if not isinstance(checkpoint_ack, dict):
                transaction_failures.append("checkpoint_ack_missing")
            else:
                if checkpoint_ack.get("status") != "acknowledged":
                    transaction_failures.append("checkpoint_ack_not_acknowledged")
                if str(checkpoint_ack.get("attempt_id") or "") != expected_attempt:
                    transaction_failures.append("checkpoint_attempt_id_mismatch")

    payload["transaction_integrity"] = {
        "required": transaction_required,
        "verified": bool(transaction_required and not transaction_failures),
        "failures": transaction_failures,
        "attempt_id": str(summary_payload.get("collection_attempt_id") or ""),
        "logical_attempt_id": str(summary_payload.get("collection_attempt_logical_id") or ""),
    }
    ack_status = str(ack.get("status") or "") if isinstance(ack, dict) else ""
    if summary_valid and ack_status not in {"acknowledged", "disabled"}:
        summary_failures.append("collection_attempt_not_accepted")
    publication_failures = sorted(set(summary_failures + transaction_failures))
    publishable = bool(not unmasked_secret and summary_valid and not publication_failures)
    payload["publishable"] = publishable
    payload["publication_failures"] = publication_failures
    payload["persistence"]["accepted_publication_allowed"] = publishable
    if unmasked_secret:
        payload["verdict"] = "blocked_unmasked_secret_pattern"
    elif not summary_valid:
        payload["verdict"] = "blocked_missing_or_invalid_summary"
    elif transaction_failures:
        payload["verdict"] = "blocked_transaction_mismatch"
    elif summary_failures:
        payload["verdict"] = "blocked_non_publishable_collector_state"
    else:
        payload["verdict"] = "archive_manifest_written"
    write_json(manifest_path, payload)
    index_entry = {
        "schema_version": SCHEMA_VERSION,
        "indexed_at_utc": payload["generated_at_utc"],
        "run_id": run_id,
        "run_attempt": run_attempt,
        "head_sha": head_sha,
        "ref": ref,
        "workflow": workflow,
        "artifact_name": artifact_name,
        "shard_id": shard_id,
        "shard_file": shard_file,
        "shard_mode": shard_mode,
        "fetch_date": fetch_date,
        "collector_status": payload["collector_status"],
        "ticker_count_requested": payload["ticker_count_requested"],
        "request_snapshot_rows": payload["request_snapshot_rows"],
        "request_has_forward_estimate_rows": payload["request_has_forward_estimate_rows"],
        "snapshot_rows": payload["snapshot_rows"],
        "has_forward_estimate_rows": payload["has_forward_estimate_rows"],
        "estimate_coverage_ratio": payload["estimate_coverage_ratio"],
        "stored_estimate_coverage_ratio": payload["stored_estimate_coverage_ratio"],
        "same_day_snapshot_merged": payload["same_day_snapshot_merged"],
        "collector_max_errors": payload["collector_max_errors"],
        "entitlement_circuit_threshold": payload["entitlement_circuit_threshold"],
        "entitlement_circuit_tripped_vendors": payload.get("vendor_entitlement_circuit", {}).get(
            "tripped_vendors", []
        ),
        "estimated_estimate_http_requests_avoided": payload.get("vendor_entitlement_circuit", {}).get(
            "estimated_estimate_http_requests_avoided", 0
        ),
        "error_count": payload["error_count"],
        "error_budget_count": payload["error_budget_count"],
        "entitlement_error_warn_only_count": payload["entitlement_error_warn_only_count"],
        "entitlement_error_probe_count": payload["entitlement_error_probe_count"],
        "collection_queue_status": payload["collection_queue_status"],
        "collection_queue_selected_ticker_count": payload["collection_queue_selected_ticker_count"],
        "collection_attempt_acknowledged_ticker_count": payload.get("collection_attempt_ack", {}).get(
            "acknowledged_ticker_count", 0
        ),
        "collection_universe_ticker_count": payload["collection_universe_ticker_count"],
        "collection_eligible_ticker_count": payload["collection_eligible_ticker_count"],
        "collection_non_equity_placeholder_ticker_count": payload[
            "collection_non_equity_placeholder_ticker_count"
        ],
        "collection_universe_source_mode": payload["collection_universe_source_mode"],
        "collection_universe_sha256": payload["collection_universe_sha256"],
        "collection_queue_summary_sha256": payload["files"]["collection_queue_summary"].get("sha256", ""),
        "collection_queue_checkpoint_sha256": payload["files"]["collection_queue_checkpoint"].get("sha256", ""),
        "collection_queue_csv_sha256": payload["files"]["collection_queue_csv"].get("sha256", ""),
        "snapshot_sha256": payload["files"]["snapshot"].get("sha256", ""),
        "signals_sha256": payload["files"]["signals"].get("sha256", ""),
        "manifest_path": display_path(manifest_path),
        "backtest_acceptance_allowed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
    }
    append_index(index_path, index_entry)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-dir", default="data_pit/events/earnings_estimates")
    parser.add_argument("--signals", default="data_pit/events/earnings_revision_signals.parquet")
    parser.add_argument("--summary", default="outputs/earnings_estimates_daily/summary.json")
    parser.add_argument("--collector-log", default="outputs/earnings_estimates_daily/collector.log")
    parser.add_argument("--manifest", default="outputs/earnings_estimates_daily/archive_manifest.json")
    parser.add_argument("--index", default="data_pit/events/earnings_estimates/archive_index.jsonl")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--run-attempt", default="")
    parser.add_argument("--head-sha", default="")
    parser.add_argument("--ref", default="")
    parser.add_argument("--workflow", default="earnings_estimates_daily.yml")
    parser.add_argument("--artifact-name", default="")
    parser.add_argument("--shard-id", default="")
    parser.add_argument("--shard-file", default="")
    parser.add_argument("--shard-mode", default="")
    parser.add_argument("--queue-summary", default="outputs/earnings_estimates_daily/incremental_universe_summary.json")
    parser.add_argument("--queue-checkpoint", default="data_pit/events/earnings_estimates/collection_checkpoint.json")
    parser.add_argument("--queue-csv", default="outputs/earnings_estimates_daily/collection_queue.csv")
    parser.add_argument("--queue-report", default="outputs/earnings_estimates_daily/collection_queue_report.md")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_manifest(
        snapshot_dir=args.snapshot_dir,
        signals=args.signals,
        summary=args.summary,
        collector_log=args.collector_log,
        manifest=args.manifest,
        index=args.index,
        run_id=args.run_id,
        run_attempt=args.run_attempt,
        head_sha=args.head_sha,
        ref=args.ref,
        workflow=args.workflow,
        artifact_name=args.artifact_name,
        shard_id=args.shard_id,
        shard_file=args.shard_file,
        shard_mode=args.shard_mode,
        queue_summary=args.queue_summary,
        queue_checkpoint=args.queue_checkpoint,
        queue_csv=args.queue_csv,
        queue_report=args.queue_report,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    if payload["text_secret_scan"]["unmasked_secret_pattern_found"]:
        return 1
    return 0 if payload.get("publishable") is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
