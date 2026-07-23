#!/usr/bin/env python3
"""Build the fail-closed manifest for an accepted Run287 paper publication."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
SCHEMA_VERSION = "run287-accepted-publication-manifest-v1"
READY_STATUS = "READY_ACCEPTED_PUBLICATION_REVIEW_ONLY"
PORTFOLIOS = ("main", "concentrated")
REQUIRED_FILES = {
    "main_target": "reports/operating_main_target_book.csv",
    "concentrated_target": "reports/operating_concentrated_target_book.csv",
    "paper_accepted_publication": "daily_simulated_fill_ledger/accepted_publication.json",
    "paper_snapshot_integrity": "daily_simulated_fill_ledger/snapshot_integrity.json",
    "risk_outcome_summary": "run287_risk_outcome_archive/summary.json",
    "operating_scorecard": "run287_operating_scorecard/operating_scorecard.json",
    "promotion_gate": "run287_promotion_gate/promotion_gate.json",
    "user_target_weights": "user_current/02_target_weights.csv",
    "user_order_preview": "user_current/03_order_preview.csv",
    "user_rebalance_decision": "user_current/08_rebalance_decision.json",
}
TARGET_FILES = {
    "main": REQUIRED_FILES["main_target"],
    "concentrated": REQUIRED_FILES["concentrated_target"],
}
PREVIEW_HASHED_FILES = {
    "orders_preview_sha256": ("orders_preview.csv", "orders"),
    "target_weights_sha256": ("target_weights.csv", "target_weights"),
}
READY_OUTCOME_FALSE_FIELDS = (
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
# A skipped archive is less capable than a ready archive, never more
# permissive. Keep the complete safety envelope fail-closed when there were no
# observations to resolve.
SKIPPED_OUTCOME_FALSE_FIELDS = READY_OUTCOME_FALSE_FIELDS
READY_OUTCOME_OUTPUTS = {
    "event_log_sha256": ("risk_outcome_events.jsonl", "risk_outcome_event_log"),
    "current_status_sha256": ("current_status.csv", "risk_outcome_current_status"),
    "price_universe_sha256": ("price_universe.csv", "risk_outcome_price_universe"),
}
PROMOTION_SOURCE_FILES = {
    "contract_sha256": "data_static/run287_promotion_gate_contract.json",
    "state_sha256": "data_static/run287_promotion_state.json",
    "base_evidence_sha256": "data_static/run287_promotion_evidence_current.json",
}
REQUIRED_GATE_OBSERVED_FILES = {
    "daily_simulated_fill_ledger/snapshot_integrity.json":
        "paper_snapshot_integrity",
    "run287_operating_scorecard/operating_scorecard.json":
        "operating_scorecard",
    "run287_risk_outcome_archive/summary.json": "risk_outcome_summary",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def require_file(path: Path, label: str) -> str:
    if not path.is_file() or path.stat().st_size <= 0:
        raise ValueError(f"accepted_publication_file_missing:{label}")
    return sha256_file(path)


def valid_commit_sha(value: str) -> bool:
    return len(value) == 40 and all(char in "0123456789abcdef" for char in value.lower())


def valid_sha256(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text.lower())


def accepted_path(
    latest_run: Path,
    value: Any,
    *,
    label: str,
) -> Path:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError(f"accepted_publication_path_missing:{label}")
    path = Path(raw)
    resolved = (path if path.is_absolute() else ROOT / path).resolve()
    try:
        resolved.relative_to(latest_run)
    except ValueError as exc:
        raise ValueError(f"accepted_publication_path_outside_latest_run:{label}") from exc
    return resolved


def bind_attested_file(
    *,
    latest_run: Path,
    file_hashes: dict[str, dict[str, str]],
    label: str,
    path: Path,
    expected_sha256: Any,
) -> str:
    expected = str(expected_sha256 or "")
    if not valid_sha256(expected):
        raise ValueError(f"accepted_publication_sha256_invalid:{label}")
    actual = require_file(path, label)
    if actual != expected:
        raise ValueError(f"accepted_publication_sha256_mismatch:{label}")
    try:
        relative = path.resolve().relative_to(latest_run).as_posix()
    except ValueError as exc:
        raise ValueError(f"accepted_publication_path_outside_latest_run:{label}") from exc
    file_hashes[label] = {"path": relative, "sha256": actual}
    return actual


def gate_observed_path(latest_run: Path, raw_path: str) -> Path:
    if raw_path.startswith("repo:"):
        relative = raw_path.removeprefix("repo:")
        base = ROOT.resolve()
    else:
        relative = raw_path
        base = latest_run.resolve()
    candidate = Path(relative)
    if not relative or candidate.is_absolute():
        raise ValueError(f"promotion_gate_observed_path_invalid:{raw_path}")
    resolved = (base / candidate).resolve()
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise ValueError(
            f"promotion_gate_observed_path_outside_root:{raw_path}"
        ) from exc
    return resolved


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.candidate-",
        dir=path.parent,
    )
    candidate = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(candidate, path)
    finally:
        if candidate.exists():
            candidate.unlink()


def build_manifest(
    *,
    latest_run: Path,
    source_commit_sha: str,
    workflow_identity: str,
    run_id: str,
    run_attempt: str,
    expected_promotion_gate_sha256: str,
) -> dict[str, Any]:
    latest_run = latest_run.resolve()
    if not latest_run.is_dir():
        raise ValueError("latest_run_missing")
    if not valid_commit_sha(source_commit_sha):
        raise ValueError("source_commit_sha_invalid")
    if not workflow_identity.strip() or not run_id.strip() or not run_attempt.strip():
        raise ValueError("workflow_identity_incomplete")
    if not valid_sha256(expected_promotion_gate_sha256):
        raise ValueError("expected_promotion_gate_sha256_invalid")

    file_hashes: dict[str, dict[str, str]] = {}
    for label, relative in REQUIRED_FILES.items():
        path = latest_run / relative
        file_hashes[label] = {
            "path": relative,
            "sha256": require_file(path, label),
        }
    if (
        file_hashes["promotion_gate"]["sha256"]
        != expected_promotion_gate_sha256
    ):
        raise ValueError("promotion_gate_step_output_sha256_mismatch")

    paper_root = latest_run / "daily_simulated_fill_ledger"
    preview_root = latest_run / "account_ledger_preview"
    try:
        try:
            from tools.run287_paper_ledger_integrity import verify_integrity_manifest
            from tools.run_daily_simulated_fill_ledger import (
                preview_identity,
                verify_accepted_publication,
            )
        except ModuleNotFoundError:
            from run287_paper_ledger_integrity import verify_integrity_manifest
            from run_daily_simulated_fill_ledger import (
                preview_identity,
                verify_accepted_publication,
            )
        paper_manifest = verify_integrity_manifest(paper_root, require=True)
        accepted = verify_accepted_publication(paper_root, preview_root)
    except Exception as exc:
        raise ValueError(f"paper_publication_verification_failed:{type(exc).__name__}:{exc}") from exc
    paper_as_of = str(paper_manifest.get("as_of_date") or "")
    if accepted.get("schema_version") != "run287-paper-accepted-publication-v1":
        raise ValueError("paper_accepted_publication_schema_invalid")
    if accepted.get("as_of_date") != paper_as_of:
        raise ValueError("paper_accepted_publication_as_of_mismatch")
    if accepted.get("transaction_mode") not in {"MARK_ONLY", "SELECTED_TARGET"}:
        raise ValueError("paper_accepted_publication_transaction_mode_invalid")
    if accepted.get("review_only") is not True:
        raise ValueError("paper_accepted_publication_not_review_only")
    if accepted.get("live_trading_enabled") is not False:
        raise ValueError("paper_accepted_publication_live_enabled")
    if accepted.get("production_mutation_allowed") is not False:
        raise ValueError("paper_accepted_publication_production_enabled")

    accepted_portfolios = accepted.get("portfolios")
    if not isinstance(accepted_portfolios, dict):
        raise ValueError("paper_accepted_publication_portfolios_invalid")
    for portfolio in PORTFOLIOS:
        row = accepted_portfolios.get(portfolio)
        if not isinstance(row, dict):
            raise ValueError(f"paper_accepted_publication_portfolio_missing:{portfolio}")

        source_path = accepted_path(
            latest_run,
            row.get("source_target_path"),
            label=f"{portfolio}_source_target",
        )
        published_path = accepted_path(
            latest_run,
            row.get("published_target_path"),
            label=f"{portfolio}_published_target",
        )
        expected_published_path = (latest_run / TARGET_FILES[portfolio]).resolve()
        if published_path != expected_published_path:
            raise ValueError(
                f"paper_accepted_publication_published_target_path_mismatch:{portfolio}"
            )
        source_sha256 = bind_attested_file(
            latest_run=latest_run,
            file_hashes=file_hashes,
            label=f"{portfolio}_source_target",
            path=source_path,
            expected_sha256=row.get("source_target_sha256"),
        )
        published_sha256 = bind_attested_file(
            latest_run=latest_run,
            file_hashes=file_hashes,
            label=f"{portfolio}_published_target",
            path=published_path,
            expected_sha256=row.get("published_target_sha256"),
        )
        if source_sha256 != published_sha256:
            raise ValueError(
                f"paper_accepted_publication_source_published_mismatch:{portfolio}"
            )
        fixed_target_label = f"{portfolio}_target"
        if file_hashes[fixed_target_label]["sha256"] != published_sha256:
            raise ValueError(
                f"paper_accepted_publication_fixed_target_mismatch:{portfolio}"
            )

        account_path = paper_root / portfolio / "account_state_latest.json"
        account_sha256 = bind_attested_file(
            latest_run=latest_run,
            file_hashes=file_hashes,
            label=f"{portfolio}_account_state",
            path=account_path,
            expected_sha256=row.get("account_state_sha256"),
        )
        preview_dir = preview_root / portfolio
        preview_manifest_path = preview_dir / "order_batch_manifest.json"
        preview_manifest_sha256 = require_file(
            preview_manifest_path, f"{portfolio}_preview_manifest"
        )
        preview_manifest = read_json(preview_manifest_path)
        file_hashes[f"{portfolio}_preview_manifest"] = {
            "path": preview_manifest_path.resolve().relative_to(latest_run).as_posix(),
            "sha256": preview_manifest_sha256,
        }
        if (
            preview_manifest.get("schema_version")
            != "account-ledger-preview-order-batch-v2"
            or preview_manifest.get("portfolio_kind") != portfolio
            or str(preview_manifest.get("as_of_date") or "") != paper_as_of
        ):
            raise ValueError(f"paper_preview_manifest_contract_invalid:{portfolio}")
        expected_preview_identity = str(
            preview_manifest.get("preview_identity_hash") or ""
        )
        if (
            not valid_sha256(expected_preview_identity)
            or row.get("preview_identity_at_acceptance")
            != expected_preview_identity
        ):
            raise ValueError(f"paper_preview_identity_mismatch:{portfolio}")
        preview_mode = str(preview_manifest.get("preview_mode") or "")
        if (
            preview_mode not in {"NO_NEW_ORDER", "EXECUTABLE_CANDIDATE"}
            or row.get("preview_mode_at_acceptance") != preview_mode
        ):
            raise ValueError(f"paper_preview_mode_mismatch:{portfolio}")
        if (
            preview_manifest.get("accepted_account_sha256") != account_sha256
            or preview_manifest.get("source_target_sha256") != source_sha256
        ):
            raise ValueError(f"paper_preview_input_binding_mismatch:{portfolio}")

        effective_target_path = paper_root / portfolio / "effective_target_latest.csv"
        bind_attested_file(
            latest_run=latest_run,
            file_hashes=file_hashes,
            label=f"{portfolio}_preview_effective_target",
            path=effective_target_path,
            expected_sha256=preview_manifest.get("effective_target_sha256"),
        )
        for hash_field, (filename, label_suffix) in PREVIEW_HASHED_FILES.items():
            bind_attested_file(
                latest_run=latest_run,
                file_hashes=file_hashes,
                label=f"{portfolio}_preview_{label_suffix}",
                path=preview_dir / filename,
                expected_sha256=preview_manifest.get(hash_field),
            )
        import pandas as pd

        recomputed_identity = preview_identity(
            preview_dir=preview_dir,
            account_path=account_path,
            effective_target_path=effective_target_path,
            source_target_path=source_path,
            portfolio=portfolio,
            as_of_date=pd.Timestamp(paper_as_of),
            preview_mode=preview_mode,
        )
        for field, expected_value in recomputed_identity.items():
            if preview_manifest.get(field) != expected_value:
                raise ValueError(
                    f"paper_preview_identity_field_mismatch:{portfolio}:{field}"
                )

    outcome_path = latest_run / REQUIRED_FILES["risk_outcome_summary"]
    outcome = read_json(outcome_path)
    if outcome.get("schema_version") != "run287-risk-outcome-archive-v1":
        raise ValueError("risk_outcome_schema_invalid")
    if str(outcome.get("as_of_date") or "") != paper_as_of:
        raise ValueError("risk_outcome_as_of_mismatch")
    outcome_status = str(outcome.get("status") or "")
    if outcome_status not in {
        "READY_RISK_OUTCOME_ARCHIVE_REVIEW_ONLY",
        "SKIPPED_NO_DECISION_OBSERVATIONS",
    }:
        raise ValueError(f"risk_outcome_not_publishable:{outcome_status}")
    if outcome.get("review_only") is not True:
        raise ValueError("risk_outcome_not_review_only")
    if outcome.get("blockers") != []:
        raise ValueError("risk_outcome_blockers_present")
    common_false_fields = (
        READY_OUTCOME_FALSE_FIELDS
        if outcome_status == "READY_RISK_OUTCOME_ARCHIVE_REVIEW_ONLY"
        else SKIPPED_OUTCOME_FALSE_FIELDS
    )
    for field in common_false_fields:
        if outcome.get(field) is not False:
            raise ValueError(f"risk_outcome_unsafe_flag:{field}")
    if outcome_status == "READY_RISK_OUTCOME_ARCHIVE_REVIEW_ONLY":
        outcome_outputs = outcome.get("outputs")
        if not isinstance(outcome_outputs, dict):
            raise ValueError("risk_outcome_outputs_invalid")
        outcome_root = latest_run / "run287_risk_outcome_archive"
        for hash_field, (filename, label) in READY_OUTCOME_OUTPUTS.items():
            bind_attested_file(
                latest_run=latest_run,
                file_hashes=file_hashes,
                label=label,
                path=outcome_root / filename,
                expected_sha256=outcome_outputs.get(hash_field),
            )
        bind_attested_file(
            latest_run=latest_run,
            file_hashes=file_hashes,
            label="risk_outcome_price_cache_manifest",
            path=(
                latest_run
                / "run287_risk_outcome_price_cache"
                / "replay_price_cache_manifest.json"
            ),
            expected_sha256=(outcome.get("source_inputs") or {}).get(
                "price_cache_manifest_sha256"
            ),
        )

    scorecard_path = latest_run / REQUIRED_FILES["operating_scorecard"]
    scorecard = read_json(scorecard_path)
    paper_trust = (scorecard.get("runtime_trust_manifest") or {}).get(
        "paper_snapshot"
    ) or {}
    if (
        scorecard.get("schema_version") != "run287-operating-scorecard-v1"
        or scorecard.get("scorecard_trusted") is not True
        or scorecard.get("scorecard_trust_blockers")
        or scorecard.get("integrity_errors")
    ):
        raise ValueError("operating_scorecard_not_trusted")
    if (
        paper_trust.get("status") != "VERIFIED"
        or paper_trust.get("manifest_sha256")
        != file_hashes["paper_snapshot_integrity"]["sha256"]
        or paper_trust.get("snapshot_hash") != paper_manifest.get("snapshot_hash")
    ):
        raise ValueError("operating_scorecard_paper_binding_mismatch")

    gate = read_json(latest_run / REQUIRED_FILES["promotion_gate"])
    if gate.get("schema_version") != "run287-promotion-gate-v1":
        raise ValueError("promotion_gate_schema_invalid")
    for field in (
        "automatic_forward_transition_performed",
        "automatic_production_activation_performed",
        "production_activation_allowed",
        "live_trading_enabled",
        "fullrun_executed",
    ):
        if gate.get(field) is not False:
            raise ValueError(f"promotion_gate_unsafe_flag:{field}")
    if gate.get("canonical_state_unchanged") is not True:
        raise ValueError("promotion_gate_changed_canonical_state")
    source_hashes = gate.get("source_hashes")
    if not isinstance(source_hashes, dict):
        raise ValueError("promotion_gate_source_hashes_invalid")
    for field, relative in PROMOTION_SOURCE_FILES.items():
        expected = source_hashes.get(field)
        if (
            not valid_sha256(expected)
            or expected != sha256_file(ROOT / relative)
        ):
            raise ValueError(f"promotion_gate_source_hash_mismatch:{field}")
    if (
        not valid_sha256(source_hashes.get("evidence_sha256"))
        or source_hashes.get("evidence_sha256")
        == source_hashes.get("base_evidence_sha256")
    ):
        raise ValueError("promotion_gate_runtime_evidence_hash_invalid")
    required_runtime_anchors = {
        "runtime_paper_integrity_sha256": "paper_snapshot_integrity",
        "runtime_risk_outcome_summary_sha256": "risk_outcome_summary",
        "runtime_scorecard_sha256": "operating_scorecard",
    }
    if outcome_status == "READY_RISK_OUTCOME_ARCHIVE_REVIEW_ONLY":
        required_runtime_anchors[
            "runtime_risk_price_cache_manifest_sha256"
        ] = "risk_outcome_price_cache_manifest"
    for field, label in required_runtime_anchors.items():
        if source_hashes.get(field) != file_hashes[label]["sha256"]:
            raise ValueError(
                f"promotion_gate_runtime_anchor_mismatch:{field}"
            )

    runtime_limitations = gate.get("runtime_evidence_limitations")
    if (
        not isinstance(runtime_limitations, list)
        or runtime_limitations
        != sorted(set(str(value) for value in runtime_limitations))
    ):
        raise ValueError("promotion_gate_runtime_limitations_invalid")
    prohibited_prefixes = (
        "paper_snapshot_integrity_failed:",
        "paper_snapshot_integrity_missing_for_challenger",
        "runtime_paper_snapshot_missing",
        "runtime_scorecard_missing",
        "runtime_scorecard_validation_failed:",
    )
    if outcome_status == "READY_RISK_OUTCOME_ARCHIVE_REVIEW_ONLY":
        prohibited_prefixes += (
            "runtime_risk_outcome_summary_missing",
            "runtime_risk_outcome_validation_failed:",
        )
    if any(
        str(value).startswith(prohibited_prefixes)
        for value in runtime_limitations
    ):
        raise ValueError("promotion_gate_runtime_validation_failed")

    observed_hashes = gate.get("runtime_observed_file_hashes")
    if not isinstance(observed_hashes, dict) or not observed_hashes:
        raise ValueError("promotion_gate_observed_file_hashes_invalid")
    gate_observed_files: dict[str, dict[str, str]] = {}
    for raw_path, expected in observed_hashes.items():
        if not isinstance(raw_path, str) or not valid_sha256(expected):
            raise ValueError("promotion_gate_observed_file_record_invalid")
        path = gate_observed_path(latest_run, raw_path)
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(
                f"promotion_gate_observed_file_hash_mismatch:{raw_path}"
            )
        scope = "repo" if raw_path.startswith("repo:") else "latest_run"
        gate_observed_files[raw_path] = {
            "scope": scope,
            "sha256": str(expected),
        }
    for relative, label in REQUIRED_GATE_OBSERVED_FILES.items():
        if (
            observed_hashes.get(relative)
            != file_hashes[label]["sha256"]
        ):
            raise ValueError(
                f"promotion_gate_required_observed_file_mismatch:{relative}"
            )

    # Close the validation/read gap before publishing the manifest.
    rebound_manifest = verify_integrity_manifest(paper_root, require=True)
    rebound_accepted = verify_accepted_publication(paper_root, preview_root)
    if rebound_manifest != paper_manifest or rebound_accepted != accepted:
        raise ValueError("paper_publication_changed_during_validation")
    for label, record in file_hashes.items():
        if sha256_file(latest_run / record["path"]) != record["sha256"]:
            raise ValueError(f"accepted_publication_file_changed:{label}")
    for raw_path, record in gate_observed_files.items():
        if (
            sha256_file(gate_observed_path(latest_run, raw_path))
            != record["sha256"]
        ):
            raise ValueError(
                f"promotion_gate_observed_file_changed:{raw_path}"
            )
    if (
        sha256_file(latest_run / REQUIRED_FILES["promotion_gate"])
        != expected_promotion_gate_sha256
    ):
        raise ValueError("promotion_gate_changed_during_validation")

    return {
        "schema_version": SCHEMA_VERSION,
        "status": READY_STATUS,
        "as_of_date": paper_as_of,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_identity": {
            "commit_sha": source_commit_sha.lower(),
            "workflow": workflow_identity,
            "run_id": run_id,
            "run_attempt": run_attempt,
            "promotion_gate_sha256": expected_promotion_gate_sha256,
        },
        "paper_snapshot": {
            "snapshot_hash": paper_manifest.get("snapshot_hash"),
            "previous_snapshot_hash": paper_manifest.get("previous_snapshot_hash"),
            "file_count": paper_manifest.get("file_count"),
            "transaction_mode": accepted.get("transaction_mode"),
        },
        "outcome_status": outcome_status,
        "promotion_state": gate.get("effective_promotion_state"),
        "promotion_gate_runtime_observed_file_count": len(observed_hashes),
        "files": file_hashes,
        "gate_observed_files": gate_observed_files,
        "review_only": True,
        "automatic_champion_replacement_allowed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "fullrun_executed": False,
    }


def verify_manifest(
    *,
    latest_run: Path,
    manifest_path: Path,
    expected_manifest_sha256: str,
) -> dict[str, Any]:
    latest_run = latest_run.resolve()
    manifest_path = manifest_path.resolve()
    if (
        not valid_sha256(expected_manifest_sha256)
        or require_file(manifest_path, "accepted_manifest")
        != expected_manifest_sha256
    ):
        raise ValueError("accepted_publication_manifest_sha256_mismatch")
    manifest = read_json(manifest_path)
    if (
        manifest.get("schema_version") != SCHEMA_VERSION
        or manifest.get("status") != READY_STATUS
        or manifest.get("review_only") is not True
        or manifest.get("automatic_champion_replacement_allowed") is not False
        or manifest.get("production_activation_allowed") is not False
        or manifest.get("live_trading_enabled") is not False
        or manifest.get("fullrun_executed") is not False
    ):
        raise ValueError("accepted_publication_manifest_contract_invalid")
    source_identity = manifest.get("source_identity")
    if (
        not isinstance(source_identity, dict)
        or not valid_commit_sha(str(source_identity.get("commit_sha") or ""))
        or not str(source_identity.get("workflow") or "").strip()
        or not str(source_identity.get("run_id") or "").strip()
        or not str(source_identity.get("run_attempt") or "").strip()
        or not valid_sha256(source_identity.get("promotion_gate_sha256"))
    ):
        raise ValueError("accepted_publication_source_identity_invalid")

    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("accepted_publication_files_invalid")
    for label, record in files.items():
        if not isinstance(label, str) or not isinstance(record, dict):
            raise ValueError("accepted_publication_file_record_invalid")
        relative = str(record.get("path") or "")
        expected = record.get("sha256")
        candidate = Path(relative)
        if not relative or candidate.is_absolute() or not valid_sha256(expected):
            raise ValueError(f"accepted_publication_file_record_invalid:{label}")
        path = (latest_run / candidate).resolve()
        try:
            path.relative_to(latest_run)
        except ValueError as exc:
            raise ValueError(
                f"accepted_publication_file_path_outside_latest_run:{label}"
            ) from exc
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"accepted_publication_file_reverify_failed:{label}")

    try:
        try:
            from tools.run287_paper_ledger_integrity import (
                verify_integrity_manifest,
            )
        except ModuleNotFoundError:
            from run287_paper_ledger_integrity import verify_integrity_manifest
        paper_manifest = verify_integrity_manifest(
            latest_run / "daily_simulated_fill_ledger",
            require=True,
        )
    except Exception as exc:
        raise ValueError(
            f"accepted_publication_paper_snapshot_reverify_failed:"
            f"{type(exc).__name__}:{exc}"
        ) from exc
    paper_snapshot = manifest.get("paper_snapshot")
    if (
        not isinstance(paper_snapshot, dict)
        or paper_snapshot.get("snapshot_hash")
        != paper_manifest.get("snapshot_hash")
        or paper_snapshot.get("previous_snapshot_hash")
        != paper_manifest.get("previous_snapshot_hash")
        or paper_snapshot.get("file_count") != paper_manifest.get("file_count")
    ):
        raise ValueError("accepted_publication_paper_snapshot_binding_invalid")

    gate_sha256 = str(source_identity["promotion_gate_sha256"])
    promotion_record = files.get("promotion_gate")
    if (
        not isinstance(promotion_record, dict)
        or promotion_record.get("sha256") != gate_sha256
    ):
        raise ValueError("accepted_publication_promotion_gate_binding_invalid")

    observed_files = manifest.get("gate_observed_files")
    if (
        not isinstance(observed_files, dict)
        or not observed_files
        or manifest.get("promotion_gate_runtime_observed_file_count")
        != len(observed_files)
    ):
        raise ValueError("accepted_publication_gate_observed_files_invalid")
    for raw_path, record in observed_files.items():
        if (
            not isinstance(raw_path, str)
            or not isinstance(record, dict)
            or record.get("scope")
            != ("repo" if raw_path.startswith("repo:") else "latest_run")
            or not valid_sha256(record.get("sha256"))
        ):
            raise ValueError(
                f"accepted_publication_gate_observed_record_invalid:{raw_path}"
            )
        path = gate_observed_path(latest_run, raw_path)
        if not path.is_file() or sha256_file(path) != record["sha256"]:
            raise ValueError(
                f"accepted_publication_gate_observed_reverify_failed:{raw_path}"
            )
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument(
        "--output",
        default="outputs/run287_accepted_publication/manifest.json",
    )
    parser.add_argument("--source-commit-sha")
    parser.add_argument("--workflow-identity")
    parser.add_argument("--run-id")
    parser.add_argument("--run-attempt")
    parser.add_argument("--expected-promotion-gate-sha256")
    parser.add_argument("--verify-manifest")
    parser.add_argument("--expected-manifest-sha256")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.verify_manifest:
        if not args.expected_manifest_sha256:
            raise ValueError(
                "accepted_publication_expected_manifest_sha256_missing"
            )
        manifest = verify_manifest(
            latest_run=Path(args.latest_run),
            manifest_path=Path(args.verify_manifest),
            expected_manifest_sha256=args.expected_manifest_sha256,
        )
        print(
            json.dumps(
                {
                    "status": "VERIFIED_ACCEPTED_PUBLICATION_MANIFEST",
                    "as_of_date": manifest.get("as_of_date"),
                    "manifest": str(Path(args.verify_manifest)),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    required = {
        "--source-commit-sha": args.source_commit_sha,
        "--workflow-identity": args.workflow_identity,
        "--run-id": args.run_id,
        "--run-attempt": args.run_attempt,
        "--expected-promotion-gate-sha256":
            args.expected_promotion_gate_sha256,
    }
    missing = [flag for flag, value in required.items() if not value]
    if missing:
        raise ValueError(
            "accepted_publication_build_arguments_missing:" + ",".join(missing)
        )
    manifest = build_manifest(
        latest_run=Path(args.latest_run),
        source_commit_sha=args.source_commit_sha,
        workflow_identity=args.workflow_identity,
        run_id=args.run_id,
        run_attempt=args.run_attempt,
        expected_promotion_gate_sha256=
            args.expected_promotion_gate_sha256,
    )
    output = Path(args.output)
    atomic_write_json(output, manifest)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
