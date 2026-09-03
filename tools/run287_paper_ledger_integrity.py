#!/usr/bin/env python3
"""Checksum and atomically publish the Run287 forward-paper snapshot.

The paper ledger is a directory-level state machine.  A successful session
publishes the complete state (both portfolios and the summary) as one snapshot;
failed validation must leave the prior directory byte-for-byte unchanged.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import stat
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


INTEGRITY_FILE = "snapshot_integrity.json"
LEGACY_INTEGRITY_SCHEMA = "run287-paper-ledger-snapshot-integrity-v1"
INTEGRITY_SCHEMA = "run287-paper-ledger-snapshot-integrity-v2"
SUPPORTED_INTEGRITY_SCHEMAS = frozenset(
    {LEGACY_INTEGRITY_SCHEMA, INTEGRITY_SCHEMA}
)
PORTFOLIOS = ("main", "concentrated")
PAPER_IMMUTABLE_FILES = (
    "genesis_identity.json",
    "bootstrap/main_account.json",
    "bootstrap/concentrated_account.json",
)
PAPER_APPEND_ONLY_FILES = tuple(
    f"{portfolio}/{filename}"
    for portfolio in PORTFOLIOS
    for filename in ("fills.csv", "rejections.csv", "equity_curve.csv")
)
PAPER_IMMUTABLE_HEAD_SELECTION_SCHEMA = (
    "run287-paper-immutable-head-selection-v1"
)
PAPER_IMMUTABLE_HEAD_SELECTION_STATUS = (
    "VERIFIED_LINEAR_IMMUTABLE_PAPER_HEAD_SELECTED"
)
PAPER_INTEGRITY_VERIFIER_RECEIPT_SCHEMA = (
    "run287-paper-ledger-integrity-verifier-receipt-v1"
)
PAPER_INTEGRITY_VERIFIER_RECEIPT_STATUS = "VERIFIED"
PAPER_IMMUTABLE_HEAD_SELECTION_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "heads_root",
        "immutable_head_count",
        "root_snapshot_hash",
        "terminal_snapshot_hash",
        "selected_snapshot_hash",
        "selected_head_dir",
        "selected_as_of_date",
        "chain_snapshot_hashes",
    }
)
REPLAY_PRICE_EVIDENCE_PREFIX = "replay_price_evidence"
REPLAY_TARGET_SOURCE_PREFIX = "replay_target_source"
REPLAY_PRICE_EVIDENCE_SUMMARY_KEYS = frozenset(
    {
        "manifest_sha256",
        "price_cache_tree_sha256",
        "source_generated_at_utc",
        "artifact_captured_at_utc",
        "ingested_at_utc",
        "artifact",
        "ticker_count",
        "durable_snapshot_path",
        "durable_price_cache_tree_sha256",
    }
)
REPLAY_TARGET_SOURCE_SUMMARY_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "selected_session_date",
        "durable_snapshot_path",
        "targets",
    }
)


class PaperLedgerIntegrityError(ValueError):
    """Fail-closed paper-ledger error with a stable machine status."""

    def __init__(self, status: str, reason: str):
        self.status = status
        self.reason = reason
        super().__init__(f"{status}: {reason}")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def canonical_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _absolute_lexical_path(path: Path) -> Path:
    """Return an absolute path without resolving symlink components."""
    return Path(os.path.abspath(os.fspath(path)))


def _require_no_symlink_components(path: Path, *, label: str) -> Path:
    """Reject a path when any existing component is a symlink."""
    absolute = _absolute_lexical_path(Path(path))
    cursor = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        cursor /= part
        if cursor.is_symlink():
            raise PaperLedgerIntegrityError(
                "BLOCKED_INTEGRITY",
                f"{label} contains a symlink component: {cursor}",
            )
    return absolute


def _path_is_within(path: Path, root: Path) -> bool:
    candidate = _absolute_lexical_path(Path(path))
    boundary = _absolute_lexical_path(Path(root))
    return candidate == boundary or boundary in candidate.parents


def _require_output_outside_protected_evidence(
    output: Path,
    *,
    protected_files: Iterable[Path],
    protected_roots: Iterable[Path],
    label: str,
) -> None:
    safe_output = _absolute_lexical_path(Path(output))
    for protected_file in protected_files:
        safe_file = _require_no_symlink_components(
            Path(protected_file),
            label=f"protected {label} evidence file",
        )
        if safe_output == safe_file:
            raise PaperLedgerIntegrityError(
                "BLOCKED_INTEGRITY",
                f"{label} output must not replace a protected evidence file",
            )
    for protected_root in protected_roots:
        safe_root = _require_no_symlink_components(
            Path(protected_root),
            label=f"protected {label} evidence root",
        )
        if _path_is_within(safe_output, safe_root):
            raise PaperLedgerIntegrityError(
                "BLOCKED_INTEGRITY",
                f"{label} output must be outside protected evidence roots",
            )


def _read_regular_file_no_follow(path: Path, *, label: str) -> bytes:
    safe_path = _require_no_symlink_components(Path(path), label=label)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(safe_path, flags)
    except OSError as exc:
        raise PaperLedgerIntegrityError(
            "BLOCKED_INTEGRITY", f"{label} cannot be opened safely: {exc}"
        ) from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise PaperLedgerIntegrityError(
                "BLOCKED_INTEGRITY", f"{label} is not a regular file"
            )
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            return handle.read()
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def valid_sha256(value: Any) -> bool:
    text = str(value or "")
    return (
        len(text) == 64
        and text == text.lower()
        and all(char in "0123456789abcdef" for char in text)
    )


def _strict_iso_date(value: Any, *, field: str) -> date:
    text = str(value or "")
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise PaperLedgerIntegrityError(
            "BLOCKED_INTEGRITY", f"{field} must be an ISO date"
        ) from exc
    if parsed.isoformat() != text:
        raise PaperLedgerIntegrityError(
            "BLOCKED_INTEGRITY", f"{field} must be a canonical ISO date"
        )
    return parsed


def _manifest_hash_payload(payload: dict[str, Any]) -> dict[str, Any]:
    result = {
        "schema_version": payload["schema_version"],
        "as_of_date": payload.get("as_of_date"),
        "files": payload.get("files"),
        "genesis_identity_sha256": payload.get("genesis_identity_sha256", ""),
        "previous_snapshot_hash": payload.get("previous_snapshot_hash", ""),
    }
    if payload["schema_version"] == INTEGRITY_SCHEMA:
        result["ancestor_snapshot_hashes"] = payload.get(
            "ancestor_snapshot_hashes", []
        )
    return result


def _validate_manifest_envelope(payload: Any) -> dict[str, Any]:
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") not in SUPPORTED_INTEGRITY_SCHEMAS
    ):
        raise PaperLedgerIntegrityError(
            "BLOCKED_INTEGRITY", "integrity manifest schema mismatch"
        )
    expected_keys = {
        "schema_version",
        "as_of_date",
        "files",
        "file_count",
        "genesis_identity_sha256",
        "previous_snapshot_hash",
        "generated_at_utc",
        "snapshot_hash",
    }
    if payload["schema_version"] == INTEGRITY_SCHEMA:
        expected_keys.add("ancestor_snapshot_hashes")
    if set(payload) != expected_keys:
        raise PaperLedgerIntegrityError(
            "BLOCKED_INTEGRITY",
            "integrity manifest keys mismatch:"
            f"missing={sorted(expected_keys - set(payload))}:"
            f"extra={sorted(set(payload) - expected_keys)}",
        )
    _strict_iso_date(payload.get("as_of_date"), field="as_of_date")
    expected = payload.get("files")
    if not isinstance(expected, dict) or not expected:
        raise PaperLedgerIntegrityError(
            "BLOCKED_INTEGRITY", "integrity manifest has no file hashes"
        )
    normalized_files = {str(key): str(value) for key, value in expected.items()}
    if (
        any(not key or key == INTEGRITY_FILE for key in normalized_files)
        or any(not valid_sha256(value) for value in normalized_files.values())
    ):
        raise PaperLedgerIntegrityError(
            "BLOCKED_INTEGRITY", "integrity manifest file map is invalid"
        )
    if payload.get("file_count") != len(normalized_files):
        raise PaperLedgerIntegrityError(
            "BLOCKED_INTEGRITY", "integrity manifest file_count mismatch"
        )
    previous = str(payload.get("previous_snapshot_hash") or "")
    if previous and not valid_sha256(previous):
        raise PaperLedgerIntegrityError(
            "BLOCKED_INTEGRITY", "previous snapshot hash is invalid"
        )
    if payload["schema_version"] == INTEGRITY_SCHEMA:
        raw_ancestors = payload.get("ancestor_snapshot_hashes")
        if not isinstance(raw_ancestors, list):
            raise PaperLedgerIntegrityError(
                "BLOCKED_INTEGRITY", "ancestor snapshot hashes are missing"
            )
        ancestors = [str(value) for value in raw_ancestors]
        if (
            any(not valid_sha256(value) for value in ancestors)
            or len(set(ancestors)) != len(ancestors)
            or (previous and (not ancestors or ancestors[0] != previous))
            or (not previous and ancestors)
        ):
            raise PaperLedgerIntegrityError(
                "BLOCKED_INTEGRITY", "ancestor snapshot chain is invalid"
            )
    else:
        ancestors = [previous] if previous else []
    snapshot_hash = str(payload.get("snapshot_hash") or "")
    if (
        not valid_sha256(snapshot_hash)
        or snapshot_hash in ancestors
        or snapshot_hash != canonical_hash(_manifest_hash_payload(payload))
    ):
        raise PaperLedgerIntegrityError(
            "BLOCKED_INTEGRITY", "snapshot hash mismatch"
        )
    return {
        **payload,
        "files": normalized_files,
        "previous_snapshot_hash": previous,
        "ancestor_snapshot_hashes": ancestors,
        "snapshot_hash": snapshot_hash,
    }


def _read_manifest_envelope(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise PaperLedgerIntegrityError(
            "BLOCKED_INTEGRITY", f"unreadable integrity manifest: {exc}"
        ) from exc
    return _validate_manifest_envelope(payload)


def snapshot_files(root: Path) -> dict[str, str]:
    safe_root = _require_no_symlink_components(
        Path(root), label="paper snapshot root"
    )
    if not safe_root.is_dir():
        return {}
    files: dict[str, str] = {}
    for path in sorted(safe_root.rglob("*")):
        if path.is_symlink():
            raise PaperLedgerIntegrityError(
                "BLOCKED_INTEGRITY",
                "paper snapshot contains a symlink: "
                f"{path.relative_to(safe_root).as_posix()}",
            )
        if path.is_file() and path.name != INTEGRITY_FILE:
            files[path.relative_to(safe_root).as_posix()] = file_hash(path)
    return files


def write_integrity_manifest(
    root: Path,
    *,
    as_of_date: str,
    previous_snapshot_hash: str = "",
) -> dict[str, Any]:
    files = snapshot_files(root)
    if not files:
        raise PaperLedgerIntegrityError("BLOCKED_INTEGRITY", "cannot attest an empty paper-ledger snapshot")
    _strict_iso_date(as_of_date, field="as_of_date")
    previous = str(previous_snapshot_hash or "")
    if previous and not valid_sha256(previous):
        raise PaperLedgerIntegrityError(
            "BLOCKED_INTEGRITY", "previous snapshot hash is invalid"
        )
    ancestors: list[str] = []
    prior_path = root / INTEGRITY_FILE
    if previous:
        ancestors.append(previous)
        if prior_path.is_file():
            prior = _read_manifest_envelope(prior_path)
            if prior["snapshot_hash"] != previous:
                raise PaperLedgerIntegrityError(
                    "BLOCKED_INTEGRITY",
                    "previous snapshot hash does not match the staged predecessor",
                )
            ancestors.extend(prior["ancestor_snapshot_hashes"])
        if len(set(ancestors)) != len(ancestors):
            raise PaperLedgerIntegrityError(
                "BLOCKED_INTEGRITY", "snapshot ancestry contains a cycle"
            )
    identity_path = root / "genesis_identity.json"
    payload: dict[str, Any] = {
        "schema_version": INTEGRITY_SCHEMA,
        "as_of_date": str(as_of_date),
        "files": files,
        "file_count": len(files),
        "genesis_identity_sha256": file_hash(identity_path) if identity_path.is_file() else "",
        "previous_snapshot_hash": previous,
        "ancestor_snapshot_hashes": ancestors,
        "generated_at_utc": utc_now(),
    }
    payload["snapshot_hash"] = canonical_hash(_manifest_hash_payload(payload))
    target = root / INTEGRITY_FILE
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def verify_integrity_manifest(root: Path, *, require: bool = True) -> dict[str, Any]:
    safe_root = _require_no_symlink_components(
        Path(root), label="paper snapshot root"
    )
    path = safe_root / INTEGRITY_FILE
    _require_no_symlink_components(path, label="paper integrity manifest")
    if not path.is_file():
        if require:
            raise PaperLedgerIntegrityError("BLOCKED_INTEGRITY", f"missing {INTEGRITY_FILE}")
        return {"status": "LEGACY_UNATTESTED", "snapshot_hash": ""}
    payload = _read_manifest_envelope(path)
    expected = payload["files"]
    actual = snapshot_files(safe_root)
    if actual != expected:
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        changed = sorted(key for key in set(actual) & set(expected) if actual[key] != expected[key])
        raise PaperLedgerIntegrityError(
            "BLOCKED_INTEGRITY",
            f"snapshot checksum mismatch missing={missing} extra={extra} changed={changed}",
        )
    identity_hash = (
        actual.get("genesis_identity.json", "")
        if (safe_root / "genesis_identity.json").is_file()
        else ""
    )
    if payload.get("genesis_identity_sha256", "") != identity_hash:
        raise PaperLedgerIntegrityError(
            "BLOCKED_INTEGRITY", "genesis identity hash mismatch"
        )
    return {**payload, "status": "VERIFIED"}


def _strict_json_object(raw: bytes, *, label: str) -> dict[str, Any]:
    def reject_duplicate_keys(
        pairs: list[tuple[str, Any]],
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise PaperLedgerIntegrityError(
                    "BLOCKED_INTEGRITY",
                    f"{label} has duplicate JSON key: {key}",
                )
            result[key] = value
        return result

    try:
        payload = json.loads(raw, object_pairs_hook=reject_duplicate_keys)
    except PaperLedgerIntegrityError:
        raise
    except Exception as exc:
        raise PaperLedgerIntegrityError(
            "BLOCKED_INTEGRITY", f"{label} is unreadable: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise PaperLedgerIntegrityError(
            "BLOCKED_INTEGRITY", f"{label} is not a JSON object"
        )
    return payload


def _validate_immutable_head_selection_receipt(
    *,
    receipt: dict[str, Any],
    verified_manifest: dict[str, Any],
    canonical_manifest_raw: bytes,
) -> list[str]:
    if set(receipt) != PAPER_IMMUTABLE_HEAD_SELECTION_KEYS:
        raise PaperLedgerIntegrityError(
            "BLOCKED_INTEGRITY",
            "immutable paper head selection receipt keys mismatch",
        )
    ancestors = list(verified_manifest["ancestor_snapshot_hashes"])
    terminal = str(verified_manifest["snapshot_hash"])
    expected_chain = [*reversed(ancestors), terminal]
    expected_root = expected_chain[0]
    heads_root = Path(str(receipt.get("heads_root") or ""))
    selected_head = Path(str(receipt.get("selected_head_dir") or ""))
    if (
        receipt.get("schema_version")
        != PAPER_IMMUTABLE_HEAD_SELECTION_SCHEMA
        or receipt.get("status")
        != PAPER_IMMUTABLE_HEAD_SELECTION_STATUS
        or not heads_root.is_absolute()
        or not selected_head.is_absolute()
        or selected_head != heads_root / terminal
        or receipt.get("immutable_head_count") != len(expected_chain)
        or receipt.get("root_snapshot_hash") != expected_root
        or receipt.get("terminal_snapshot_hash") != terminal
        or receipt.get("selected_snapshot_hash") != terminal
        or receipt.get("selected_as_of_date")
        != verified_manifest["as_of_date"]
        or receipt.get("chain_snapshot_hashes") != expected_chain
    ):
        raise PaperLedgerIntegrityError(
            "BLOCKED_INTEGRITY",
            "immutable paper head selection receipt does not match the "
            "verified canonical manifest lineage",
        )

    _require_no_symlink_components(
        heads_root, label="immutable paper heads root"
    )
    _require_no_symlink_components(
        selected_head, label="selected immutable paper head"
    )
    actual_selection = select_verified_immutable_paper_head(heads_root)
    if receipt != actual_selection:
        raise PaperLedgerIntegrityError(
            "BLOCKED_INTEGRITY",
            "immutable paper head selection receipt does not match "
            "the reverified on-disk immutable head chain",
        )
    selected_manifest_path = selected_head / INTEGRITY_FILE
    selected_verified = verify_integrity_manifest(
        selected_head, require=True
    )
    if selected_verified != verified_manifest:
        raise PaperLedgerIntegrityError(
            "BLOCKED_INTEGRITY",
            "selected immutable paper head does not exactly match the "
            "verified canonical manifest",
        )
    if _read_regular_file_no_follow(
        selected_manifest_path,
        label="selected immutable paper head manifest",
    ) != canonical_manifest_raw:
        raise PaperLedgerIntegrityError(
            "BLOCKED_INTEGRITY",
            "selected immutable paper head manifest bytes do not match "
            "the verified canonical manifest",
        )
    return expected_chain


def build_integrity_verifier_receipt(
    root: Path,
    *,
    immutable_head_selection: Path,
) -> dict[str, Any]:
    """Bind verified raw/file bytes to the immutable-head selection receipt."""
    state_root = _require_no_symlink_components(
        Path(root), label="paper snapshot root"
    )
    manifest_path = state_root / INTEGRITY_FILE
    selection_path = _require_no_symlink_components(
        Path(immutable_head_selection),
        label="immutable paper head selection receipt",
    )
    if _path_is_within(selection_path, state_root):
        raise PaperLedgerIntegrityError(
            "BLOCKED_INTEGRITY",
            "immutable paper head selection receipt must be outside the "
            "accepted paper state",
        )
    if not manifest_path.is_file():
        raise PaperLedgerIntegrityError(
            "BLOCKED_INTEGRITY", f"missing or unsafe {INTEGRITY_FILE}"
        )
    if not selection_path.is_file():
        raise PaperLedgerIntegrityError(
            "BLOCKED_INTEGRITY",
            "immutable paper head selection receipt is missing or unsafe",
        )

    manifest_raw_before = _read_regular_file_no_follow(
        manifest_path, label="paper integrity manifest"
    )
    verified = verify_integrity_manifest(state_root, require=True)
    if (
        verified.get("schema_version") != INTEGRITY_SCHEMA
        or not valid_sha256(verified.get("genesis_identity_sha256"))
    ):
        raise PaperLedgerIntegrityError(
            "BLOCKED_INTEGRITY",
            "paper integrity verifier receipt requires a v2 manifest "
            "with a nonempty genesis identity",
        )
    manifest_raw_after = _read_regular_file_no_follow(
        manifest_path, label="paper integrity manifest"
    )
    if manifest_raw_before != manifest_raw_after:
        raise PaperLedgerIntegrityError(
            "BLOCKED_INTEGRITY",
            "paper integrity manifest changed during verification",
        )
    raw_manifest = _strict_json_object(
        manifest_raw_before, label="raw paper integrity manifest"
    )
    verified_without_status = dict(verified)
    if verified_without_status.pop("status", None) != "VERIFIED" or (
        raw_manifest != verified_without_status
    ):
        raise PaperLedgerIntegrityError(
            "BLOCKED_INTEGRITY",
            "raw paper manifest and canonical verifier result differ",
        )

    selection_raw = _read_regular_file_no_follow(
        selection_path,
        label="immutable paper head selection receipt",
    )
    selection = _strict_json_object(
        selection_raw,
        label="immutable paper head selection receipt",
    )
    chain = _validate_immutable_head_selection_receipt(
        receipt=selection,
        verified_manifest=verified,
        canonical_manifest_raw=manifest_raw_before,
    )
    if _read_regular_file_no_follow(
        selection_path,
        label="immutable paper head selection receipt",
    ) != selection_raw:
        raise PaperLedgerIntegrityError(
            "BLOCKED_INTEGRITY",
            "immutable paper head selection receipt changed during "
            "verification",
        )
    return {
        "schema_version": PAPER_INTEGRITY_VERIFIER_RECEIPT_SCHEMA,
        "status": PAPER_INTEGRITY_VERIFIER_RECEIPT_STATUS,
        "raw_manifest": {
            "schema_version": verified["schema_version"],
            "sha256": hashlib.sha256(manifest_raw_before).hexdigest(),
            "bytes": len(manifest_raw_before),
            "as_of_date": verified["as_of_date"],
            "snapshot_hash": verified["snapshot_hash"],
            "previous_snapshot_hash": verified[
                "previous_snapshot_hash"
            ],
            "ancestor_snapshot_hashes": list(
                verified["ancestor_snapshot_hashes"]
            ),
            "genesis_identity_sha256": verified[
                "genesis_identity_sha256"
            ],
            "file_count": verified["file_count"],
            "files_sha256": canonical_hash(verified["files"]),
        },
        "immutable_head_selection": {
            "schema_version": selection["schema_version"],
            "status": selection["status"],
            "sha256": hashlib.sha256(selection_raw).hexdigest(),
            "bytes": len(selection_raw),
            "immutable_head_count": selection["immutable_head_count"],
            "root_snapshot_hash": selection["root_snapshot_hash"],
            "terminal_snapshot_hash": selection[
                "terminal_snapshot_hash"
            ],
            "chain_snapshot_hashes": chain,
        },
    }


def write_integrity_verifier_receipt(
    path: Path,
    payload: Mapping[str, Any],
    *,
    protected_files: Iterable[Path] = (),
    protected_roots: Iterable[Path] = (),
) -> None:
    output = _absolute_lexical_path(Path(path))
    protected_files = tuple(protected_files)
    protected_roots = tuple(protected_roots)

    def require_outside_protected_evidence() -> None:
        _require_output_outside_protected_evidence(
            output,
            protected_files=protected_files,
            protected_roots=protected_roots,
            label="verifier receipt",
        )

    require_outside_protected_evidence()
    _require_no_symlink_components(
        output.parent, label="verifier receipt output directory"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    _require_no_symlink_components(
        output, label="verifier receipt output"
    )
    raw = integrity_verifier_receipt_bytes(payload)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.",
        suffix=".tmp",
        dir=output.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        _require_no_symlink_components(
            output, label="verifier receipt output"
        )
        require_outside_protected_evidence()
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def integrity_verifier_receipt_bytes(
    payload: Mapping[str, Any],
) -> bytes:
    return (
        json.dumps(
            dict(payload),
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def copy_diagnostic_file_exact(
    source: Path,
    output: Path,
    *,
    protected_files: Iterable[Path] = (),
    protected_roots: Iterable[Path] = (),
) -> dict[str, Any]:
    """Copy one regular file without following links or fixed temp names."""
    safe_source = _require_no_symlink_components(
        Path(source), label="diagnostic source"
    )
    safe_output = _absolute_lexical_path(Path(output))
    protected_files = tuple(protected_files)
    protected_roots = tuple(protected_roots)

    def require_outside_protected_evidence() -> None:
        _require_output_outside_protected_evidence(
            safe_output,
            protected_files=protected_files,
            protected_roots=protected_roots,
            label="diagnostic copy",
        )

    if safe_source == safe_output:
        raise PaperLedgerIntegrityError(
            "BLOCKED_INTEGRITY",
            "diagnostic source and output must be different paths",
        )
    require_outside_protected_evidence()
    _require_no_symlink_components(
        safe_output.parent, label="diagnostic output directory"
    )
    safe_output.parent.mkdir(parents=True, exist_ok=True)
    _require_no_symlink_components(
        safe_output, label="diagnostic output"
    )

    source_raw = _read_regular_file_no_follow(
        safe_source, label="diagnostic source"
    )
    if not source_raw:
        raise PaperLedgerIntegrityError(
            "BLOCKED_INTEGRITY", "diagnostic source is empty"
        )
    if (
        _read_regular_file_no_follow(
            safe_source, label="diagnostic source"
        )
        != source_raw
    ):
        raise PaperLedgerIntegrityError(
            "BLOCKED_INTEGRITY",
            "diagnostic source changed while being read",
        )

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{safe_output.name}.",
        suffix=".tmp",
        dir=safe_output.parent,
    )
    temporary = Path(temporary_name)
    published = False
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(source_raw)
            handle.flush()
            os.fsync(handle.fileno())
        if (
            _read_regular_file_no_follow(
                temporary, label="diagnostic temporary output"
            )
            != source_raw
        ):
            raise PaperLedgerIntegrityError(
                "BLOCKED_INTEGRITY",
                "diagnostic temporary output is not byte-exact",
            )
        if (
            _read_regular_file_no_follow(
                safe_source, label="diagnostic source"
            )
            != source_raw
        ):
            raise PaperLedgerIntegrityError(
                "BLOCKED_INTEGRITY",
                "diagnostic source changed before publication",
            )
        _require_no_symlink_components(
            safe_output, label="diagnostic output"
        )
        require_outside_protected_evidence()
        os.replace(temporary, safe_output)
        published = True
        if (
            _read_regular_file_no_follow(
                safe_output, label="diagnostic output"
            )
            != source_raw
            or _read_regular_file_no_follow(
                safe_source, label="diagnostic source"
            )
            != source_raw
        ):
            safe_output.unlink(missing_ok=True)
            raise PaperLedgerIntegrityError(
                "BLOCKED_INTEGRITY",
                "diagnostic source and output differ after publication",
            )
    finally:
        if not published:
            temporary.unlink(missing_ok=True)

    return {
        "schema_version": "run287-safe-diagnostic-file-copy-v1",
        "status": "COPIED_BYTE_EXACT_NO_SYMLINKS",
        "source": str(safe_source),
        "output": str(safe_output),
        "bytes": len(source_raw),
        "sha256": hashlib.sha256(source_raw).hexdigest(),
    }


def clone_directory(source: Path, parent: Path, prefix: str) -> Path:
    parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=prefix, dir=parent))
    if source.is_dir():
        shutil.copytree(source, staging, dirs_exist_ok=True)
    return staging


def directory_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): file_hash(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    } if root.is_dir() else {}


def _remove_owned_candidate(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def _write_journal(path: Path, payload: dict[str, Any]) -> None:
    staged = path.with_name(path.name + ".tmp")
    staged.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(staged, path)


def recover_interrupted_publish(journal_path: Path) -> bool:
    """Roll back an incomplete directory bundle publish from its recovery copies."""
    if not journal_path.is_file():
        return False
    try:
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        entries = journal.get("entries") if isinstance(journal, dict) else None
        if not isinstance(entries, list):
            raise ValueError("transaction journal entries missing")
        if journal.get("status") == "COMMITTED":
            for entry in entries:
                _remove_owned_candidate(Path(str(entry["backup"])))
            journal_path.unlink()
            return True
        for entry in reversed(entries):
            destination = Path(str(entry["destination"]))
            backup = Path(str(entry["backup"]))
            if backup.exists():
                _remove_owned_candidate(destination)
                os.replace(backup, destination)
            elif not bool(entry.get("destination_existed")):
                _remove_owned_candidate(destination)
        journal_path.unlink()
        return True
    except Exception as exc:
        raise PaperLedgerIntegrityError("BLOCKED_INTEGRITY", f"transaction recovery failed: {exc}") from exc


def atomic_publish_bundle(
    pairs: Iterable[tuple[Path, Path]],
    *,
    journal_path: Path,
    validators: Iterable[Callable[[], Any]] = (),
    failpoint: str = "",
) -> None:
    """Publish directory candidates together, restoring every prior directory on failure."""
    normalized = [(Path(stage), Path(destination)) for stage, destination in pairs]
    if not normalized:
        return
    recover_interrupted_publish(journal_path)
    token = next(tempfile._get_candidate_names())
    entries: list[dict[str, Any]] = []
    for _stage, destination in normalized:
        destination.parent.mkdir(parents=True, exist_ok=True)
        entries.append(
            {
                "destination": str(destination.resolve()),
                "backup": str((destination.parent / f".{destination.name}.recovery-{token}").resolve()),
                "destination_existed": destination.exists(),
            }
        )
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    journal = {
        "schema_version": "run287-paper-directory-transaction-v1",
        "status": "PREPARED",
        "entries": entries,
    }
    _write_journal(journal_path, journal)
    try:
        for index, ((stage, destination), entry) in enumerate(zip(normalized, entries, strict=True)):
            backup = Path(entry["backup"])
            if backup.exists():
                raise PaperLedgerIntegrityError("BLOCKED_INTEGRITY", f"unexpected recovery path exists: {backup}")
            if destination.exists():
                os.replace(destination, backup)
            if failpoint == f"after_backup_{index}":
                raise RuntimeError(f"injected transaction interruption after_backup_{index}")
            os.replace(stage, destination)
            if failpoint == f"after_publish_{index}":
                raise RuntimeError(f"injected transaction interruption after_publish_{index}")
        for validator in validators:
            validator()
        if failpoint == "after_validation":
            raise RuntimeError("injected transaction interruption after_validation")
        journal["status"] = "COMMITTED"
        _write_journal(journal_path, journal)
    except Exception:
        recover_interrupted_publish(journal_path)
        raise
    for entry in entries:
        backup = Path(entry["backup"])
        _remove_owned_candidate(backup)
    journal_path.unlink(missing_ok=True)


def compare_snapshot_continuity(
    candidate: dict[str, Any],
    anchor: dict[str, Any],
) -> str:
    """Return the cryptographically evidenced relationship between snapshots."""
    candidate_hash = str(candidate.get("snapshot_hash") or "")
    anchor_hash = str(anchor.get("snapshot_hash") or "")
    if not valid_sha256(candidate_hash) or not valid_sha256(anchor_hash):
        raise PaperLedgerIntegrityError(
            "BLOCKED_CONTINUITY", "snapshot continuity hash is invalid"
        )
    candidate_date = _strict_iso_date(
        candidate.get("as_of_date"), field="candidate.as_of_date"
    )
    anchor_date = _strict_iso_date(
        anchor.get("as_of_date"), field="anchor.as_of_date"
    )
    if candidate_hash == anchor_hash:
        if candidate_date != anchor_date:
            raise PaperLedgerIntegrityError(
                "BLOCKED_CONTINUITY",
                "equal snapshot hashes have different as-of dates",
            )
        return "SAME_SNAPSHOT"
    candidate_genesis = str(candidate.get("genesis_identity_sha256") or "")
    anchor_genesis = str(anchor.get("genesis_identity_sha256") or "")
    if (
        not valid_sha256(candidate_genesis)
        or not valid_sha256(anchor_genesis)
        or candidate_genesis != anchor_genesis
    ):
        raise PaperLedgerIntegrityError(
            "BLOCKED_CONTINUITY",
            "snapshots do not share one nonempty genesis identity",
        )
    candidate_ancestors = list(candidate.get("ancestor_snapshot_hashes") or [])
    anchor_ancestors = list(anchor.get("ancestor_snapshot_hashes") or [])
    candidate_descends = anchor_hash in candidate_ancestors
    anchor_descends = candidate_hash in anchor_ancestors
    if candidate_descends and anchor_descends:
        raise PaperLedgerIntegrityError(
            "BLOCKED_CONTINUITY", "snapshot ancestry contains a cross-snapshot cycle"
        )
    if candidate_descends:
        anchor_index = candidate_ancestors.index(anchor_hash)
        if candidate_ancestors[anchor_index + 1 :] != anchor_ancestors:
            raise PaperLedgerIntegrityError(
                "BLOCKED_CONTINUITY",
                "candidate ancestry does not preserve the anchor chain",
            )
        if candidate_date < anchor_date:
            raise PaperLedgerIntegrityError(
                "BLOCKED_CONTINUITY",
                "candidate descendant predates its continuity anchor",
            )
        return "CANDIDATE_DESCENDS_FROM_ANCHOR"
    if anchor_descends:
        candidate_index = anchor_ancestors.index(candidate_hash)
        if anchor_ancestors[candidate_index + 1 :] != candidate_ancestors:
            raise PaperLedgerIntegrityError(
                "BLOCKED_CONTINUITY",
                "anchor ancestry does not preserve the candidate chain",
            )
        if anchor_date < candidate_date:
            raise PaperLedgerIntegrityError(
                "BLOCKED_CONTINUITY",
                "continuity anchor descendant predates its candidate",
            )
        return "CANDIDATE_IS_ANCESTOR_OF_ANCHOR"
    raise PaperLedgerIntegrityError(
        "BLOCKED_CONTINUITY",
        "snapshots are on unproven or divergent chains",
    )


def _csv_contract(path: Path) -> tuple[tuple[str, ...], list[dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                if path.read_text(encoding="utf-8").strip():
                    raise ValueError("missing CSV columns")
                return (), []
            if len(reader.fieldnames) != len(set(reader.fieldnames)):
                raise ValueError("missing or duplicate CSV columns")
            raw_rows = list(reader)
            if any(None in row for row in raw_rows):
                raise ValueError("CSV row contains surplus columns")
            rows = [
                {str(key): str(value or "") for key, value in row.items()}
                for row in raw_rows
            ]
            return tuple(reader.fieldnames), rows
    except Exception as exc:
        raise PaperLedgerIntegrityError(
            "BLOCKED_CONTINUITY",
            f"append-only history is unreadable: {path}: {exc}",
        ) from exc


def _validate_paper_semantics(root: Path) -> None:
    account_paths = [
        root / portfolio / "account_state_latest.json"
        for portfolio in PORTFOLIOS
    ]
    if not any(path.is_file() for path in account_paths):
        return
    if not all(path.is_file() for path in account_paths):
        raise PaperLedgerIntegrityError(
            "BLOCKED_CONTINUITY",
            "paper snapshot has only one portfolio account",
        )
    try:
        try:
            from tools.run_daily_simulated_fill_ledger import (
                validate_restored_snapshot,
            )
        except ModuleNotFoundError:
            from run_daily_simulated_fill_ledger import (
                validate_restored_snapshot,
            )
        for portfolio in PORTFOLIOS:
            validate_restored_snapshot(root / portfolio, portfolio)
    except Exception as exc:
        raise PaperLedgerIntegrityError(
            "BLOCKED_CONTINUITY",
            f"paper snapshot semantic replay failed: {type(exc).__name__}:{exc}",
        ) from exc


def verified_replay_price_evidence_sessions(
    root: Path,
) -> dict[str, dict[str, Any]]:
    """Revalidate every immutable replay cache and return it by session."""
    evidence_root = root / REPLAY_PRICE_EVIDENCE_PREFIX
    if not evidence_root.exists():
        return {}
    if evidence_root.is_symlink() or not evidence_root.is_dir():
        raise PaperLedgerIntegrityError(
            "BLOCKED_PRICE_EVIDENCE",
            "durable replay price evidence root is unsafe",
        )
    sessions: dict[str, dict[str, Any]] = {}
    for entry in sorted(evidence_root.iterdir(), key=lambda path: path.name):
        if entry.is_symlink() or not entry.is_dir():
            raise PaperLedgerIntegrityError(
                "BLOCKED_PRICE_EVIDENCE",
                "durable replay price evidence contains a non-directory entry",
            )
        parsed = _strict_iso_date(
            entry.name,
            field="replay_price_evidence.session",
        )
        session = parsed.isoformat()
        if session != entry.name or session in sessions:
            raise PaperLedgerIntegrityError(
                "BLOCKED_PRICE_EVIDENCE",
                "durable replay price evidence session is not canonical",
            )
        if any(path.is_symlink() for path in entry.rglob("*")):
            raise PaperLedgerIntegrityError(
                "BLOCKED_PRICE_EVIDENCE",
                f"durable replay price evidence contains a symlink:{session}",
            )
        try:
            import pandas as pd

            try:
                from tools.run_daily_simulated_fill_ledger import (
                    validate_replay_price_evidence,
                )
            except ModuleNotFoundError:
                from run_daily_simulated_fill_ledger import (
                    validate_replay_price_evidence,
                )
            validated = validate_replay_price_evidence(
                price_cache=entry,
                manifest_path=entry / "manifest.json",
                as_of_date=pd.Timestamp(session),
            )
        except PaperLedgerIntegrityError:
            raise
        except Exception as exc:
            raise PaperLedgerIntegrityError(
                "BLOCKED_PRICE_EVIDENCE",
                "durable replay price evidence semantic validation failed:"
                f"{session}:{exc}",
            ) from exc
        sessions[session] = {
            **validated,
            "durable_snapshot_path": (
                f"{REPLAY_PRICE_EVIDENCE_PREFIX}/{session}"
            ),
            "durable_price_cache_tree_sha256": validated[
                "price_cache_tree_sha256"
            ],
        }
    return sessions


def verified_replay_target_source_sessions(
    root: Path,
) -> dict[str, dict[str, dict[str, Any]]]:
    """Revalidate exact target bytes retained for replay retry provenance."""
    evidence_root = root / REPLAY_TARGET_SOURCE_PREFIX
    if not evidence_root.exists():
        return {}
    if evidence_root.is_symlink() or not evidence_root.is_dir():
        raise PaperLedgerIntegrityError(
            "BLOCKED_TARGET_EVIDENCE",
            "durable replay target source root is unsafe",
        )
    sessions: dict[str, dict[str, dict[str, Any]]] = {}
    expected_names = {f"{portfolio}.csv" for portfolio in PORTFOLIOS}
    for entry in sorted(evidence_root.iterdir(), key=lambda path: path.name):
        if entry.is_symlink() or not entry.is_dir():
            raise PaperLedgerIntegrityError(
                "BLOCKED_TARGET_EVIDENCE",
                "durable replay target source contains a non-directory entry",
            )
        parsed = _strict_iso_date(
            entry.name,
            field="replay_target_source.session",
        )
        session = parsed.isoformat()
        actual_entries = {
            path.name
            for path in entry.iterdir()
        }
        if (
            session != entry.name
            or session in sessions
            or actual_entries != expected_names
        ):
            raise PaperLedgerIntegrityError(
                "BLOCKED_TARGET_EVIDENCE",
                "durable replay target source session contract is invalid",
            )
        targets: dict[str, dict[str, Any]] = {}
        for portfolio in PORTFOLIOS:
            path = entry / f"{portfolio}.csv"
            if (
                path.is_symlink()
                or not path.is_file()
                or path.stat().st_size <= 0
            ):
                raise PaperLedgerIntegrityError(
                    "BLOCKED_TARGET_EVIDENCE",
                    f"durable replay target source is invalid:{session}:{portfolio}",
                )
            targets[portfolio] = {
                "path": (
                    Path(REPLAY_TARGET_SOURCE_PREFIX)
                    / session
                    / f"{portfolio}.csv"
                ).as_posix(),
                "sha256": file_hash(path),
                "bytes": path.stat().st_size,
            }
        sessions[session] = targets
    return sessions


def _validate_complete_paper_snapshot(
    root: Path,
    integrity: dict[str, Any],
) -> None:
    """Require a hash-valid immutable head to be a complete accepted ledger."""
    account_paths = {
        portfolio: root / portfolio / "account_state_latest.json"
        for portfolio in PORTFOLIOS
    }
    if not all(path.is_file() for path in account_paths.values()):
        raise PaperLedgerIntegrityError(
            "BLOCKED_INTEGRITY",
            "immutable paper head is not a complete two-portfolio ledger",
        )
    _validate_paper_semantics(root)
    try:
        summary = _continuity_json(root / "summary.json")
        publication = _continuity_json(root / "accepted_publication.json")
        as_of_date = str(integrity["as_of_date"])
        replay_sessions = verified_replay_price_evidence_sessions(root)
        replay_target_sessions = verified_replay_target_source_sessions(root)
        suppressed = summary.get("new_order_generation_suppressed")
        expected_mode = "MARK_ONLY" if suppressed is True else "SELECTED_TARGET"
        if (
            summary.get("schema_version")
            != "daily-simulated-fill-ledger-summary-v1"
            or summary.get("status") != "completed"
            or summary.get("as_of_date") != as_of_date
            or not isinstance(suppressed, bool)
            or summary.get("review_only") is not True
            or summary.get("simulated") is not True
            or summary.get("live_trading_enabled") is not False
            or summary.get("production_mutation_allowed") is not False
            or summary.get("historical_cagr_mdd_replacement_allowed")
            is not False
            or set((summary.get("portfolios") or {}).keys())
            != set(PORTFOLIOS)
        ):
            raise ValueError("root summary contract")
        if (
            publication.get("schema_version")
            != "run287-paper-accepted-publication-v1"
            or publication.get("status") != "ACCEPTED_ATOMIC_PUBLICATION"
            or publication.get("as_of_date") != as_of_date
            or publication.get("transaction_mode") != expected_mode
            or publication.get("review_only") is not True
            or publication.get("live_trading_enabled") is not False
            or publication.get("production_mutation_allowed") is not False
            or set((publication.get("portfolios") or {}).keys())
            != set(PORTFOLIOS)
        ):
            raise ValueError("accepted publication contract")
        if summary.get("replay_only") is True:
            evidence = summary.get("price_evidence")
            target_evidence = summary.get("target_source_evidence")
            expected_relative = (
                f"{REPLAY_PRICE_EVIDENCE_PREFIX}/{as_of_date}"
            )
            if (
                summary.get("forward_promotion_eligible") is not False
                or not isinstance(evidence, dict)
                or set(evidence) != REPLAY_PRICE_EVIDENCE_SUMMARY_KEYS
                or evidence.get("durable_snapshot_path")
                != expected_relative
                or not valid_sha256(
                    evidence.get("manifest_sha256")
                )
                or not valid_sha256(
                    evidence.get("price_cache_tree_sha256")
                )
                or not valid_sha256(
                    evidence.get("durable_price_cache_tree_sha256")
                )
                or evidence.get("durable_price_cache_tree_sha256")
                != evidence.get("price_cache_tree_sha256")
            ):
                raise ValueError("replay price evidence summary contract")
            expected_target_relative = (
                f"{REPLAY_TARGET_SOURCE_PREFIX}/{as_of_date}"
            )
            if target_evidence is None:
                # Immutable heads accepted before target-source retention was
                # introduced remain readable. They cannot claim the new
                # evidence contract or carry an unbound partial archive.
                if replay_target_sessions:
                    raise ValueError(
                        "pre-field replay head contains unbound target source "
                        "evidence"
                    )
            else:
                revalidated_targets = replay_target_sessions.get(
                    as_of_date
                )
                if (
                    not isinstance(target_evidence, dict)
                    or set(target_evidence)
                    != REPLAY_TARGET_SOURCE_SUMMARY_KEYS
                    or target_evidence.get("schema_version")
                    != "run287-replay-target-source-evidence-v1"
                    or target_evidence.get("status")
                    != "VERIFIED_DURABLE_REPLAY_TARGET_SOURCE"
                    or target_evidence.get("selected_session_date")
                    != as_of_date
                    or target_evidence.get("durable_snapshot_path")
                    != expected_target_relative
                    or not isinstance(revalidated_targets, dict)
                    or set(revalidated_targets) != set(PORTFOLIOS)
                    or target_evidence.get("targets")
                    != revalidated_targets
                    or any(
                        revalidated_targets[portfolio].get("sha256")
                        != (
                            summary.get("portfolios", {})
                            .get(portfolio, {})
                            .get("source_target_sha256")
                        )
                        or revalidated_targets[portfolio].get("sha256")
                        != (
                            publication.get("portfolios", {})
                            .get(portfolio, {})
                            .get("source_target_sha256")
                        )
                        or revalidated_targets[portfolio].get("sha256")
                        != (
                            publication.get("portfolios", {})
                            .get(portfolio, {})
                            .get("published_target_sha256")
                        )
                        for portfolio in PORTFOLIOS
                    )
                ):
                    raise ValueError(
                        "replay target source evidence summary contract"
                    )
            durable_root = root / expected_relative
            if (
                durable_root.is_symlink()
                or not durable_root.is_dir()
                or any(
                    path.is_symlink()
                    for path in durable_root.rglob("*")
                )
            ):
                raise ValueError("durable replay price evidence path")
            revalidated = replay_sessions.get(as_of_date)
            if revalidated is None:
                raise ValueError(
                    "durable replay price evidence session is missing"
                )
            for key, value in revalidated.items():
                if evidence.get(key) != value:
                    raise ValueError(
                        f"durable replay price evidence parity:{key}"
                    )
            durable_hashes = directory_hashes(durable_root)
            durable_tree_sha256 = canonical_hash(durable_hashes)
            if (
                durable_tree_sha256
                != evidence.get("durable_price_cache_tree_sha256")
                or file_hash(durable_root / "manifest.json")
                != evidence.get("manifest_sha256")
                or {
                    key: value
                    for key, value in integrity["files"].items()
                    if key.startswith(expected_relative + "/")
                }
                != {
                    f"{expected_relative}/{key}": value
                    for key, value in durable_hashes.items()
                }
            ):
                raise ValueError("durable replay price evidence hash binding")
        elif "price_evidence" in summary:
            raise ValueError("non-replay summary contains price evidence")
        elif "target_source_evidence" in summary:
            raise ValueError(
                "non-replay summary contains replay target source evidence"
            )
        for portfolio in PORTFOLIOS:
            portfolio_root = root / portfolio
            manifest_path = portfolio_root / "manifest.json"
            target_path = portfolio_root / "effective_target_latest.csv"
            manifest = _continuity_json(manifest_path)
            row = publication["portfolios"][portfolio]
            if not isinstance(row, dict):
                raise ValueError(f"{portfolio} publication row")
            target_sha256 = file_hash(target_path)
            if (
                summary["portfolios"][portfolio] != manifest
                or manifest.get("as_of_date") != as_of_date
                or manifest.get("new_order_generation_suppressed")
                is not suppressed
                or not target_path.is_file()
                or not valid_sha256(target_sha256)
                or manifest.get("target_sha256") != target_sha256
                or not valid_sha256(manifest.get("source_target_sha256"))
                or row.get("source_target_sha256")
                != manifest.get("source_target_sha256")
                or row.get("published_target_sha256")
                != manifest.get("source_target_sha256")
                or row.get("account_state_sha256")
                != file_hash(account_paths[portfolio])
                or row.get("ledger_manifest_sha256")
                != file_hash(manifest_path)
                or not valid_sha256(row.get("preview_identity_at_acceptance"))
                or row.get("preview_mode_at_acceptance")
                != (
                    "NO_NEW_ORDER"
                    if suppressed
                    else "EXECUTABLE_CANDIDATE"
                )
            ):
                raise ValueError(f"{portfolio} root publication parity")
    except PaperLedgerIntegrityError:
        raise
    except Exception as exc:
        raise PaperLedgerIntegrityError(
            "BLOCKED_INTEGRITY",
            f"immutable paper head acceptance contract failed: {exc}",
        ) from exc


def _continuity_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise PaperLedgerIntegrityError(
            "BLOCKED_CONTINUITY",
            f"same-session continuity input is unreadable: {path}: {exc}",
        ) from exc
    if not isinstance(payload, dict):
        raise PaperLedgerIntegrityError(
            "BLOCKED_CONTINUITY",
            f"same-session continuity input is not an object: {path}",
        )
    return payload


def _continuity_nonnegative_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PaperLedgerIntegrityError(
            "BLOCKED_CONTINUITY",
            f"same-session continuity count is invalid: {field}",
        )
    return value


def _verify_same_session_extension(
    candidate_root: Path,
    anchor_root: Path,
    *,
    as_of_date: str,
) -> None:
    """Permit only the explicit MARK_ONLY -> SELECTED_TARGET paper transition."""

    def require(condition: bool, reason: str) -> None:
        if not condition:
            raise PaperLedgerIntegrityError("BLOCKED_CONTINUITY", reason)

    roots = {
        "anchor": (anchor_root, "MARK_ONLY", True, "NO_NEW_ORDER"),
        "candidate": (
            candidate_root,
            "SELECTED_TARGET",
            False,
            "EXECUTABLE_CANDIDATE",
        ),
    }
    publications: dict[str, dict[str, Any]] = {}
    summaries: dict[str, dict[str, Any]] = {}
    for label, (root, mode, suppressed, _preview_mode) in roots.items():
        require(
            all(
                (root / portfolio / "account_state_latest.json").is_file()
                for portfolio in PORTFOLIOS
            ),
            f"same-session {label} is not a complete real paper snapshot",
        )
        publication = _continuity_json(root / "accepted_publication.json")
        summary = _continuity_json(root / "summary.json")
        require(
            publication.get("schema_version")
            == "run287-paper-accepted-publication-v1"
            and publication.get("status") == "ACCEPTED_ATOMIC_PUBLICATION"
            and publication.get("as_of_date") == as_of_date
            and publication.get("transaction_mode") == mode
            and publication.get("review_only") is True
            and publication.get("live_trading_enabled") is False
            and publication.get("production_mutation_allowed") is False
            and isinstance(publication.get("portfolios"), dict),
            f"same-session {label} accepted publication contract is invalid",
        )
        require(
            summary.get("schema_version")
            == "daily-simulated-fill-ledger-summary-v1"
            and summary.get("status") == "completed"
            and summary.get("as_of_date") == as_of_date
            and summary.get("new_order_generation_suppressed") is suppressed
            and summary.get("review_only") is True
            and summary.get("simulated") is True
            and summary.get("live_trading_enabled") is False
            and summary.get("production_mutation_allowed") is False
            and isinstance(summary.get("portfolios"), dict),
            f"same-session {label} summary contract is invalid",
        )
        publications[label] = publication
        summaries[label] = summary

    unchanged_files = (
        "fills.csv",
        "rejections.csv",
        "equity_curve.csv",
        "positions_latest.csv",
    )
    account_transition_fields = {
        "pending_order_count",
        "reserve_reason_reconciliation",
        "reserve_reason_source_hash",
        "target_reserve_reason_reconciliation",
    }
    for portfolio in PORTFOLIOS:
        manifests: dict[str, dict[str, Any]] = {}
        accounts: dict[str, dict[str, Any]] = {}
        for label, (root, _mode, suppressed, preview_mode) in roots.items():
            portfolio_root = root / portfolio
            manifest_path = portfolio_root / "manifest.json"
            account_path = portfolio_root / "account_state_latest.json"
            target_path = portfolio_root / "effective_target_latest.csv"
            manifest = _continuity_json(manifest_path)
            account = _continuity_json(account_path)
            publication_row = (
                publications[label].get("portfolios", {}).get(portfolio)
            )
            require(
                isinstance(publication_row, dict),
                f"same-session {label} publication lacks {portfolio}",
            )
            require(
                manifest.get("schema_version")
                == "daily-simulated-fill-ledger-manifest-v2"
                and manifest.get("portfolio_kind") == portfolio
                and manifest.get("as_of_date") == as_of_date
                and manifest.get("new_order_generation_suppressed")
                is suppressed
                and manifest.get("review_only") is True
                and manifest.get("simulated") is True
                and manifest.get("live_trading_enabled") is False
                and manifest.get("production_mutation_allowed") is False,
                f"same-session {label} {portfolio} manifest contract is invalid",
            )
            require(
                summaries[label].get("portfolios", {}).get(portfolio)
                == manifest,
                f"same-session {label} {portfolio} summary/manifest parity failed",
            )
            target_identity = tuple(
                str(manifest.get(field) or "")
                for field in ("target_hash", "target_sha256", "source_target_sha256")
            )
            require(
                all(valid_sha256(value) for value in target_identity)
                and target_path.is_file()
                and target_identity[1] == file_hash(target_path),
                f"same-session {label} {portfolio} target identity is invalid",
            )
            require(
                publication_row.get("source_target_sha256")
                == target_identity[2]
                and publication_row.get("published_target_sha256")
                == target_identity[2]
                and publication_row.get("account_state_sha256")
                == file_hash(account_path)
                and publication_row.get("ledger_manifest_sha256")
                == file_hash(manifest_path)
                and publication_row.get("preview_mode_at_acceptance")
                == preview_mode
                and valid_sha256(
                    publication_row.get("preview_identity_at_acceptance")
                ),
                f"same-session {label} {portfolio} publication parity failed",
            )
            manifests[label] = manifest
            accounts[label] = account

        require(
            manifests["candidate"].get("seeded_this_run") is False
            and _continuity_nonnegative_int(
                manifests["candidate"].get("resolved_fills_this_run"),
                field=f"{portfolio}.resolved_fills_this_run",
            )
            == 0
            and _continuity_nonnegative_int(
                manifests["candidate"].get("resolved_rejections_this_run"),
                field=f"{portfolio}.resolved_rejections_this_run",
            )
            == 0,
            f"same-session {portfolio} candidate re-executed accepted state",
        )

        for filename in unchanged_files:
            anchor_path = anchor_root / portfolio / filename
            candidate_path = candidate_root / portfolio / filename
            require(
                anchor_path.is_file()
                and candidate_path.is_file()
                and file_hash(anchor_path) == file_hash(candidate_path),
                f"same-session {portfolio} changed accepted {filename}",
            )

        anchor_pending = anchor_root / portfolio / "pending_orders.csv"
        candidate_pending = candidate_root / portfolio / "pending_orders.csv"
        anchor_fields, anchor_rows = _csv_contract(anchor_pending)
        candidate_fields, candidate_rows = _csv_contract(candidate_pending)
        require(
            candidate_fields == anchor_fields
            and len(candidate_rows) >= len(anchor_rows)
            and candidate_rows[: len(anchor_rows)] == anchor_rows,
            f"same-session {portfolio} pending orders are not an exact extension",
        )
        added_orders = len(candidate_rows) - len(anchor_rows)
        enqueued = _continuity_nonnegative_int(
            manifests["candidate"].get("enqueued_this_run"),
            field=f"{portfolio}.enqueued_this_run",
        )
        require(
            added_orders == enqueued,
            f"same-session {portfolio} pending/enqueued count mismatch",
        )

        anchor_economic_account = {
            key: value
            for key, value in accounts["anchor"].items()
            if key not in account_transition_fields
        }
        candidate_economic_account = {
            key: value
            for key, value in accounts["candidate"].items()
            if key not in account_transition_fields
        }
        require(
            candidate_economic_account == anchor_economic_account,
            f"same-session {portfolio} changed accepted economic account state",
        )
        for field in (
            "event_sequence",
            "event_chain_hash",
            "fill_count",
            "rejection_count",
        ):
            require(
                manifests["candidate"].get(field)
                == manifests["anchor"].get(field),
                f"same-session {portfolio} changed accepted {field}",
            )


def _verify_snapshot_extension(candidate_root: Path, anchor_root: Path) -> None:
    """Prove state evolution with content, not self-asserted ancestry metadata."""
    candidate_root = candidate_root.resolve()
    anchor_root = anchor_root.resolve()
    candidate_integrity = _read_manifest_envelope(
        candidate_root / INTEGRITY_FILE
    )
    anchor_integrity = _read_manifest_envelope(anchor_root / INTEGRITY_FILE)
    same_session = (
        candidate_integrity["as_of_date"] == anchor_integrity["as_of_date"]
    )
    if same_session and (
        candidate_integrity["previous_snapshot_hash"]
        != anchor_integrity["snapshot_hash"]
    ):
        raise PaperLedgerIntegrityError(
            "BLOCKED_CONTINUITY",
            "same-session extension is not the anchor's direct descendant",
        )
    real_paper_anchor = any(
        (anchor_root / portfolio / "account_state_latest.json").is_file()
        for portfolio in PORTFOLIOS
    )
    immutable_files = (
        PAPER_IMMUTABLE_FILES
        if real_paper_anchor
        else ("genesis_identity.json",)
    )
    for relative in immutable_files:
        candidate_path = candidate_root / relative
        anchor_path = anchor_root / relative
        if (
            not candidate_path.is_file()
            or not anchor_path.is_file()
            or file_hash(candidate_path) != file_hash(anchor_path)
        ):
            raise PaperLedgerIntegrityError(
                "BLOCKED_CONTINUITY",
                f"immutable continuity input changed or disappeared: {relative}",
            )
    legacy_attestation = "legacy_migration_attestation.json"
    candidate_attestation = candidate_root / legacy_attestation
    anchor_attestation = anchor_root / legacy_attestation
    if candidate_attestation.is_file() or anchor_attestation.is_file():
        if (
            not candidate_attestation.is_file()
            or not anchor_attestation.is_file()
            or file_hash(candidate_attestation) != file_hash(anchor_attestation)
        ):
            raise PaperLedgerIntegrityError(
                "BLOCKED_CONTINUITY",
                "durable legacy migration attestation changed or disappeared",
            )
    evidence_prefix = f"{REPLAY_PRICE_EVIDENCE_PREFIX}/"
    anchor_evidence = {
        relative: digest
        for relative, digest in directory_hashes(anchor_root).items()
        if relative.startswith(evidence_prefix)
    }
    candidate_evidence = {
        relative: digest
        for relative, digest in directory_hashes(candidate_root).items()
        if relative.startswith(evidence_prefix)
    }
    changed_or_missing_evidence = sorted(
        relative
        for relative, digest in anchor_evidence.items()
        if candidate_evidence.get(relative) != digest
    )
    if changed_or_missing_evidence:
        raise PaperLedgerIntegrityError(
            "BLOCKED_CONTINUITY",
            "durable replay price evidence changed or disappeared: "
            + ",".join(changed_or_missing_evidence),
        )
    added_evidence = sorted(set(candidate_evidence) - set(anchor_evidence))
    if added_evidence:
        expected_added_prefix = (
            f"{evidence_prefix}{candidate_integrity['as_of_date']}/"
        )
        candidate_summary = _continuity_json(
            candidate_root / "summary.json"
        )
        if (
            candidate_summary.get("replay_only") is not True
            or any(
                not relative.startswith(expected_added_prefix)
                for relative in added_evidence
            )
        ):
            raise PaperLedgerIntegrityError(
                "BLOCKED_CONTINUITY",
                "new durable replay price evidence is not bound to the "
                "candidate replay session",
            )
    target_evidence_prefix = f"{REPLAY_TARGET_SOURCE_PREFIX}/"
    anchor_target_evidence = {
        relative: digest
        for relative, digest in directory_hashes(anchor_root).items()
        if relative.startswith(target_evidence_prefix)
    }
    candidate_target_evidence = {
        relative: digest
        for relative, digest in directory_hashes(candidate_root).items()
        if relative.startswith(target_evidence_prefix)
    }
    changed_or_missing_target_evidence = sorted(
        relative
        for relative, digest in anchor_target_evidence.items()
        if candidate_target_evidence.get(relative) != digest
    )
    if changed_or_missing_target_evidence:
        raise PaperLedgerIntegrityError(
            "BLOCKED_CONTINUITY",
            "durable replay target source changed or disappeared: "
            + ",".join(changed_or_missing_target_evidence),
        )
    added_target_evidence = sorted(
        set(candidate_target_evidence) - set(anchor_target_evidence)
    )
    if added_target_evidence:
        expected_added_target_prefix = (
            f"{target_evidence_prefix}{candidate_integrity['as_of_date']}/"
        )
        candidate_summary = _continuity_json(
            candidate_root / "summary.json"
        )
        if (
            candidate_summary.get("replay_only") is not True
            or any(
                not relative.startswith(expected_added_target_prefix)
                for relative in added_target_evidence
            )
        ):
            raise PaperLedgerIntegrityError(
                "BLOCKED_CONTINUITY",
                "new durable replay target source is not bound to the "
                "candidate replay session",
            )

    history_files = (
        PAPER_APPEND_ONLY_FILES
        if real_paper_anchor
        else tuple(
            relative
            for relative in PAPER_APPEND_ONLY_FILES
            if (anchor_root / relative).is_file()
        )
    )
    if not history_files:
        raise PaperLedgerIntegrityError(
            "BLOCKED_CONTINUITY",
            "snapshot has no append-only history continuity proof",
        )
    advanced = False
    for relative in history_files:
        candidate_path = candidate_root / relative
        anchor_path = anchor_root / relative
        if not candidate_path.is_file() or not anchor_path.is_file():
            raise PaperLedgerIntegrityError(
                "BLOCKED_CONTINUITY",
                f"append-only history disappeared: {relative}",
            )
        anchor_fields, anchor_rows = _csv_contract(anchor_path)
        candidate_fields, candidate_rows = _csv_contract(candidate_path)
        if (
            (
                candidate_fields != anchor_fields
                and (anchor_fields or anchor_rows)
            )
            or len(candidate_rows) < len(anchor_rows)
            or candidate_rows[: len(anchor_rows)] != anchor_rows
        ):
            raise PaperLedgerIntegrityError(
                "BLOCKED_CONTINUITY",
                f"append-only history is not an exact prefix: {relative}",
            )
        advanced = advanced or len(candidate_rows) > len(anchor_rows)
    if real_paper_anchor:
        _validate_complete_paper_snapshot(
            anchor_root,
            anchor_integrity,
        )
        _validate_complete_paper_snapshot(
            candidate_root,
            candidate_integrity,
        )
    else:
        _validate_paper_semantics(anchor_root)
        _validate_paper_semantics(candidate_root)
    if same_session:
        _verify_same_session_extension(
            candidate_root,
            anchor_root,
            as_of_date=candidate_integrity["as_of_date"],
        )
    elif not advanced:
        raise PaperLedgerIntegrityError(
            "BLOCKED_CONTINUITY",
            "descendant date advanced without an append-only history row",
        )


def require_state_descends_from(
    state: Path,
    anchor: Path,
) -> dict[str, Any]:
    candidate = verify_integrity_manifest(state, require=True)
    verified_anchor = verify_integrity_manifest(anchor, require=True)
    relation = compare_snapshot_continuity(candidate, verified_anchor)
    if relation not in {"SAME_SNAPSHOT", "CANDIDATE_DESCENDS_FROM_ANCHOR"}:
        raise PaperLedgerIntegrityError(
            "BLOCKED_CONTINUITY",
            f"state would roll back accepted anchor: {relation}",
        )
    if relation == "CANDIDATE_DESCENDS_FROM_ANCHOR":
        _verify_snapshot_extension(state, anchor)
    return {
        **candidate,
        "continuity_status": relation,
        "continuity_anchor_snapshot_hash": verified_anchor["snapshot_hash"],
        "continuity_anchor_as_of_date": verified_anchor["as_of_date"],
    }


def install_verified_snapshot(
    source: Path,
    destination: Path,
    *,
    require_continuity: bool = False,
) -> dict[str, Any]:
    verified = verify_integrity_manifest(source, require=True)
    if require_continuity:
        if not (destination / INTEGRITY_FILE).is_file():
            raise PaperLedgerIntegrityError(
                "BLOCKED_CONTINUITY",
                "missing verified local/cache continuity anchor",
            )
        destination_anchor = verify_integrity_manifest(destination, require=True)
        relation = compare_snapshot_continuity(verified, destination_anchor)
        if relation == "SAME_SNAPSHOT":
            return {
                **destination_anchor,
                "continuity_status": relation,
                "install_status": "RETAINED_EQUIVALENT_VERIFIED_DESTINATION",
            }
        if relation == "CANDIDATE_IS_ANCESTOR_OF_ANCHOR":
            _verify_snapshot_extension(destination, source)
            return {
                **destination_anchor,
                "continuity_status": relation,
                "install_status": "RETAINED_NEWER_VERIFIED_DESTINATION",
            }
        if relation != "CANDIDATE_DESCENDS_FROM_ANCHOR":
            raise PaperLedgerIntegrityError(
                "BLOCKED_CONTINUITY", f"unsafe install relation: {relation}"
            )
        _verify_snapshot_extension(source, destination)
    else:
        relation = "CONTINUITY_NOT_REQUIRED"
    stage = clone_directory(source, destination.parent, f".{destination.name}.install-")
    journal = destination.parent / f".{destination.name}.install-transaction.json"
    atomic_publish_bundle(
        [(stage, destination)],
        journal_path=journal,
        validators=[lambda: verify_integrity_manifest(destination, require=True)],
    )
    return {
        **verified,
        "continuity_status": relation,
        "install_status": (
            "INSTALLED_VERIFIED_DESCENDANT"
            if require_continuity
            else "INSTALLED_VERIFIED_SNAPSHOT"
        ),
    }


def _immutable_paper_head_nodes(
    heads_root: Path,
) -> dict[str, dict[str, Any]]:
    """Return verified marker-committed immutable paper heads by snapshot hash.

    An immutable-head directory is committed only once its integrity manifest
    has been written.  This mirrors marker-last publication: directories that
    have not reached that final marker are ignored, while every directory that
    has reached it must verify completely and be named by its snapshot hash.
    """
    heads_root = _require_no_symlink_components(
        Path(heads_root), label="immutable paper heads root"
    )
    if not heads_root.is_dir():
        raise PaperLedgerIntegrityError(
            "BLOCKED_INTEGRITY", "immutable paper heads root is missing or unsafe"
        )
    nodes: dict[str, dict[str, Any]] = {}
    for entry in sorted(heads_root.iterdir(), key=lambda path: path.name):
        if entry.is_symlink():
            raise PaperLedgerIntegrityError(
                "BLOCKED_INTEGRITY", f"immutable paper head symlink is forbidden: {entry.name}"
            )
        if not entry.is_dir():
            continue
        marker = entry / INTEGRITY_FILE
        # A missing marker means a publisher has not committed this directory
        # yet.  Do not let partial uploads affect the accepted chain.
        if not marker.exists() and not marker.is_symlink():
            continue
        if not valid_sha256(entry.name):
            raise PaperLedgerIntegrityError(
                "BLOCKED_INTEGRITY", f"immutable paper head directory name is invalid: {entry.name}"
            )
        if marker.is_symlink() or not marker.is_file():
            raise PaperLedgerIntegrityError(
                "BLOCKED_INTEGRITY", f"immutable paper head marker is unsafe: {entry.name}"
            )
        for descendant in entry.rglob("*"):
            if descendant.is_symlink():
                raise PaperLedgerIntegrityError(
                    "BLOCKED_INTEGRITY",
                    f"immutable paper head bundle symlink is forbidden: {entry.name}",
                )
        verified = verify_integrity_manifest(entry, require=True)
        _validate_complete_paper_snapshot(entry, verified)
        snapshot_hash = str(verified["snapshot_hash"])
        if snapshot_hash != entry.name:
            raise PaperLedgerIntegrityError(
                "BLOCKED_INTEGRITY",
                "immutable paper head directory/hash mismatch: "
                f"directory={entry.name} manifest={snapshot_hash}",
            )
        nodes[snapshot_hash] = {**verified, "_head_dir": entry.resolve()}
    if not nodes:
        raise PaperLedgerIntegrityError(
            "BLOCKED_INTEGRITY", "immutable paper heads contain no committed head"
        )
    return nodes


def _linear_immutable_paper_head_chain(
    nodes: dict[str, dict[str, Any]],
) -> tuple[str, str, list[str]]:
    """Validate one complete immutable-head chain without recursive traversal."""
    parents: dict[str, str] = {}
    children: dict[str, list[str]] = {snapshot_hash: [] for snapshot_hash in nodes}
    roots: list[str] = []
    for snapshot_hash, manifest in nodes.items():
        parent = str(manifest.get("previous_snapshot_hash") or "")
        if not parent:
            roots.append(snapshot_hash)
            parents[snapshot_hash] = ""
            continue
        if parent not in nodes:
            raise PaperLedgerIntegrityError(
                "BLOCKED_INTEGRITY",
                f"immutable paper head parent is missing: child={snapshot_hash} parent={parent}",
            )
        parents[snapshot_hash] = parent
        children[parent].append(snapshot_hash)

    # Keep cycle detection iterative: a durable daily ledger can be much
    # longer than Python's recursion limit.
    colours: dict[str, int] = {snapshot_hash: 0 for snapshot_hash in nodes}
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
            raise PaperLedgerIntegrityError(
                "BLOCKED_INTEGRITY", f"immutable paper head cycle detected: {cursor}"
            )
        for snapshot_hash in reversed(active):
            colours[snapshot_hash] = 2

    for snapshot_hash, parent in parents.items():
        if not parent:
            continue
        manifest = nodes[snapshot_hash]
        parent_manifest = nodes[parent]
        expected_ancestors = [parent, *parent_manifest["ancestor_snapshot_hashes"]]
        if manifest["ancestor_snapshot_hashes"] != expected_ancestors:
            raise PaperLedgerIntegrityError(
                "BLOCKED_INTEGRITY",
                f"immutable paper head parent lineage mismatch: child={snapshot_hash} parent={parent}",
            )
        if (
            manifest.get("genesis_identity_sha256", "")
            != parent_manifest.get("genesis_identity_sha256", "")
        ):
            raise PaperLedgerIntegrityError(
                "BLOCKED_INTEGRITY",
                f"immutable paper head parent genesis mismatch: child={snapshot_hash} parent={parent}",
            )
        if _strict_iso_date(manifest["as_of_date"], field="as_of_date") < _strict_iso_date(
            parent_manifest["as_of_date"], field="parent.as_of_date"
        ):
            raise PaperLedgerIntegrityError(
                "BLOCKED_INTEGRITY",
                f"immutable paper head predates parent: child={snapshot_hash} parent={parent}",
            )

    if len(roots) != 1:
        raise PaperLedgerIntegrityError(
            "BLOCKED_INTEGRITY", f"immutable paper head root count is invalid: {len(roots)}"
        )
    for parent, child_hashes in children.items():
        if len(child_hashes) > 1:
            raise PaperLedgerIntegrityError(
                "BLOCKED_INTEGRITY",
                "immutable paper head fork detected: "
                f"parent={parent} children={','.join(sorted(child_hashes))}",
            )
    terminals = sorted(
        snapshot_hash
        for snapshot_hash, child_hashes in children.items()
        if not child_hashes
    )
    if len(terminals) != 1:
        raise PaperLedgerIntegrityError(
            "BLOCKED_INTEGRITY",
            f"immutable paper head terminal count is invalid: {len(terminals)}",
        )

    chain = [roots[0]]
    while children[chain[-1]]:
        chain.append(children[chain[-1]][0])
    if len(chain) != len(nodes):
        raise PaperLedgerIntegrityError(
            "BLOCKED_INTEGRITY", "immutable paper head chain is disconnected"
        )
    return roots[0], terminals[0], chain


def select_verified_immutable_paper_head(heads_root: Path) -> dict[str, Any]:
    """Select the unique terminal complete accepted paper head."""
    root = _require_no_symlink_components(
        Path(heads_root), label="immutable paper heads root"
    )
    nodes = _immutable_paper_head_nodes(root)
    root_hash, terminal_hash, chain = _linear_immutable_paper_head_chain(nodes)
    for parent_hash, child_hash in zip(chain, chain[1:], strict=False):
        _verify_snapshot_extension(
            Path(nodes[child_hash]["_head_dir"]),
            Path(nodes[parent_hash]["_head_dir"]),
        )
    terminal = nodes[terminal_hash]
    return {
        "schema_version": PAPER_IMMUTABLE_HEAD_SELECTION_SCHEMA,
        "status": PAPER_IMMUTABLE_HEAD_SELECTION_STATUS,
        "heads_root": str(root.resolve()),
        "immutable_head_count": len(chain),
        "root_snapshot_hash": root_hash,
        "terminal_snapshot_hash": terminal_hash,
        "selected_snapshot_hash": terminal_hash,
        "selected_head_dir": str(terminal["_head_dir"]),
        "selected_as_of_date": terminal["as_of_date"],
        "chain_snapshot_hashes": chain,
    }


def install_unique_verified_immutable_paper_head(
    heads_root: Path,
    destination: Path,
    *,
    require_continuity: bool = False,
) -> dict[str, Any]:
    """Select and install the only terminal committed immutable paper head."""
    selection = select_verified_immutable_paper_head(heads_root)
    installed = install_verified_snapshot(
        Path(selection["selected_head_dir"]),
        Path(destination),
        require_continuity=require_continuity,
    )
    return {**selection, **installed}


def reconcile_immutable_paper_head_cache(
    cache_root: Path,
    *,
    merge_heads_roots: Iterable[Path] = (),
    add_head_sources: Iterable[Path] = (),
    expected_terminal_hash: str = "",
) -> dict[str, Any]:
    """Atomically merge complete immutable chains and accepted snapshots."""
    destination = Path(cache_root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}.reconcile-",
            dir=destination.parent,
        )
    )
    try:
        if destination.exists():
            if destination.is_symlink() or not destination.is_dir():
                raise PaperLedgerIntegrityError(
                    "BLOCKED_INTEGRITY",
                    "immutable paper head cache destination is unsafe",
                )
            select_verified_immutable_paper_head(destination)
            shutil.copytree(destination, stage, dirs_exist_ok=True)

        def install_head(source: Path) -> None:
            verified = verify_integrity_manifest(source, require=True)
            _validate_complete_paper_snapshot(source, verified)
            snapshot_hash = str(verified["snapshot_hash"])
            target = stage / snapshot_hash
            if target.exists():
                if directory_hashes(target) != directory_hashes(source):
                    raise PaperLedgerIntegrityError(
                        "BLOCKED_INTEGRITY",
                        "one immutable paper hash has divergent bundles:"
                        f"{snapshot_hash}",
                    )
                return
            shutil.copytree(source, target)

        for source_root in merge_heads_roots:
            source_root = Path(source_root)
            nodes = _immutable_paper_head_nodes(source_root)
            _linear_immutable_paper_head_chain(nodes)
            for snapshot_hash in sorted(nodes):
                install_head(Path(nodes[snapshot_hash]["_head_dir"]))
        for source in add_head_sources:
            install_head(Path(source))

        selection = select_verified_immutable_paper_head(stage)
        expected = str(expected_terminal_hash or "")
        if expected and (
            not valid_sha256(expected)
            or selection["selected_snapshot_hash"] != expected
        ):
            raise PaperLedgerIntegrityError(
                "BLOCKED_CONTINUITY",
                "reconciled immutable paper terminal differs from the "
                "expected accepted state",
            )
        journal = destination.parent / (
            f".{destination.name}.reconcile-transaction.json"
        )
        atomic_publish_bundle(
            [(stage, destination)],
            journal_path=journal,
            validators=[
                lambda: select_verified_immutable_paper_head(
                    destination
                )
            ],
        )
        published_selection = select_verified_immutable_paper_head(destination)
        return {
            **published_selection,
            "cache_status": "RECONCILED_IMMUTABLE_PAPER_HEAD_CACHE",
        }
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", default="")
    parser.add_argument("--require-integrity", action="store_true")
    parser.add_argument("--install-source", default="")
    parser.add_argument("--install-immutable-heads-root", default="")
    parser.add_argument("--select-immutable-heads-root", default="")
    parser.add_argument("--reconcile-immutable-head-cache", default="")
    parser.add_argument(
        "--merge-immutable-heads-root",
        action="append",
        default=[],
    )
    parser.add_argument(
        "--add-head-source",
        action="append",
        default=[],
    )
    parser.add_argument("--expected-terminal-hash", default="")
    parser.add_argument("--require-install-continuity", action="store_true")
    parser.add_argument("--require-state-descends-from", default="")
    parser.add_argument("--immutable-head-selection", default="")
    parser.add_argument("--verifier-receipt-output", default="")
    parser.add_argument("--safe-diagnostic-copy-source", default="")
    parser.add_argument("--safe-diagnostic-copy-output", default="")
    parser.add_argument("--output", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.verifier_receipt_output and not args.immutable_head_selection:
            raise PaperLedgerIntegrityError(
                "BLOCKED_INTEGRITY",
                "verifier receipt mode requires immutable-head selection "
                "and output",
            )
        if args.immutable_head_selection and not (
            args.verifier_receipt_output
            or args.safe_diagnostic_copy_source
        ):
            raise PaperLedgerIntegrityError(
                "BLOCKED_INTEGRITY",
                "immutable-head selection requires verifier receipt or "
                "safe diagnostic copy mode",
            )
        diagnostic_copy_request_values = (
            args.safe_diagnostic_copy_source,
            args.safe_diagnostic_copy_output,
        )
        if any(diagnostic_copy_request_values) and not all(
            (*diagnostic_copy_request_values, args.immutable_head_selection)
        ):
            raise PaperLedgerIntegrityError(
                "BLOCKED_INTEGRITY",
                "safe diagnostic copy mode requires source, output, and "
                "immutable-head selection",
            )
        modes = [
            bool(args.install_source),
            bool(args.install_immutable_heads_root),
            bool(args.select_immutable_heads_root),
            bool(args.reconcile_immutable_head_cache),
            bool(args.require_state_descends_from),
        ]
        if args.safe_diagnostic_copy_source:
            if (
                any(modes)
                or bool(args.verifier_receipt_output)
                or not args.state_dir
                or args.require_integrity
                or args.require_install_continuity
                or args.merge_immutable_heads_root
                or args.add_head_source
                or args.expected_terminal_hash
                or args.output
            ):
                raise PaperLedgerIntegrityError(
                    "BLOCKED_INTEGRITY",
                    "safe diagnostic copy mode requires only --state-dir "
                    "and its source/output/immutable-head-selection "
                    "arguments",
                )
            state_root = _require_no_symlink_components(
                Path(args.state_dir), label="paper snapshot root"
            )
            source = _require_no_symlink_components(
                Path(args.safe_diagnostic_copy_source),
                label="diagnostic source",
            )
            output = _require_no_symlink_components(
                Path(args.safe_diagnostic_copy_output),
                label="diagnostic output",
            )
            selection_path = _require_no_symlink_components(
                Path(args.immutable_head_selection),
                label="immutable paper head selection receipt",
            )
            if source != state_root / INTEGRITY_FILE:
                raise PaperLedgerIntegrityError(
                    "BLOCKED_INTEGRITY",
                    "diagnostic source must be the canonical paper "
                    "integrity manifest",
                )
            if _path_is_within(output, state_root):
                raise PaperLedgerIntegrityError(
                    "BLOCKED_INTEGRITY",
                    "diagnostic output must be outside the accepted "
                    "paper state",
                )
            if _path_is_within(selection_path, state_root):
                raise PaperLedgerIntegrityError(
                    "BLOCKED_INTEGRITY",
                    "immutable paper head selection receipt must be "
                    "outside the accepted paper state",
                )
            selection_raw = _read_regular_file_no_follow(
                selection_path,
                label="immutable paper head selection receipt",
            )
            selection = _strict_json_object(
                selection_raw,
                label="immutable paper head selection receipt",
            )
            if set(selection) != PAPER_IMMUTABLE_HEAD_SELECTION_KEYS:
                raise PaperLedgerIntegrityError(
                    "BLOCKED_INTEGRITY",
                    "immutable paper head selection receipt keys mismatch",
                )
            heads_root = Path(str(selection.get("heads_root") or ""))
            if not heads_root.is_absolute():
                raise PaperLedgerIntegrityError(
                    "BLOCKED_INTEGRITY",
                    "immutable paper heads root must be absolute",
                )
            heads_root = _require_no_symlink_components(
                heads_root, label="immutable paper heads root"
            )
            if selection != select_verified_immutable_paper_head(heads_root):
                raise PaperLedgerIntegrityError(
                    "BLOCKED_INTEGRITY",
                    "immutable paper head selection receipt does not match "
                    "the reverified on-disk immutable head chain",
                )
            if _read_regular_file_no_follow(
                selection_path,
                label="immutable paper head selection receipt",
            ) != selection_raw:
                raise PaperLedgerIntegrityError(
                    "BLOCKED_INTEGRITY",
                    "immutable paper head selection receipt changed before "
                    "diagnostic copy publication",
                )
            if output == selection_path:
                raise PaperLedgerIntegrityError(
                    "BLOCKED_INTEGRITY",
                    "diagnostic copy output must not replace the immutable "
                    "paper head selection receipt",
                )
            if _path_is_within(output, heads_root):
                raise PaperLedgerIntegrityError(
                    "BLOCKED_INTEGRITY",
                    "diagnostic copy output must be outside the immutable "
                    "paper head evidence root",
                )
            result = copy_diagnostic_file_exact(
                source,
                output,
                protected_files=(selection_path,),
                protected_roots=(state_root, heads_root),
            )
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        if args.verifier_receipt_output:
            if (
                any(modes)
                or not args.state_dir
                or not args.require_integrity
                or args.output
            ):
                raise PaperLedgerIntegrityError(
                    "BLOCKED_INTEGRITY",
                    "verifier receipt mode requires only --state-dir, "
                    "--require-integrity, and verifier receipt arguments",
                )
            state_root = _require_no_symlink_components(
                Path(args.state_dir), label="paper snapshot root"
            )
            receipt_output = _require_no_symlink_components(
                Path(args.verifier_receipt_output),
                label="verifier receipt output",
            )
            selection_path = _require_no_symlink_components(
                Path(args.immutable_head_selection),
                label="immutable paper head selection receipt",
            )
            if _path_is_within(receipt_output, state_root):
                raise PaperLedgerIntegrityError(
                    "BLOCKED_INTEGRITY",
                    "verifier receipt output must be outside the accepted "
                    "paper state",
                )
            selection_raw = _read_regular_file_no_follow(
                selection_path,
                label="immutable paper head selection receipt",
            )
            selection = _strict_json_object(
                selection_raw,
                label="immutable paper head selection receipt",
            )
            heads_root = Path(str(selection.get("heads_root") or ""))
            if not heads_root.is_absolute():
                raise PaperLedgerIntegrityError(
                    "BLOCKED_INTEGRITY",
                    "immutable paper heads root must be absolute",
                )
            heads_root = _require_no_symlink_components(
                heads_root, label="immutable paper heads root"
            )
            if receipt_output == selection_path:
                raise PaperLedgerIntegrityError(
                    "BLOCKED_INTEGRITY",
                    "verifier receipt output must not replace the immutable "
                    "paper head selection receipt",
                )
            if _path_is_within(receipt_output, heads_root):
                raise PaperLedgerIntegrityError(
                    "BLOCKED_INTEGRITY",
                    "verifier receipt output must be outside the immutable "
                    "paper head evidence root",
                )
            result = build_integrity_verifier_receipt(
                state_root,
                immutable_head_selection=selection_path,
            )
            if _read_regular_file_no_follow(
                selection_path,
                label="immutable paper head selection receipt",
            ) != selection_raw:
                raise PaperLedgerIntegrityError(
                    "BLOCKED_INTEGRITY",
                    "immutable paper head selection receipt changed before "
                    "verifier receipt publication",
                )
            write_integrity_verifier_receipt(
                receipt_output,
                result,
                protected_files=(selection_path,),
                protected_roots=(state_root, heads_root),
            )
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        if sum(modes) > 1:
            raise PaperLedgerIntegrityError(
                "BLOCKED_CONTINUITY",
                "install, immutable-head selection, and descendant assertion modes "
                "are mutually exclusive",
            )
        if args.require_install_continuity and not (
            args.install_source or args.install_immutable_heads_root
        ):
            raise PaperLedgerIntegrityError(
                "BLOCKED_CONTINUITY",
                "--require-install-continuity requires an install mode",
            )
        if (
            args.merge_immutable_heads_root
            or args.add_head_source
            or args.expected_terminal_hash
        ) and not args.reconcile_immutable_head_cache:
            raise PaperLedgerIntegrityError(
                "BLOCKED_INTEGRITY",
                "immutable head merge arguments require reconciliation mode",
            )
        if not args.select_immutable_heads_root and not args.state_dir:
            if args.reconcile_immutable_head_cache:
                pass
            else:
                raise PaperLedgerIntegrityError(
                    "BLOCKED_INTEGRITY",
                    "--state-dir is required for this mode",
                )
        destination = Path(args.state_dir) if args.state_dir else Path()
        if args.select_immutable_heads_root:
            result = select_verified_immutable_paper_head(
                Path(args.select_immutable_heads_root)
            )
        elif args.reconcile_immutable_head_cache:
            if not (
                args.merge_immutable_heads_root
                or args.add_head_source
                or Path(args.reconcile_immutable_head_cache).is_dir()
            ):
                raise PaperLedgerIntegrityError(
                    "BLOCKED_INTEGRITY",
                    "immutable head cache reconciliation has no source",
                )
            result = reconcile_immutable_paper_head_cache(
                Path(args.reconcile_immutable_head_cache),
                merge_heads_roots=[
                    Path(value)
                    for value in args.merge_immutable_heads_root
                ],
                add_head_sources=[
                    Path(value) for value in args.add_head_source
                ],
                expected_terminal_hash=args.expected_terminal_hash,
            )
        elif args.install_immutable_heads_root:
            result = install_unique_verified_immutable_paper_head(
                Path(args.install_immutable_heads_root),
                destination,
                require_continuity=bool(args.require_install_continuity),
            )
        elif args.install_source:
            result = install_verified_snapshot(
                Path(args.install_source),
                destination,
                require_continuity=bool(args.require_install_continuity),
            )
        elif args.require_state_descends_from:
            result = require_state_descends_from(
                destination, Path(args.require_state_descends_from)
            )
        else:
            result = verify_integrity_manifest(destination, require=bool(args.require_integrity))
        payload = {"status": "PASS", **result}
        if args.output:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        status = exc.status if isinstance(exc, PaperLedgerIntegrityError) else "BLOCKED_INTEGRITY"
        print(json.dumps({"status": status, "reason": str(exc)}, indent=2, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
