#!/usr/bin/env python3
"""Checksum and atomically publish the Run287 forward-paper snapshot.

The paper ledger is a directory-level state machine.  A successful session
publishes the complete state (both portfolios and the summary) as one snapshot;
failed validation must leave the prior directory byte-for-byte unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable


INTEGRITY_FILE = "snapshot_integrity.json"
INTEGRITY_SCHEMA = "run287-paper-ledger-snapshot-integrity-v1"


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


def snapshot_files(root: Path) -> dict[str, str]:
    if not root.is_dir():
        return {}
    return {
        path.relative_to(root).as_posix(): file_hash(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != INTEGRITY_FILE
    }


def write_integrity_manifest(
    root: Path,
    *,
    as_of_date: str,
    previous_snapshot_hash: str = "",
) -> dict[str, Any]:
    files = snapshot_files(root)
    if not files:
        raise PaperLedgerIntegrityError("BLOCKED_INTEGRITY", "cannot attest an empty paper-ledger snapshot")
    identity_path = root / "genesis_identity.json"
    payload: dict[str, Any] = {
        "schema_version": INTEGRITY_SCHEMA,
        "as_of_date": str(as_of_date),
        "files": files,
        "file_count": len(files),
        "genesis_identity_sha256": file_hash(identity_path) if identity_path.is_file() else "",
        "previous_snapshot_hash": str(previous_snapshot_hash or ""),
        "generated_at_utc": utc_now(),
    }
    payload["snapshot_hash"] = canonical_hash(
        {
            "schema_version": payload["schema_version"],
            "as_of_date": payload["as_of_date"],
            "files": files,
            "genesis_identity_sha256": payload["genesis_identity_sha256"],
            "previous_snapshot_hash": payload["previous_snapshot_hash"],
        }
    )
    target = root / INTEGRITY_FILE
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def verify_integrity_manifest(root: Path, *, require: bool = True) -> dict[str, Any]:
    path = root / INTEGRITY_FILE
    if not path.is_file():
        if require:
            raise PaperLedgerIntegrityError("BLOCKED_INTEGRITY", f"missing {INTEGRITY_FILE}")
        return {"status": "LEGACY_UNATTESTED", "snapshot_hash": ""}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise PaperLedgerIntegrityError("BLOCKED_INTEGRITY", f"unreadable integrity manifest: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != INTEGRITY_SCHEMA:
        raise PaperLedgerIntegrityError("BLOCKED_INTEGRITY", "integrity manifest schema mismatch")
    expected = payload.get("files")
    if not isinstance(expected, dict) or not expected:
        raise PaperLedgerIntegrityError("BLOCKED_INTEGRITY", "integrity manifest has no file hashes")
    actual = snapshot_files(root)
    if actual != {str(key): str(value) for key, value in expected.items()}:
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        changed = sorted(key for key in set(actual) & set(expected) if actual[key] != expected[key])
        raise PaperLedgerIntegrityError(
            "BLOCKED_INTEGRITY",
            f"snapshot checksum mismatch missing={missing} extra={extra} changed={changed}",
        )
    expected_snapshot_hash = canonical_hash(
        {
            "schema_version": payload["schema_version"],
            "as_of_date": payload.get("as_of_date"),
            "files": actual,
            "genesis_identity_sha256": payload.get("genesis_identity_sha256", ""),
            "previous_snapshot_hash": payload.get("previous_snapshot_hash", ""),
        }
    )
    if payload.get("snapshot_hash") != expected_snapshot_hash:
        raise PaperLedgerIntegrityError("BLOCKED_INTEGRITY", "snapshot hash mismatch")
    return {**payload, "status": "VERIFIED"}


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


def install_verified_snapshot(source: Path, destination: Path) -> dict[str, Any]:
    verified = verify_integrity_manifest(source, require=True)
    stage = clone_directory(source, destination.parent, f".{destination.name}.install-")
    journal = destination.parent / f".{destination.name}.install-transaction.json"
    atomic_publish_bundle(
        [(stage, destination)],
        journal_path=journal,
        validators=[lambda: verify_integrity_manifest(destination, require=True)],
    )
    return verified


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--require-integrity", action="store_true")
    parser.add_argument("--install-source", default="")
    parser.add_argument("--output", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    destination = Path(args.state_dir)
    try:
        if args.install_source:
            result = install_verified_snapshot(Path(args.install_source), destination)
            result = {**result, "install_status": "INSTALLED_VERIFIED_SNAPSHOT"}
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
