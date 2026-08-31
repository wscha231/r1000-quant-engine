#!/usr/bin/env python3
"""Collect immutable Chameleon macro/options observations for future decisions.

Official network responses are usable only from their exact capture time and
are labelled FORWARD_PIT. Fixture and supplied-file captures remain
FREE_PROXY. This collector does not materialize historical backtests, route a
portfolio, write targets or TradeIntent, create orders, mutate portfolio
ledgers or accepted heads, dispatch workflows, or promote a policy.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import quote, urlsplit, urlunsplit

import requests


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = ROOT / "docs" / "run287_chameleon_forward_archive_contract.json"
CANONICAL_CONTRACT_SEMANTIC_SHA256 = (
    "20702cef268459b596684f838e533c6586ad109eeaced1c47baccce488966371"
)
SCHEMA_VERSION = "run287-chameleon-forward-archive-v1"
READY_STATUS = "READY_CHAMELEON_FORWARD_ARCHIVE_REPORT_ONLY"
READY_PARTIAL_STATUS = (
    "READY_CHAMELEON_FORWARD_ARCHIVE_REPORT_ONLY_WITH_MISSING_SOURCES"
)
BLOCKED_STATUS = "BLOCKED_CHAMELEON_FORWARD_ARCHIVE"
USER_AGENT = "run287-chameleon-forward-archive/1.0 research-only"
UTC_EXACT = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$"
)
HEX64 = re.compile(r"^[0-9a-f]{64}$")

SAFETY = {
    "report_only": True,
    "selector_executed": False,
    "target_books_mutated": False,
    "trade_intents_written": False,
    "orders_generated": False,
    "portfolio_ledger_mutated": False,
    "accepted_head_mutated": False,
    "historical_backtest_executed": False,
    "fullrun_executed": False,
    "workflow_dispatched": False,
    "production_activation_allowed": False,
    "live_trading_enabled": False,
    "automatic_promotion_allowed": False,
}


class ArchiveContractError(ValueError):
    """Raised when an archive attempt could misstate provenance or chronology."""


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def pretty_json_bytes(payload: Any) -> bytes:
    return (
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")


def semantic_sha256(payload: Any) -> str:
    return sha256_bytes(canonical_json_bytes(payload))


def atomic_write_bytes(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    atomic_write_bytes(path, pretty_json_bytes(dict(payload)))


def git_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    head = result.stdout.strip().lower()
    if result.returncode != 0 or re.fullmatch(r"[0-9a-f]{40}", head) is None:
        raise ArchiveContractError("git_head_unavailable_or_invalid")
    return head


def builder_identity() -> dict[str, str]:
    return {
        "git_head": git_head(),
        "builder_sha256": sha256_file(Path(__file__).resolve()),
    }


def verify_builder_identity(expected: Mapping[str, str]) -> None:
    if builder_identity() != dict(expected):
        raise ArchiveContractError("builder_or_git_head_changed_during_collection")


def parse_utc(value: Any, *, field: str) -> datetime:
    raw = str(value or "").strip()
    if UTC_EXACT.fullmatch(raw) is None:
        raise ArchiveContractError(f"{field}_not_exact_utc")
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ArchiveContractError(f"{field}_not_timezone_aware")
    return parsed.astimezone(timezone.utc)


def utc_iso(value: datetime) -> str:
    normalized = value.astimezone(timezone.utc)
    if normalized.microsecond:
        text = normalized.isoformat(timespec="microseconds")
    else:
        text = normalized.isoformat(timespec="seconds")
    return text.replace("+00:00", "Z")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def strict_iso_date(value: Any, *, field: str) -> date:
    raw = str(value or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw) is None:
        raise ArchiveContractError(f"{field}_invalid_date")
    try:
        parsed = date.fromisoformat(raw)
    except ValueError as exc:
        raise ArchiveContractError(f"{field}_invalid_date") from exc
    if parsed.isoformat() != raw:
        raise ArchiveContractError(f"{field}_invalid_date")
    return parsed


def parse_cboe_date(value: Any, *, field: str) -> date:
    raw = str(value or "").strip()
    for pattern in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, pattern).date()
        except ValueError:
            continue
    raise ArchiveContractError(f"{field}_invalid_date")


def finite_number(
    value: Any,
    *,
    field: str,
    strictly_positive: bool = False,
    allow_negative: bool = False,
) -> float:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ArchiveContractError(f"{field}_invalid_number") from exc
    if not math.isfinite(parsed):
        raise ArchiveContractError(f"{field}_non_finite")
    if strictly_positive and parsed <= 0:
        raise ArchiveContractError(f"{field}_not_positive")
    if not strictly_positive and not allow_negative and parsed < 0:
        raise ArchiveContractError(f"{field}_negative")
    return parsed


def nonnegative_integer(value: Any, *, field: str) -> int:
    raw = str(value or "").strip()
    if re.fullmatch(r"\d+", raw) is None:
        raise ArchiveContractError(f"{field}_invalid_integer")
    return int(raw)


def subtract_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year - years)
    except ValueError:
        return value.replace(year=value.year - years, day=28)


def safe_blocker(exc: BaseException) -> str:
    text = f"{type(exc).__name__}:{exc}"
    secret = os.environ.get("FRED_API_KEY", "")
    if secret:
        text = text.replace(secret, "<redacted>")
    text = re.sub(r"(?i)(api_key=)[^&\s]+", r"\1<redacted>", text)
    return text[:1000]


def raw_contains_secret(raw: bytes, secret: str) -> bool:
    if not secret:
        return False
    variants = {
        secret,
        quote(secret, safe=""),
    }
    return any(value.encode("utf-8") in raw for value in variants if value)


def public_https_url(value: Any, *, field: str) -> str:
    """Return a credential-free public HTTPS URL or fail closed."""
    raw = str(value or "").strip()
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise ArchiveContractError(f"{field}_invalid_url") from exc
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.query
        or parsed.fragment
    ):
        raise ArchiveContractError(f"{field}_credential_bearing_or_nonpublic_url")
    if any(character in raw for character in "\r\n"):
        raise ArchiveContractError(f"{field}_invalid_url")
    return raw


def network_origin(value: Any, *, field: str) -> tuple[str, int]:
    """Validate a network hop without ever returning its query string."""
    raw = str(value or "").strip()
    try:
        parsed = urlsplit(raw)
        port = parsed.port or 443
    except ValueError as exc:
        raise ArchiveContractError(f"{field}_invalid_url") from exc
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or any(character in raw for character in "\r\n")
    ):
        raise ArchiveContractError(f"{field}_unapproved_origin")
    return parsed.hostname.lower().rstrip("."), port


def sanitized_network_url(value: Any, *, field: str) -> str:
    """Bind a final URL while stripping secret-bearing query material."""
    raw = str(value or "").strip()
    network_origin(raw, field=field)
    parsed = urlsplit(raw)
    hostname = str(parsed.hostname or "").lower().rstrip(".")
    netloc = hostname if parsed.port in (None, 443) else f"{hostname}:{parsed.port}"
    return urlunsplit(("https", netloc, parsed.path or "/", "", ""))


def load_contract(path: Path) -> dict[str, Any]:
    if path.resolve() != DEFAULT_CONTRACT.resolve():
        raise ArchiveContractError("noncanonical_contract_path")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArchiveContractError("contract_unreadable") from exc
    if not isinstance(payload, dict):
        raise ArchiveContractError("contract_root_not_object")
    observed = semantic_sha256(payload)
    if observed != CANONICAL_CONTRACT_SEMANTIC_SHA256:
        raise ArchiveContractError(
            f"canonical_contract_semantic_hash_mismatch:{observed}"
        )
    if payload.get("schema_version") != "run287-chameleon-forward-archive-contract-v1":
        raise ArchiveContractError("contract_schema_mismatch")
    if payload.get("mode") != "RESEARCH_ONLY_REPORT_ONLY":
        raise ArchiveContractError("contract_mode_not_report_only")
    truth = payload.get("truth_policy") or {}
    if truth.get("official_network_capture") != "FORWARD_PIT":
        raise ArchiveContractError("network_truth_policy_changed")
    if truth.get("fixture_or_supplied_file_capture") != "FREE_PROXY":
        raise ArchiveContractError("fixture_truth_policy_changed")
    if truth.get("pit_verified_emitted_by_this_collector") is not False:
        raise ArchiveContractError("pit_verified_not_forbidden")
    if truth.get("historical_ab_allowed") is not False:
        raise ArchiveContractError("historical_ab_not_forbidden")
    collection = payload.get("collection") or {}
    if collection.get("network_redirect_policy") != "HTTPS_SAME_ORIGIN_EVERY_HOP":
        raise ArchiveContractError("network_redirect_policy_changed")
    if (
        collection.get("network_response_read_policy")
        != "CONTENT_LENGTH_PREFLIGHT_PLUS_BOUNDED_STREAM"
    ):
        raise ArchiveContractError("network_response_read_policy_changed")
    if (
        collection.get("writer_policy")
        != "OS_ADVISORY_SINGLE_WRITER_ACROSS_RECOVERY_CAPTURE_AND_COMMIT"
    ):
        raise ArchiveContractError("archive_writer_policy_changed")
    if int(collection.get("writer_lock_timeout_seconds", -1)) != 30:
        raise ArchiveContractError("archive_writer_timeout_changed")
    if (
        collection.get("source_text_encoding_policy")
        != "STRICT_UTF8_WITH_OPTIONAL_BOM"
    ):
        raise ArchiveContractError("source_text_encoding_policy_changed")
    archive = payload.get("archive") or {}
    if (
        archive.get("verified_unindexed_snapshot_policy")
        != "RECOVER_SINGLE_EXACT_ORPHAN_BEFORE_NEXT_CAPTURE"
    ):
        raise ArchiveContractError("orphan_recovery_policy_changed")
    if (
        archive.get("idempotent_receipt_policy")
        != "PRESERVE_MANIFEST_AND_INDEX_ENTRY_HASHES"
    ):
        raise ArchiveContractError("idempotent_receipt_policy_changed")
    if (
        truth.get("available_from_precision")
        != "PRESERVE_RUNTIME_MICROSECONDS_NO_FLOOR"
    ):
        raise ArchiveContractError("available_from_precision_policy_changed")
    fred = payload.get("fred") or {}
    if (
        fred.get("observation_date_policy")
        != "EVERY_ROW_INSIDE_INCLUSIVE_REQUEST_WINDOW"
    ):
        raise ArchiveContractError("fred_observation_date_policy_changed")
    if fred.get("response_secret_policy") != "REJECT_ACTIVE_API_KEY_IN_RAW_RESPONSE":
        raise ArchiveContractError("fred_response_secret_policy_changed")
    cboe = payload.get("cboe") or {}
    if int(cboe.get("daily_options_max_completed_nyse_session_lag", -1)) != 1:
        raise ArchiveContractError("daily_options_freshness_policy_changed")
    cross_asset = payload.get("cross_asset") or {}
    if (
        cross_asset.get("provenance_url_policy")
        != "PUBLIC_HTTPS_WITHOUT_USERINFO_QUERY_PARAMS_OR_FRAGMENT"
    ):
        raise ArchiveContractError("cross_asset_provenance_url_policy_changed")
    safety = payload.get("safety") or {}
    if safety.get("report_only") is not True:
        raise ArchiveContractError("report_only_not_frozen")
    if any(
        value is not False
        for key, value in safety.items()
        if key != "report_only"
    ):
        raise ArchiveContractError("unsafe_contract_permission")
    return payload


def validate_archive_root(root: Path) -> None:
    if root.exists() and root.is_symlink():
        raise ArchiveContractError("archive_root_symlink_forbidden")
    root.mkdir(parents=True, exist_ok=True)
    for relative in (
        Path("objects"),
        Path("objects/raw"),
        Path("objects/normalized"),
        Path("snapshots"),
    ):
        child = root / relative
        if child.exists() and child.is_symlink():
            label = str(relative).replace("\\", "_").replace("/", "_")
            raise ArchiveContractError(f"archive_{label}_symlink_forbidden")


def acquire_archive_writer_lock(root: Path, timeout_seconds: float) -> Any:
    """Hold one OS-released writer lock across recovery and publication."""
    path = root / ".writer.lock"
    if path.exists() and path.is_symlink():
        raise ArchiveContractError("archive_writer_lock_symlink_forbidden")
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise ArchiveContractError("archive_writer_lock_open_failed") from exc
    handle = os.fdopen(descriptor, "r+b", buffering=0)
    try:
        if path.is_symlink():
            raise ArchiveContractError("archive_writer_lock_symlink_forbidden")
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            os.fsync(handle.fileno())
        deadline = time.monotonic() + max(float(timeout_seconds), 0.0)
        while True:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return handle
            except (BlockingIOError, OSError) as exc:
                if time.monotonic() >= deadline:
                    raise ArchiveContractError("archive_writer_lock_timeout") from exc
                time.sleep(0.05)
    except Exception:
        handle.close()
        raise


def release_archive_writer_lock(handle: Any) -> None:
    if handle is None or handle.closed:
        return
    try:
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
    finally:
        handle.close()


def validate_object_path(root: Path, relative: str, digest: str) -> Path:
    if HEX64.fullmatch(digest) is None:
        raise ArchiveContractError("invalid_object_digest")
    expected = {
        f"objects/raw/{digest}",
        f"objects/normalized/{digest}.jsonl",
    }
    normalized = str(Path(relative)).replace("\\", "/")
    if normalized not in expected:
        raise ArchiveContractError("object_path_not_content_addressed")
    path = root / Path(normalized)
    if path.is_symlink() or not path.is_file() or sha256_file(path) != digest:
        raise ArchiveContractError(f"object_hash_mismatch:{normalized}")
    return path


def index_hash(payload: Mapping[str, Any]) -> str:
    material = dict(payload)
    material.pop("entry_sha256", None)
    return semantic_sha256(material)


def load_archive_index(
    root: Path,
    contract_sha256: str,
    *,
    allow_unindexed_snapshots: bool = False,
) -> list[dict[str, Any]]:
    index_path = root / "archive_index.jsonl"
    snapshots_root = root / "snapshots"
    snapshot_dirs: list[Path] = []
    if snapshots_root.exists():
        linked_entries = sorted(
            path.name for path in snapshots_root.iterdir() if path.is_symlink()
        )
        if linked_entries:
            raise ArchiveContractError(
                "snapshot_symlink_forbidden:" + ",".join(linked_entries)
            )
        snapshot_dirs = sorted(
            path for path in snapshots_root.iterdir() if path.is_dir()
        )
        non_directories = sorted(
            path.name for path in snapshots_root.iterdir() if not path.is_dir()
        )
        if non_directories:
            raise ArchiveContractError(
                "unexpected_snapshot_entries:" + ",".join(non_directories)
            )
        staging = sorted(
            path.name for path in snapshot_dirs if path.name.startswith(".staging-")
        )
        if staging:
            raise ArchiveContractError(
                "incomplete_snapshot_staging_present:" + ",".join(staging)
            )
    if not index_path.exists():
        if snapshot_dirs and not allow_unindexed_snapshots:
            raise ArchiveContractError("snapshots_present_without_archive_index")
        return []
    if index_path.is_symlink():
        raise ArchiveContractError("archive_index_symlink_forbidden")

    entries: list[dict[str, Any]] = []
    previous = ""
    previous_time: datetime | None = None
    seen_ids: set[str] = set()
    seen_times: set[str] = set()
    for line_number, line in enumerate(
        index_path.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            raise ArchiveContractError(f"blank_archive_index_line:{line_number}")
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ArchiveContractError(
                f"invalid_archive_index_json:{line_number}"
            ) from exc
        if not isinstance(entry, dict):
            raise ArchiveContractError(f"archive_index_row_not_object:{line_number}")
        snapshot_id = str(entry.get("snapshot_id") or "")
        collected_at = str(entry.get("collected_at_utc") or "")
        if not snapshot_id or snapshot_id in seen_ids:
            raise ArchiveContractError("duplicate_or_blank_snapshot_id")
        if not collected_at or collected_at in seen_times:
            raise ArchiveContractError("duplicate_or_blank_collection_time")
        parsed_time = parse_utc(collected_at, field="index_collected_at")
        if previous_time is not None and parsed_time <= previous_time:
            raise ArchiveContractError("archive_index_not_strictly_chronological")
        if str(entry.get("previous_entry_sha256") or "") != previous:
            raise ArchiveContractError("archive_index_previous_hash_mismatch")
        observed_hash = index_hash(entry)
        if str(entry.get("entry_sha256") or "") != observed_hash:
            raise ArchiveContractError("archive_index_entry_hash_mismatch")
        manifest_path = snapshots_root / snapshot_id / "manifest.json"
        manifest_sha = str(entry.get("snapshot_manifest_sha256") or "")
        if (
            HEX64.fullmatch(manifest_sha) is None
            or manifest_path.is_symlink()
            or not manifest_path.is_file()
            or sha256_file(manifest_path) != manifest_sha
        ):
            raise ArchiveContractError(
                f"snapshot_manifest_hash_mismatch:{snapshot_id}"
            )
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ArchiveContractError(
                f"snapshot_manifest_unreadable:{snapshot_id}"
            ) from exc
        if not isinstance(manifest, dict):
            raise ArchiveContractError(f"snapshot_manifest_not_object:{snapshot_id}")
        if manifest.get("snapshot_id") != snapshot_id:
            raise ArchiveContractError(f"snapshot_manifest_id_mismatch:{snapshot_id}")
        if manifest.get("collected_at_utc") != collected_at:
            raise ArchiveContractError(
                f"snapshot_manifest_collection_time_mismatch:{snapshot_id}"
            )
        if (
            manifest.get("contract_semantic_sha256")
            != contract_sha256
        ):
            raise ArchiveContractError(f"snapshot_contract_drift:{snapshot_id}")
        if manifest.get("historical_ab_allowed") is not False:
            raise ArchiveContractError(f"snapshot_historical_ab_enabled:{snapshot_id}")
        if any(
            manifest.get(key) is not expected
            for key, expected in SAFETY.items()
        ):
            raise ArchiveContractError(f"snapshot_safety_drift:{snapshot_id}")
        for source in manifest.get("sources") or []:
            if not isinstance(source, dict):
                raise ArchiveContractError(
                    f"snapshot_source_not_object:{snapshot_id}"
                )
            if source.get("truth_class") == "PIT_VERIFIED":
                raise ArchiveContractError(
                    f"snapshot_pit_verified_forbidden:{snapshot_id}"
                )
            raw_sha = str(source.get("raw_sha256") or "")
            normalized_sha = str(source.get("normalized_sha256") or "")
            raw_path = str(source.get("raw_object") or "")
            normalized_path = str(source.get("normalized_object") or "")
            if raw_sha or normalized_sha or raw_path or normalized_path:
                validate_object_path(root, raw_path, raw_sha)
                validate_object_path(root, normalized_path, normalized_sha)
        entries.append(entry)
        seen_ids.add(snapshot_id)
        seen_times.add(collected_at)
        previous = observed_hash
        previous_time = parsed_time

    indexed_ids = {str(entry["snapshot_id"]) for entry in entries}
    directory_ids = {path.name for path in snapshot_dirs}
    missing = sorted(indexed_ids - directory_ids)
    extra = sorted(directory_ids - indexed_ids)
    if missing or (extra and not allow_unindexed_snapshots):
        raise ArchiveContractError(
            "snapshot_index_directory_mismatch:"
            f"missing={','.join(missing)}:extra={','.join(extra)}"
        )
    return entries


def verify_recoverable_snapshot(
    root: Path,
    snapshot_id: str,
    contract_sha256: str,
) -> tuple[dict[str, Any], str]:
    snapshot_dir = root / "snapshots" / snapshot_id
    manifest_path = snapshot_dir / "manifest.json"
    if snapshot_dir.is_symlink() or manifest_path.is_symlink() or not manifest_path.is_file():
        raise ArchiveContractError(f"orphan_snapshot_manifest_missing:{snapshot_id}")
    raw = manifest_path.read_bytes()
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArchiveContractError(
            f"orphan_snapshot_manifest_unreadable:{snapshot_id}"
        ) from exc
    if not isinstance(manifest, dict):
        raise ArchiveContractError(f"orphan_snapshot_manifest_not_object:{snapshot_id}")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ArchiveContractError(f"orphan_snapshot_schema_mismatch:{snapshot_id}")
    if manifest.get("snapshot_id") != snapshot_id:
        raise ArchiveContractError(f"orphan_snapshot_id_mismatch:{snapshot_id}")
    collected_at = parse_utc(
        manifest.get("collected_at_utc"), field="orphan_collected_at"
    )
    timestamp_key = collected_at.strftime("%Y%m%dT%H%M%SZ")
    if not snapshot_id.startswith(f"{timestamp_key}-"):
        raise ArchiveContractError(f"orphan_snapshot_timestamp_mismatch:{snapshot_id}")
    if manifest.get("contract_semantic_sha256") != contract_sha256:
        raise ArchiveContractError(f"orphan_snapshot_contract_drift:{snapshot_id}")
    if manifest.get("archive_passed") is not True:
        raise ArchiveContractError(f"orphan_snapshot_not_passed:{snapshot_id}")
    if manifest.get("historical_ab_allowed") is not False:
        raise ArchiveContractError(f"orphan_snapshot_historical_ab_enabled:{snapshot_id}")
    if manifest.get("pit_verified_emitted") is not False:
        raise ArchiveContractError(f"orphan_snapshot_pit_verified:{snapshot_id}")
    if any(manifest.get(key) is not expected for key, expected in SAFETY.items()):
        raise ArchiveContractError(f"orphan_snapshot_safety_drift:{snapshot_id}")
    git_commit = str(manifest.get("git_head") or "")
    builder_sha = str(manifest.get("builder_sha256") or "")
    if re.fullmatch(r"[0-9a-f]{40}", git_commit) is None or HEX64.fullmatch(builder_sha) is None:
        raise ArchiveContractError(f"orphan_snapshot_builder_identity_invalid:{snapshot_id}")

    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ArchiveContractError(f"orphan_snapshot_sources_invalid:{snapshot_id}")
    source_ids: set[str] = set()
    missing_count = 0
    partial_count = 0
    captured_count = 0
    source_truth_counts: Counter[str] = Counter()
    row_truth_counts: Counter[str] = Counter()
    for source in sources:
        if not isinstance(source, dict):
            raise ArchiveContractError(f"orphan_snapshot_source_not_object:{snapshot_id}")
        source_id = str(source.get("source_id") or "")
        if not source_id or source_id in source_ids:
            raise ArchiveContractError(f"orphan_snapshot_source_id_invalid:{snapshot_id}")
        source_ids.add(source_id)
        status = str(source.get("status") or "")
        mode = str(source.get("mode") or "")
        truth = source.get("truth_class")
        if status == "missing_or_unavailable":
            missing_count += 1
            if mode != "missing" or truth is not None:
                raise ArchiveContractError(f"orphan_snapshot_missing_source_invalid:{source_id}")
            continue
        if status not in {"ready", "partial"}:
            raise ArchiveContractError(f"orphan_snapshot_present_source_invalid:{source_id}")
        captured_count += 1
        partial_count += status == "partial"
        row_count = int(source.get("normalized_row_count") or 0)
        if row_count <= 0:
            raise ArchiveContractError(f"orphan_snapshot_empty_source:{source_id}")
        if mode == "official_network":
            if truth != "FORWARD_PIT":
                raise ArchiveContractError(f"orphan_snapshot_network_truth_invalid:{source_id}")
            requested = public_https_url(
                source.get("public_url"), field=f"orphan_{source_id}_public_url"
            )
            resolved = sanitized_network_url(
                source.get("resolved_url"), field=f"orphan_{source_id}_resolved_url"
            )
            if network_origin(requested, field="orphan_requested_origin") != network_origin(
                resolved, field="orphan_resolved_origin"
            ):
                raise ArchiveContractError(f"orphan_snapshot_network_origin_invalid:{source_id}")
        elif mode == "fixture":
            if truth != "FREE_PROXY" or source.get("resolved_url"):
                raise ArchiveContractError(f"orphan_snapshot_fixture_truth_invalid:{source_id}")
        else:
            raise ArchiveContractError(f"orphan_snapshot_source_mode_invalid:{source_id}")
        source_truth_counts[str(truth)] += 1
        row_truth_counts[str(truth)] += row_count
        validate_object_path(
            root,
            str(source.get("raw_object") or ""),
            str(source.get("raw_sha256") or ""),
        )
        validate_object_path(
            root,
            str(source.get("normalized_object") or ""),
            str(source.get("normalized_sha256") or ""),
        )

    expected_status = (
        READY_PARTIAL_STATUS if missing_count or partial_count else READY_STATUS
    )
    expected_fields = {
        "status": expected_status,
        "source_expected_count": len(sources),
        "source_captured_count": captured_count,
        "source_missing_count": missing_count,
        "source_partial_count": partial_count,
        "source_truth_class_counts": dict(sorted(source_truth_counts.items())),
        "normalized_row_truth_class_counts": dict(sorted(row_truth_counts.items())),
    }
    if any(manifest.get(key) != value for key, value in expected_fields.items()):
        raise ArchiveContractError(f"orphan_snapshot_counter_mismatch:{snapshot_id}")
    identity = {
        "schema_version": SCHEMA_VERSION,
        "collected_at_utc": manifest["collected_at_utc"],
        "git_head": git_commit,
        "builder_sha256": builder_sha,
        "contract_semantic_sha256": contract_sha256,
        "fixture_mode": manifest.get("fixture_mode"),
        "sources": sources,
    }
    identity_sha = semantic_sha256(identity)
    if manifest.get("snapshot_identity_sha256") != identity_sha:
        raise ArchiveContractError(f"orphan_snapshot_identity_mismatch:{snapshot_id}")
    if snapshot_id != f"{timestamp_key}-{identity_sha[:16]}":
        raise ArchiveContractError(f"orphan_snapshot_name_mismatch:{snapshot_id}")
    return manifest, sha256_bytes(raw)


def recover_verified_unindexed_snapshot(
    root: Path, contract_sha256: str
) -> list[dict[str, Any]]:
    entries = load_archive_index(
        root,
        contract_sha256,
        allow_unindexed_snapshots=True,
    )
    snapshots_root = root / "snapshots"
    directory_ids = (
        {
            path.name
            for path in snapshots_root.iterdir()
            if path.is_dir() and not path.name.startswith(".staging-")
        }
        if snapshots_root.exists()
        else set()
    )
    indexed_ids = {str(entry["snapshot_id"]) for entry in entries}
    orphan_ids = sorted(directory_ids - indexed_ids)
    if not orphan_ids:
        return load_archive_index(root, contract_sha256)
    if len(orphan_ids) != 1:
        raise ArchiveContractError(
            "multiple_unindexed_snapshots:" + ",".join(orphan_ids)
        )
    snapshot_id = orphan_ids[0]
    manifest, manifest_sha = verify_recoverable_snapshot(
        root, snapshot_id, contract_sha256
    )
    collected_at = parse_utc(
        manifest["collected_at_utc"], field="orphan_collected_at"
    )
    if entries:
        latest = parse_utc(
            entries[-1]["collected_at_utc"], field="latest_collection_time"
        )
        if collected_at <= latest:
            raise ArchiveContractError("orphan_snapshot_not_chronological")
    entry = {
        "schema_version": "run287-chameleon-forward-archive-index-v1",
        "snapshot_id": snapshot_id,
        "collected_at_utc": manifest["collected_at_utc"],
        "snapshot_manifest_sha256": manifest_sha,
        "source_captured_count": manifest["source_captured_count"],
        "source_missing_count": manifest["source_missing_count"],
        "previous_entry_sha256": (
            str(entries[-1]["entry_sha256"]) if entries else ""
        ),
    }
    entry["entry_sha256"] = index_hash(entry)
    write_index(root / "archive_index.jsonl", [*entries, entry])
    return load_archive_index(root, contract_sha256)


def stable_read(path: Path, consumed: dict[str, str]) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise ArchiveContractError(f"fixture_not_regular_file:{path.name}")
    raw = path.read_bytes()
    digest = sha256_bytes(raw)
    consumed[str(path.resolve())] = digest
    return raw


def verify_consumed_inputs(consumed: Mapping[str, str]) -> None:
    for raw_path, expected in consumed.items():
        path = Path(raw_path)
        if not path.is_file() or path.is_symlink() or sha256_file(path) != expected:
            raise ArchiveContractError(
                f"fixture_changed_during_collection:{path.name}"
            )


def decode_csv(raw: bytes, *, source_id: str) -> list[list[str]]:
    try:
        text = raw.decode("utf-8-sig")
        return list(csv.reader(io.StringIO(text)))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ArchiveContractError(f"{source_id}_csv_unreadable") from exc


def normalized_header(row: Iterable[Any]) -> list[str]:
    return [
        re.sub(r"\s+", "_", str(value).replace("\ufeff", "").strip().lower())
        for value in row
    ]


def find_header(
    rows: list[list[str]],
    required: set[str],
    *,
    source_id: str,
) -> tuple[int, dict[str, int]]:
    matches: list[tuple[int, list[str]]] = []
    for index, row in enumerate(rows):
        normalized = normalized_header(row)
        if required.issubset(set(normalized)):
            matches.append((index, normalized))
    if len(matches) != 1:
        raise ArchiveContractError(
            f"{source_id}_header_match_count:{len(matches)}"
        )
    index, header = matches[0]
    duplicates = sorted(
        item for item in set(header) if item and header.count(item) > 1
    )
    if duplicates:
        raise ArchiveContractError(
            f"{source_id}_colliding_headers:{','.join(duplicates)}"
        )
    return index, {name: position for position, name in enumerate(header)}


def row_value(
    row: list[str], columns: Mapping[str, int], name: str, *, source_id: str
) -> str:
    position = columns[name]
    if position >= len(row):
        raise ArchiveContractError(f"{source_id}_short_csv_row")
    return row[position]


def normalize_fred(
    raw: bytes,
    *,
    source_id: str,
    series_id: str,
    requested_vintage_date: str,
    requested_observation_start: str,
    requested_observation_end: str,
    missing_token: str,
) -> tuple[list[dict[str, Any]], int]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArchiveContractError(f"{source_id}_json_unreadable") from exc
    if not isinstance(payload, dict):
        raise ArchiveContractError(f"{source_id}_root_not_object")
    for field in (
        "realtime_start",
        "realtime_end",
        "observation_start",
        "observation_end",
        "limit",
        "offset",
        "sort_order",
        "count",
        "observations",
    ):
        if field not in payload:
            raise ArchiveContractError(f"{source_id}_missing_{field}")
    if payload["realtime_start"] != requested_vintage_date:
        raise ArchiveContractError(f"{source_id}_realtime_start_mismatch")
    if payload["realtime_end"] != requested_vintage_date:
        raise ArchiveContractError(f"{source_id}_realtime_end_mismatch")
    if payload["observation_start"] != requested_observation_start:
        raise ArchiveContractError(f"{source_id}_observation_start_mismatch")
    if payload["observation_end"] != requested_observation_end:
        raise ArchiveContractError(f"{source_id}_observation_end_mismatch")
    if payload["sort_order"] != "asc":
        raise ArchiveContractError(f"{source_id}_sort_order_mismatch")
    try:
        limit = int(payload["limit"])
        offset = int(payload["offset"])
    except (TypeError, ValueError) as exc:
        raise ArchiveContractError(f"{source_id}_pagination_metadata_invalid") from exc
    if limit != 100000 or offset != 0:
        raise ArchiveContractError(f"{source_id}_unexpected_pagination")
    observations = payload["observations"]
    if not isinstance(observations, list):
        raise ArchiveContractError(f"{source_id}_observations_not_list")
    try:
        count = int(payload["count"])
    except (TypeError, ValueError) as exc:
        raise ArchiveContractError(f"{source_id}_count_invalid") from exc
    if count != len(observations):
        raise ArchiveContractError(f"{source_id}_response_is_paginated_or_truncated")
    requested_start = strict_iso_date(
        requested_observation_start,
        field=f"{source_id}_requested_observation_start",
    )
    requested_end = strict_iso_date(
        requested_observation_end,
        field=f"{source_id}_requested_observation_end",
    )
    if requested_start > requested_end:
        raise ArchiveContractError(f"{source_id}_observation_window_inverted")

    rows: list[dict[str, Any]] = []
    missing_count = 0
    seen_dates: set[str] = set()
    previous_observed: date | None = None
    for observation in observations:
        if not isinstance(observation, dict):
            raise ArchiveContractError(f"{source_id}_observation_not_object")
        if observation.get("realtime_start") != requested_vintage_date:
            raise ArchiveContractError(f"{source_id}_row_realtime_start_mismatch")
        if observation.get("realtime_end") != requested_vintage_date:
            raise ArchiveContractError(f"{source_id}_row_realtime_end_mismatch")
        observed_date = strict_iso_date(
            observation.get("date"), field=f"{source_id}_observation"
        )
        if not requested_start <= observed_date <= requested_end:
            raise ArchiveContractError(
                f"{source_id}_observation_outside_requested_window"
            )
        observed = observed_date.isoformat()
        if observed in seen_dates:
            raise ArchiveContractError(f"{source_id}_duplicate_observation_date")
        if previous_observed is not None and observed_date <= previous_observed:
            raise ArchiveContractError(
                f"{source_id}_observation_order_mismatch"
            )
        seen_dates.add(observed)
        previous_observed = observed_date
        raw_value = str(observation.get("value") or "").strip()
        if raw_value == missing_token:
            missing_count += 1
            continue
        value = finite_number(
            raw_value, field=f"{source_id}_value", allow_negative=True
        )
        rows.append(
            {
                "source_observation_date": observed,
                "value": value,
                "series_id": series_id,
                "vintage_start": requested_vintage_date,
                "vintage_end": requested_vintage_date,
            }
        )
    rows.sort(key=lambda row: row["source_observation_date"])
    return rows, missing_count


def normalize_cboe_index(
    raw: bytes, *, source_id: str, symbol: str
) -> list[dict[str, Any]]:
    rows = decode_csv(raw, source_id=source_id)
    candidates: list[tuple[int, list[str], str]] = []
    symbol_column = str(symbol).strip().lower()
    for index, row in enumerate(rows):
        header = normalized_header(row)
        value_columns = [
            name for name in ("close", symbol_column) if name in header
        ]
        if "date" in header and len(value_columns) == 1:
            candidates.append((index, header, value_columns[0]))
        elif "date" in header and len(value_columns) > 1:
            raise ArchiveContractError(f"{source_id}_ambiguous_value_column")
    if len(candidates) != 1:
        raise ArchiveContractError(
            f"{source_id}_header_match_count:{len(candidates)}"
        )
    header_index, header, value_column = candidates[0]
    duplicates = sorted(
        item for item in set(header) if item and header.count(item) > 1
    )
    if duplicates:
        raise ArchiveContractError(
            f"{source_id}_colliding_headers:{','.join(duplicates)}"
        )
    columns = {name: position for position, name in enumerate(header)}
    output: list[dict[str, Any]] = []
    seen_dates: set[str] = set()
    for row in rows[header_index + 1 :]:
        if not any(str(value).strip() for value in row):
            continue
        observed = parse_cboe_date(
            row_value(row, columns, "date", source_id=source_id),
            field=f"{source_id}_observation",
        ).isoformat()
        if observed in seen_dates:
            raise ArchiveContractError(f"{source_id}_duplicate_observation_date")
        seen_dates.add(observed)
        close = finite_number(
            row_value(row, columns, value_column, source_id=source_id),
            field=f"{source_id}_close",
            strictly_positive=True,
        )
        output.append(
            {
                "source_observation_date": observed,
                "value": close,
                "instrument": symbol.upper(),
                "value_field": "close",
            }
        )
    output.sort(key=lambda row: row["source_observation_date"])
    return output


def one_regex_match(
    text: str, pattern: str, *, source_id: str, field: str
) -> re.Match[str]:
    matches = list(re.finditer(pattern, text, flags=re.DOTALL))
    if len(matches) != 1:
        raise ArchiveContractError(
            f"{source_id}_{field}_match_count:{len(matches)}"
        )
    return matches[0]


def completed_nyse_sessions(captured_at: datetime) -> list[date]:
    """Return holiday-aware NYSE sessions whose official close has passed."""
    try:
        import pandas_market_calendars as mcal
    except ImportError as exc:
        raise ArchiveContractError("nyse_calendar_dependency_unavailable") from exc
    try:
        calendar = mcal.get_calendar("NYSE")
        schedule = calendar.schedule(
            start_date=(captured_at.date() - timedelta(days=21)).isoformat(),
            end_date=captured_at.date().isoformat(),
        )
    except Exception as exc:
        raise ArchiveContractError("nyse_calendar_resolution_failed") from exc
    sessions: list[date] = []
    for session_label, row in schedule.iterrows():
        market_close = row["market_close"].to_pydatetime().astimezone(timezone.utc)
        if market_close <= captured_at.astimezone(timezone.utc):
            sessions.append(session_label.date())
    if not sessions:
        raise ArchiveContractError("no_completed_nyse_session_for_capture")
    return sessions


def normalize_cboe_daily_options_page(
    raw: bytes,
    *,
    source_id: str,
    captured_at: datetime,
    maximum_completed_session_lag: int,
) -> list[dict[str, Any]]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ArchiveContractError(f"{source_id}_html_unreadable") from exc
    selected = one_regex_match(
        text,
        r'\\"selectedDate\\":\\"(\d{4}-\d{2}-\d{2})\\"',
        source_id=source_id,
        field="selected_date",
    ).group(1)
    observed = strict_iso_date(
        selected, field=f"{source_id}_selected_date"
    )
    completed_sessions = completed_nyse_sessions(captured_at)
    if observed not in completed_sessions:
        raise ArchiveContractError(f"{source_id}_selected_date_not_completed_session")
    session_lag = sum(session > observed for session in completed_sessions)
    if session_lag > maximum_completed_session_lag:
        raise ArchiveContractError(
            f"{source_id}_stale_selected_date:lag={session_lag}"
        )
    observed_text = observed.isoformat()
    output: list[dict[str, Any]] = []
    for scope, label in (
        ("EQUITY", "EQUITY OPTIONS"),
        ("INDEX", "INDEX OPTIONS"),
    ):
        ratio_label = f"{scope} PUT/CALL RATIO"
        ratio_pattern = (
            r'\\"name\\":\\"'
            + re.escape(ratio_label)
            + r'\\",\\"value\\":\\"([^"\\]+)\\"'
        )
        ratio = finite_number(
            one_regex_match(
                text,
                ratio_pattern,
                source_id=source_id,
                field=f"{scope.lower()}_ratio",
            ).group(1),
            field=f"{source_id}_{scope.lower()}_ratio",
        )
        volume_pattern = (
            r'\\"'
            + re.escape(label)
            + r'\\"\s*:\s*\[\{\\"name\\":\\"VOLUME\\",'
            + r'\\"call\\":(\d+),\\"put\\":(\d+),\\"total\\":(\d+)\}'
        )
        volume_match = one_regex_match(
            text,
            volume_pattern,
            source_id=source_id,
            field=f"{scope.lower()}_volume",
        )
        call, put, total = (int(value) for value in volume_match.groups())
        if call <= 0:
            raise ArchiveContractError(
                f"{source_id}_{scope.lower()}_zero_call_volume"
            )
        if total != call + put:
            raise ArchiveContractError(
                f"{source_id}_{scope.lower()}_volume_total_mismatch"
            )
        if abs(ratio - put / call) > 0.02:
            raise ArchiveContractError(
                f"{source_id}_{scope.lower()}_ratio_volume_mismatch"
            )
        output.append(
            {
                "source_observation_date": observed_text,
                "value": ratio,
                "instrument": scope,
                "value_field": "put_call_ratio",
                "call_volume": call,
                "put_volume": put,
                "total_volume": total,
            }
        )
    output.sort(key=lambda item: item["instrument"])
    return output


def normalize_cross_asset(
    raw: bytes,
    *,
    source_id: str,
    required_tickers: Iterable[str],
    allowed_price_basis: Iterable[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    rows = decode_csv(raw, source_id=source_id)
    required_columns = {
        "ticker",
        "observation_date",
        "close",
        "price_basis",
        "provider",
        "source_url",
    }
    header_index, columns = find_header(
        rows, required_columns, source_id=source_id
    )
    required = {str(value).strip().upper() for value in required_tickers}
    allowed_basis = {str(value) for value in allowed_price_basis}
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    observed_tickers: set[str] = set()
    for row in rows[header_index + 1 :]:
        if not any(str(value).strip() for value in row):
            continue
        ticker = row_value(row, columns, "ticker", source_id=source_id).strip().upper()
        if ticker not in required:
            raise ArchiveContractError(f"{source_id}_unexpected_ticker:{ticker}")
        observed = strict_iso_date(
            row_value(row, columns, "observation_date", source_id=source_id),
            field=f"{source_id}_observation",
        ).isoformat()
        key = (ticker, observed)
        if key in seen:
            raise ArchiveContractError(f"{source_id}_duplicate_ticker_date")
        seen.add(key)
        price_basis = row_value(
            row, columns, "price_basis", source_id=source_id
        ).strip()
        if price_basis not in allowed_basis:
            raise ArchiveContractError(f"{source_id}_invalid_price_basis")
        provider = row_value(row, columns, "provider", source_id=source_id).strip()
        source_url = row_value(
            row, columns, "source_url", source_id=source_id
        ).strip()
        if (
            not provider
            or any(character in provider for character in "\r\n")
        ):
            raise ArchiveContractError(f"{source_id}_invalid_provider_provenance")
        source_url = public_https_url(
            source_url, field=f"{source_id}_source_url"
        )
        close = finite_number(
            row_value(row, columns, "close", source_id=source_id),
            field=f"{source_id}_close",
            strictly_positive=True,
        )
        output.append(
            {
                "source_observation_date": observed,
                "value": close,
                "instrument": ticker,
                "value_field": "close",
                "price_basis": price_basis,
                "upstream_provider": provider,
                "upstream_source_url": source_url,
            }
        )
        observed_tickers.add(ticker)
    output.sort(
        key=lambda item: (item["source_observation_date"], item["instrument"])
    )
    return output, sorted(required - observed_tickers)


def network_fetch(
    *,
    url: str,
    params: Mapping[str, Any] | None,
    timeout_seconds: int,
    maximum_bytes: int,
) -> tuple[bytes | None, str, datetime | None, str]:
    expected_origin = network_origin(url, field="network_requested_url")
    try:
        with requests.get(
            url,
            params=dict(params or {}),
            headers={"User-Agent": USER_AGENT},
            timeout=int(timeout_seconds),
            stream=True,
        ) as response:
            response.raise_for_status()
            hop_urls = [
                str(item.url or "") for item in list(response.history)
            ] + [str(response.url or "")]
            if not hop_urls or any(
                network_origin(hop, field="network_redirect_hop")
                != expected_origin
                for hop in hop_urls
            ):
                raise ArchiveContractError("network_redirect_origin_mismatch")
            final_url = sanitized_network_url(
                response.url, field="network_final_url"
            )
            content_length = str(response.headers.get("Content-Length") or "").strip()
            if content_length:
                if re.fullmatch(r"\d+", content_length) is None:
                    raise ArchiveContractError("network_content_length_invalid")
                if int(content_length) > maximum_bytes:
                    raise ArchiveContractError("official_network_response_too_large")
            chunks = bytearray()
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                if len(chunks) + len(chunk) > maximum_bytes:
                    raise ArchiveContractError("official_network_response_too_large")
                chunks.extend(chunk)
            raw = bytes(chunks)
    except requests.RequestException as exc:
        return None, type(exc).__name__, None, ""
    captured_at = utc_now()
    if not raw:
        raise ArchiveContractError("official_network_response_empty")
    return raw, "", captured_at, final_url


def missing_audit(
    *,
    source_id: str,
    provider: str,
    source_kind: str,
    public_url: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "provider": provider,
        "source_kind": source_kind,
        "status": "missing_or_unavailable",
        "mode": "missing",
        "public_url": public_url,
        "resolved_url": None,
        "public_request_params": {},
        "reason": reason,
        "truth_class": None,
        "captured_at_utc": None,
        "raw_sha256": None,
        "raw_object": None,
        "normalized_sha256": None,
        "normalized_object": None,
        "normalized_row_count": 0,
    }


def collect_sources(
    *,
    contract: Mapping[str, Any],
    source_bundle: Path | None,
    fixture_mode: bool,
    fixture_time: datetime | None,
    allow_network: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
    captures: list[dict[str, Any]] = []
    audits: list[dict[str, Any]] = []
    consumed: dict[str, str] = {}
    timeout = int(contract["collection"]["request_timeout_seconds"])
    maximum_bytes = int(contract["collection"]["maximum_raw_bytes_per_source"])
    missing_token = str(contract["fred"]["missing_value_token"])
    fred_endpoint = public_https_url(
        contract["fred"]["endpoint"], field="fred_endpoint"
    )
    fred_key_name = str(
        contract["collection"]["fred_api_key_environment_variable"]
    )
    fred_key = os.environ.get(fred_key_name, "")
    if fred_key and (
        fred_key.strip() != fred_key
        or any(character in fred_key for character in "\r\n")
    ):
        fred_key = ""

    for name, series_id in sorted(contract["fred"]["series"].items()):
        source_id = f"fred.{name}"
        history_years = int(
            contract["collection"]["fred_observation_history_years"]
        )
        fixture_path = (
            source_bundle / "fred" / f"{series_id}.json"
            if source_bundle is not None
            else None
        )
        raw: bytes | None = None
        error = ""
        resolved_url = ""
        if fixture_mode:
            if fixture_path is not None and fixture_path.is_file():
                raw = stable_read(fixture_path, consumed)
                captured_at = fixture_time
                mode = "fixture"
                truth_class = "FREE_PROXY"
                vintage_date = fixture_time.date().isoformat() if fixture_time else ""
                observation_start = subtract_years(
                    fixture_time.date(), history_years
                ).isoformat() if fixture_time else ""
                observation_end = vintage_date
            else:
                audits.append(
                    missing_audit(
                        source_id=source_id,
                        provider="FRED_ALFRED_API",
                        source_kind="FRED_SERIES_OBSERVATIONS",
                        public_url=fred_endpoint,
                        reason="fixture_file_missing",
                    )
                )
                continue
        elif allow_network and fred_key:
            request_date = utc_now().date()
            observation_start = subtract_years(
                request_date, history_years
            ).isoformat()
            observation_end = request_date.isoformat()
            params = {
                "series_id": series_id,
                "api_key": fred_key,
                "file_type": "json",
                "realtime_start": request_date.isoformat(),
                "realtime_end": request_date.isoformat(),
                "observation_start": observation_start,
                "observation_end": observation_end,
                "sort_order": "asc",
                "limit": 100000,
            }
            raw, error, captured_at, resolved_url = network_fetch(
                url=fred_endpoint,
                params=params,
                timeout_seconds=timeout,
                maximum_bytes=maximum_bytes,
            )
            if raw is None or captured_at is None:
                audits.append(
                    missing_audit(
                        source_id=source_id,
                        provider="FRED_ALFRED_API",
                        source_kind="FRED_SERIES_OBSERVATIONS",
                        public_url=fred_endpoint,
                        reason=f"network_unavailable:{error}",
                    )
                )
                continue
            mode = "official_network"
            truth_class = "FORWARD_PIT"
            vintage_date = request_date.isoformat()
        else:
            reason = (
                "fred_api_key_unavailable"
                if allow_network
                else "network_disabled"
            )
            audits.append(
                missing_audit(
                    source_id=source_id,
                    provider="FRED_ALFRED_API",
                    source_kind="FRED_SERIES_OBSERVATIONS",
                    public_url=fred_endpoint,
                    reason=reason,
                )
            )
            continue
        assert raw is not None and captured_at is not None
        if raw_contains_secret(raw, fred_key):
            raise ArchiveContractError(f"{source_id}_raw_response_contains_api_key")
        if len(raw) > maximum_bytes:
            raise ArchiveContractError(f"{source_id}_raw_too_large")
        normalized, missing_count = normalize_fred(
            raw,
            source_id=source_id,
            series_id=str(series_id),
            requested_vintage_date=vintage_date,
            requested_observation_start=observation_start,
            requested_observation_end=observation_end,
            missing_token=missing_token,
        )
        captures.append(
            {
                "source_id": source_id,
                "provider": "FRED_ALFRED_API",
                "source_kind": "FRED_SERIES_OBSERVATIONS",
                "mode": mode,
                "truth_class": truth_class,
                "public_url": fred_endpoint,
                "resolved_url": (
                    resolved_url if mode == "official_network" else ""
                ),
                "public_request_params": {
                    "series_id": series_id,
                    "file_type": "json",
                    "realtime_start": vintage_date,
                    "realtime_end": vintage_date,
                    "observation_start": observation_start,
                    "observation_end": observation_end,
                    "sort_order": "asc",
                    "limit": 100000,
                },
                "captured_at_utc": utc_iso(captured_at),
                "raw": raw,
                "rows": normalized,
                "missing_value_count": missing_count,
                "status": "ready" if normalized else "empty",
            }
        )

    for name, spec in sorted(contract["cboe"]["sources"].items()):
        source_id = f"cboe.{name}"
        public_url = public_https_url(
            spec["url"], field=f"{source_id}_public_url"
        )
        kind = str(spec["kind"])
        fixture_path = (
            source_bundle / Path(str(spec["fixture_path"]))
            if source_bundle is not None
            else None
        )
        raw = None
        error = ""
        resolved_url = ""
        if fixture_mode:
            if fixture_path is not None and fixture_path.is_file():
                raw = stable_read(fixture_path, consumed)
                captured_at = fixture_time
                mode = "fixture"
                truth_class = "FREE_PROXY"
            else:
                audits.append(
                    missing_audit(
                        source_id=source_id,
                        provider="CBOE",
                        source_kind=kind,
                        public_url=public_url,
                        reason="fixture_file_missing",
                    )
                )
                continue
        elif allow_network:
            raw, error, captured_at, resolved_url = network_fetch(
                url=public_url,
                params=None,
                timeout_seconds=timeout,
                maximum_bytes=maximum_bytes,
            )
            if raw is None or captured_at is None:
                audits.append(
                    missing_audit(
                        source_id=source_id,
                        provider="CBOE",
                        source_kind=kind,
                        public_url=public_url,
                        reason=f"network_unavailable:{error}",
                    )
                )
                continue
            mode = "official_network"
            truth_class = "FORWARD_PIT"
        else:
            audits.append(
                missing_audit(
                    source_id=source_id,
                    provider="CBOE",
                    source_kind=kind,
                    public_url=public_url,
                    reason="network_disabled",
                )
            )
            continue
        assert raw is not None and captured_at is not None
        if len(raw) > maximum_bytes:
            raise ArchiveContractError(f"{source_id}_raw_too_large")
        if kind == "INDEX_HISTORY":
            normalized = normalize_cboe_index(
                raw, source_id=source_id, symbol=name
            )
        elif kind == "DAILY_OPTIONS_PAGE":
            normalized = normalize_cboe_daily_options_page(
                raw,
                source_id=source_id,
                captured_at=captured_at,
                maximum_completed_session_lag=int(
                    contract["cboe"]["daily_options_max_completed_nyse_session_lag"]
                ),
            )
        else:
            raise ArchiveContractError(f"{source_id}_unknown_source_kind")
        captures.append(
            {
                "source_id": source_id,
                "provider": "CBOE",
                "source_kind": kind,
                "mode": mode,
                "truth_class": truth_class,
                "public_url": public_url,
                "resolved_url": (
                    resolved_url if mode == "official_network" else ""
                ),
                "public_request_params": {},
                "captured_at_utc": utc_iso(captured_at),
                "raw": raw,
                "rows": normalized,
                "missing_value_count": 0,
                "status": "ready" if normalized else "empty",
            }
        )

    cross_spec = contract["cross_asset"]
    cross_source_id = "cross_asset.daily_close"
    cross_fixture = (
        source_bundle / Path(str(cross_spec["fixture_path"]))
        if source_bundle is not None
        else None
    )
    if fixture_mode and cross_fixture is not None and cross_fixture.is_file():
        raw = stable_read(cross_fixture, consumed)
        if len(raw) > maximum_bytes:
            raise ArchiveContractError(f"{cross_source_id}_raw_too_large")
        normalized, missing_tickers = normalize_cross_asset(
            raw,
            source_id=cross_source_id,
            required_tickers=cross_spec["required_tickers"],
            allowed_price_basis=cross_spec["allowed_price_basis"],
        )
        captures.append(
            {
                "source_id": cross_source_id,
                "provider": "SOURCE_BUNDLE_DECLARED_PROVIDER",
                "source_kind": "CROSS_ASSET_DAILY_CLOSE",
                "mode": "fixture",
                "truth_class": "FREE_PROXY",
                "public_url": "",
                "resolved_url": "",
                "public_request_params": {},
                "captured_at_utc": utc_iso(fixture_time) if fixture_time else "",
                "raw": raw,
                "rows": normalized,
                "missing_value_count": 0,
                "missing_tickers": missing_tickers,
                "status": "partial" if missing_tickers else "ready",
            }
        )
    else:
        reason = (
            "fixture_file_missing"
            if fixture_mode
            else "trusted_network_provider_not_configured"
        )
        audits.append(
            missing_audit(
                source_id=cross_source_id,
                provider="UNCONFIGURED",
                source_kind="CROSS_ASSET_DAILY_CLOSE",
                public_url="",
                reason=reason,
            )
        )
    return captures, audits, consumed


def normalized_bytes(
    capture: Mapping[str, Any], raw_sha256: str
) -> tuple[bytes, list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    capture_time = parse_utc(capture["captured_at_utc"], field="captured_at")
    for raw_row in capture["rows"]:
        observation_date = strict_iso_date(
            raw_row.get("source_observation_date"),
            field=f"{capture['source_id']}_normalized_observation",
        )
        if observation_date > capture_time.date():
            raise ArchiveContractError(
                f"{capture['source_id']}_future_observation_date"
            )
        row = {
            "schema_version": "run287-chameleon-forward-observation-v1",
            "source_id": capture["source_id"],
            "provider": capture["provider"],
            "source_kind": capture["source_kind"],
            **dict(raw_row),
            "available_from": capture["captured_at_utc"],
            "collected_at_utc": capture["captured_at_utc"],
            "raw_sha256": raw_sha256,
            "truth_class": capture["truth_class"],
            "historical_ab_allowed": False,
        }
        if row["truth_class"] == "PIT_VERIFIED":
            raise ArchiveContractError("pit_verified_emission_forbidden")
        if parse_utc(row["available_from"], field="available_from") != capture_time:
            raise ArchiveContractError("available_from_before_capture")
        rows.append(row)
    raw = b"".join(canonical_json_bytes(row) + b"\n" for row in rows)
    return raw, rows


def materialize_sources(
    captures: Iterable[Mapping[str, Any]],
    missing_audits: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, bytes], dict[str, bytes]]:
    audits: list[dict[str, Any]] = [dict(item) for item in missing_audits]
    raw_objects: dict[str, bytes] = {}
    normalized_objects: dict[str, bytes] = {}
    for capture in captures:
        if not capture.get("rows"):
            raise ArchiveContractError(
                f"{capture.get('source_id')}_no_usable_observations"
            )
        raw = bytes(capture["raw"])
        raw_sha = sha256_bytes(raw)
        normalized_raw, normalized_rows = normalized_bytes(capture, raw_sha)
        normalized_sha = sha256_bytes(normalized_raw)
        raw_objects[raw_sha] = raw
        normalized_objects[normalized_sha] = normalized_raw
        observations = [
            str(row["source_observation_date"]) for row in normalized_rows
        ]
        audit = {
            "source_id": capture["source_id"],
            "provider": capture["provider"],
            "source_kind": capture["source_kind"],
            "status": capture["status"],
            "mode": capture["mode"],
            "public_url": capture["public_url"],
            "resolved_url": capture.get("resolved_url") or None,
            "public_request_params": capture["public_request_params"],
            "reason": "",
            "truth_class": capture["truth_class"],
            "captured_at_utc": capture["captured_at_utc"],
            "raw_sha256": raw_sha,
            "raw_object": f"objects/raw/{raw_sha}",
            "normalized_sha256": normalized_sha,
            "normalized_object": f"objects/normalized/{normalized_sha}.jsonl",
            "normalized_row_count": len(normalized_rows),
            "first_observation_date": min(observations) if observations else None,
            "last_observation_date": max(observations) if observations else None,
            "missing_value_count": int(capture.get("missing_value_count") or 0),
            "missing_tickers": list(capture.get("missing_tickers") or []),
        }
        if capture["mode"] != "official_network" and audit["truth_class"] != "FREE_PROXY":
            raise ArchiveContractError("nonnetwork_capture_claimed_forward_pit")
        if capture["mode"] == "official_network" and audit["truth_class"] != "FORWARD_PIT":
            raise ArchiveContractError("network_capture_not_forward_pit")
        if capture["mode"] == "official_network" and not audit["resolved_url"]:
            raise ArchiveContractError("network_capture_missing_resolved_url")
        if capture["mode"] != "official_network" and audit["resolved_url"]:
            raise ArchiveContractError("nonnnetwork_capture_has_resolved_url")
        audits.append(audit)
    audits.sort(key=lambda item: str(item["source_id"]))
    source_ids = [str(item["source_id"]) for item in audits]
    if len(source_ids) != len(set(source_ids)):
        raise ArchiveContractError("duplicate_source_audit_id")
    return audits, raw_objects, normalized_objects


def write_content_object(path: Path, raw: bytes, expected_sha256: str) -> None:
    if sha256_bytes(raw) != expected_sha256:
        raise ArchiveContractError("content_object_input_hash_mismatch")
    if path.exists():
        if not path.is_file() or path.is_symlink() or sha256_file(path) != expected_sha256:
            raise ArchiveContractError(f"existing_content_object_conflict:{path.name}")
        return
    atomic_write_bytes(path, raw)
    if sha256_file(path) != expected_sha256:
        raise ArchiveContractError(f"content_object_write_mismatch:{path.name}")


def write_index(path: Path, entries: Iterable[Mapping[str, Any]]) -> None:
    raw = b"".join(canonical_json_bytes(dict(entry)) + b"\n" for entry in entries)
    atomic_write_bytes(path, raw)


def build(args: argparse.Namespace) -> dict[str, Any]:
    output_root = repo_path(args.archive_root)
    writer_lock = None
    try:
        validate_archive_root(output_root)
        identity = builder_identity()
        contract = load_contract(repo_path(args.contract))
        launch = parse_utc(
            contract["launch_not_before_utc"], field="launch_not_before"
        )
        fixture_mode = bool(args.fixture_mode)
        allow_network = bool(args.allow_network)
        source_bundle = (
            repo_path(args.source_bundle) if str(args.source_bundle or "") else None
        )
        if fixture_mode:
            if source_bundle is None:
                raise ArchiveContractError("fixture_mode_requires_source_bundle")
            if not source_bundle.is_dir() or source_bundle.is_symlink():
                raise ArchiveContractError("source_bundle_not_regular_directory")
            fixture_time = parse_utc(args.collected_at, field="fixture_collected_at")
            if allow_network:
                raise ArchiveContractError("fixture_mode_network_forbidden")
        else:
            fixture_time = None
            if str(args.collected_at or ""):
                raise ArchiveContractError("caller_timestamp_forbidden_outside_fixture")
            if source_bundle is not None:
                raise ArchiveContractError("source_bundle_requires_fixture_mode")
            if not allow_network:
                raise ArchiveContractError("normal_mode_requires_allow_network")

        writer_lock = acquire_archive_writer_lock(
            output_root,
            float(contract["collection"]["writer_lock_timeout_seconds"]),
        )
        existing_entries = recover_verified_unindexed_snapshot(
            output_root, CANONICAL_CONTRACT_SEMANTIC_SHA256
        )
        captures, missing_audits, consumed = collect_sources(
            contract=contract,
            source_bundle=source_bundle,
            fixture_mode=fixture_mode,
            fixture_time=fixture_time,
            allow_network=allow_network,
        )
        if not captures:
            raise ArchiveContractError("no_source_captured")
        verify_consumed_inputs(consumed)
        verify_builder_identity(identity)
        audits, raw_objects, normalized_objects = materialize_sources(
            captures, missing_audits
        )
        completed_at = fixture_time if fixture_mode else utc_now()
        assert completed_at is not None
        capture_times = [
            parse_utc(item["captured_at_utc"], field="source_captured_at")
            for item in audits
            if item.get("captured_at_utc")
        ]
        if capture_times and completed_at < max(capture_times):
            completed_at = max(capture_times)
        if completed_at < launch:
            raise ArchiveContractError("collection_precedes_archive_launch")
        collected_at = utc_iso(completed_at)
        if any(value < launch for value in capture_times):
            raise ArchiveContractError("source_capture_precedes_archive_launch")

        source_truth_counts = dict(
            sorted(
                Counter(
                    str(item["truth_class"])
                    for item in audits
                    if item.get("truth_class")
                ).items()
            )
        )
        row_truth_counts: Counter[str] = Counter()
        for item in audits:
            truth = item.get("truth_class")
            if truth:
                row_truth_counts[str(truth)] += int(
                    item.get("normalized_row_count") or 0
                )
        missing_count = sum(
            item["status"] == "missing_or_unavailable" for item in audits
        )
        partial_count = sum(item["status"] == "partial" for item in audits)
        snapshot_identity = {
            "schema_version": SCHEMA_VERSION,
            "collected_at_utc": collected_at,
            "git_head": identity["git_head"],
            "builder_sha256": identity["builder_sha256"],
            "contract_semantic_sha256": CANONICAL_CONTRACT_SEMANTIC_SHA256,
            "fixture_mode": fixture_mode,
            "sources": audits,
        }
        identity_hash = semantic_sha256(snapshot_identity)
        timestamp_key = completed_at.strftime("%Y%m%dT%H%M%SZ")
        snapshot_id = f"{timestamp_key}-{identity_hash[:16]}"

        same_time = [
            entry
            for entry in existing_entries
            if entry["collected_at_utc"] == collected_at
        ]
        if same_time:
            if len(same_time) != 1 or same_time[0]["snapshot_id"] != snapshot_id:
                raise ArchiveContractError("same_collection_time_payload_conflict")
            existing_manifest = (
                output_root
                / "snapshots"
                / snapshot_id
                / "manifest.json"
            )
            manifest = json.loads(existing_manifest.read_text(encoding="utf-8"))
            result = {
                **manifest,
                "status": (
                    READY_PARTIAL_STATUS
                    if missing_count or partial_count
                    else READY_STATUS
                ),
                "archive_passed": True,
                "idempotent_reuse": True,
                "snapshot_manifest_sha256": same_time[0][
                    "snapshot_manifest_sha256"
                ],
                "archive_index_entry_sha256": same_time[0]["entry_sha256"],
                "archive_index_entry_count": len(existing_entries),
            }
            atomic_write_json(output_root / "last_attempt.json", result)
            return result
        if existing_entries:
            latest = parse_utc(
                existing_entries[-1]["collected_at_utc"],
                field="latest_collection_time",
            )
            if completed_at <= latest:
                raise ArchiveContractError("out_of_order_collection")

        snapshot_manifest = {
            "schema_version": SCHEMA_VERSION,
            "status": (
                READY_PARTIAL_STATUS
                if missing_count or partial_count
                else READY_STATUS
            ),
            "archive_passed": True,
            "snapshot_id": snapshot_id,
            "snapshot_identity_sha256": identity_hash,
            "collected_at_utc": collected_at,
            "git_head": identity["git_head"],
            "builder_sha256": identity["builder_sha256"],
            "contract_semantic_sha256": CANONICAL_CONTRACT_SEMANTIC_SHA256,
            "fixture_mode": fixture_mode,
            "source_expected_count": len(audits),
            "source_captured_count": len(captures),
            "source_missing_count": missing_count,
            "source_partial_count": partial_count,
            "source_truth_class_counts": source_truth_counts,
            "normalized_row_truth_class_counts": dict(
                sorted(row_truth_counts.items())
            ),
            "sources": audits,
            "historical_ab_allowed": False,
            "pit_verified_emitted": False,
            "downstream_handoff": dict(contract["downstream"]),
            **SAFETY,
        }
        snapshot_manifest_raw = pretty_json_bytes(snapshot_manifest)
        snapshot_manifest_sha = sha256_bytes(snapshot_manifest_raw)

        for digest, raw in raw_objects.items():
            write_content_object(
                output_root / "objects" / "raw" / digest, raw, digest
            )
        for digest, raw in normalized_objects.items():
            write_content_object(
                output_root
                / "objects"
                / "normalized"
                / f"{digest}.jsonl",
                raw,
                digest,
            )

        snapshots_root = output_root / "snapshots"
        snapshots_root.mkdir(parents=True, exist_ok=True)
        staging = snapshots_root / f".staging-{uuid.uuid4().hex}"
        final_snapshot = snapshots_root / snapshot_id
        if final_snapshot.exists():
            raise ArchiveContractError("unindexed_snapshot_id_already_exists")
        staging.mkdir()
        try:
            (staging / "manifest.json").write_bytes(snapshot_manifest_raw)
            if sha256_file(staging / "manifest.json") != snapshot_manifest_sha:
                raise ArchiveContractError("staged_snapshot_manifest_hash_mismatch")
            verify_consumed_inputs(consumed)
            verify_builder_identity(identity)
            os.replace(staging, final_snapshot)
        finally:
            if staging.exists():
                shutil.rmtree(staging)

        entry = {
            "schema_version": "run287-chameleon-forward-archive-index-v1",
            "snapshot_id": snapshot_id,
            "collected_at_utc": collected_at,
            "snapshot_manifest_sha256": snapshot_manifest_sha,
            "source_captured_count": len(captures),
            "source_missing_count": missing_count,
            "previous_entry_sha256": (
                str(existing_entries[-1]["entry_sha256"])
                if existing_entries
                else ""
            ),
        }
        entry["entry_sha256"] = index_hash(entry)
        all_entries = [*existing_entries, entry]
        write_index(output_root / "archive_index.jsonl", all_entries)
        verified_entries = load_archive_index(
            output_root, CANONICAL_CONTRACT_SEMANTIC_SHA256
        )
        if verified_entries != all_entries:
            raise ArchiveContractError("post_commit_archive_verification_mismatch")

        result = {
            **snapshot_manifest,
            "idempotent_reuse": False,
            "snapshot_manifest_sha256": snapshot_manifest_sha,
            "archive_index_entry_sha256": entry["entry_sha256"],
            "archive_index_entry_count": len(all_entries),
        }
        atomic_write_json(output_root / "last_attempt.json", result)
        return result
    except Exception as exc:
        blocked = {
            "schema_version": SCHEMA_VERSION,
            "status": BLOCKED_STATUS,
            "archive_passed": False,
            "blockers": [safe_blocker(exc)],
            "historical_ab_allowed": False,
            "pit_verified_emitted": False,
            **SAFETY,
        }
        if writer_lock is not None:
            try:
                validate_archive_root(output_root)
                atomic_write_json(output_root / "last_attempt.json", blocked)
            except Exception:
                pass
        return blocked
    finally:
        release_archive_writer_lock(writer_lock)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--archive-root", required=True)
    result.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    result.add_argument("--source-bundle", default="")
    result.add_argument("--fixture-mode", action="store_true")
    result.add_argument("--collected-at", default="")
    result.add_argument("--allow-network", action="store_true")
    return result


def main() -> int:
    payload = build(parser().parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False))
    return 0 if str(payload.get("status") or "").startswith("READY_") else 2


if __name__ == "__main__":
    raise SystemExit(main())
