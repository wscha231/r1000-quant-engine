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
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable


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
    path = root / INTEGRITY_FILE
    if not path.is_file():
        if require:
            raise PaperLedgerIntegrityError("BLOCKED_INTEGRITY", f"missing {INTEGRITY_FILE}")
        return {"status": "LEGACY_UNATTESTED", "snapshot_hash": ""}
    payload = _read_manifest_envelope(path)
    expected = payload["files"]
    actual = snapshot_files(root)
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
        if (root / "genesis_identity.json").is_file()
        else ""
    )
    if payload.get("genesis_identity_sha256", "") != identity_hash:
        raise PaperLedgerIntegrityError(
            "BLOCKED_INTEGRITY", "genesis identity hash mismatch"
        )
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
        if candidate_date <= anchor_date:
            raise PaperLedgerIntegrityError(
                "BLOCKED_CONTINUITY",
                "candidate descendant does not advance its continuity anchor date",
            )
        return "CANDIDATE_DESCENDS_FROM_ANCHOR"
    if anchor_descends:
        candidate_index = anchor_ancestors.index(candidate_hash)
        if anchor_ancestors[candidate_index + 1 :] != candidate_ancestors:
            raise PaperLedgerIntegrityError(
                "BLOCKED_CONTINUITY",
                "anchor ancestry does not preserve the candidate chain",
            )
        if anchor_date <= candidate_date:
            raise PaperLedgerIntegrityError(
                "BLOCKED_CONTINUITY",
                "continuity anchor descendant does not advance its candidate date",
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


def _verify_snapshot_extension(candidate_root: Path, anchor_root: Path) -> None:
    """Prove state evolution with content, not self-asserted ancestry metadata."""
    candidate_root = candidate_root.resolve()
    anchor_root = anchor_root.resolve()
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
    if not advanced:
        raise PaperLedgerIntegrityError(
            "BLOCKED_CONTINUITY",
            "descendant date advanced without an append-only history row",
        )
    _validate_paper_semantics(anchor_root)
    _validate_paper_semantics(candidate_root)


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--require-integrity", action="store_true")
    parser.add_argument("--install-source", default="")
    parser.add_argument("--require-install-continuity", action="store_true")
    parser.add_argument("--require-state-descends-from", default="")
    parser.add_argument("--output", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    destination = Path(args.state_dir)
    try:
        if args.require_install_continuity and not args.install_source:
            raise PaperLedgerIntegrityError(
                "BLOCKED_CONTINUITY",
                "--require-install-continuity requires --install-source",
            )
        if args.install_source and args.require_state_descends_from:
            raise PaperLedgerIntegrityError(
                "BLOCKED_CONTINUITY",
                "install and descendant assertion modes are mutually exclusive",
            )
        if args.install_source:
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
