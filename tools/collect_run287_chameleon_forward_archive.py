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
import importlib.metadata
import ipaddress
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
import uuid
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import (
    quote,
    unquote,
    unquote_to_bytes,
    urljoin,
    urlsplit,
    urlunsplit,
)

import requests


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = ROOT / "docs" / "run287_chameleon_forward_archive_contract.json"
CANONICAL_CONTRACT_SEMANTIC_SHA256 = (
    "b0f8a2af5d79f63d2a56079ca01392b9c1f2032de70a65cd8f03b9491475efcc"
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
NYSE_CALENDAR_ENGINE = {
    "package": "pandas_market_calendars",
    "version": "5.3.2",
    "calendar": "NYSE",
}

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

SNAPSHOT_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "status",
        "archive_passed",
        "snapshot_id",
        "snapshot_identity_sha256",
        "collected_at_utc",
        "git_head",
        "builder_sha256",
        "builder_git_blob_sha256",
        "contract_semantic_sha256",
        "calendar_engine",
        "fixture_mode",
        "source_expected_count",
        "source_captured_count",
        "source_missing_count",
        "source_partial_count",
        "source_truth_class_counts",
        "normalized_row_truth_class_counts",
        "sources",
        "historical_ab_allowed",
        "pit_verified_emitted",
        "downstream_handoff",
        *SAFETY,
    }
)
MISSING_SOURCE_AUDIT_FIELDS = frozenset(
    {
        "source_id",
        "provider",
        "source_kind",
        "status",
        "mode",
        "public_url",
        "resolved_url",
        "public_request_params",
        "reason",
        "truth_class",
        "captured_at_utc",
        "raw_sha256",
        "raw_object",
        "normalized_sha256",
        "normalized_object",
        "normalized_row_count",
        "excluded_non_session_row_count",
        "excluded_non_session_dates",
    }
)
PRESENT_SOURCE_AUDIT_FIELDS = MISSING_SOURCE_AUDIT_FIELDS | {
    "first_observation_date",
    "last_observation_date",
    "missing_value_count",
    "missing_tickers",
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


def require_git_commit_object(head: str) -> None:
    object_type = subprocess.run(
        ["git", "cat-file", "-t", head],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    if object_type.returncode != 0 or object_type.stdout.strip() != "commit":
        raise ArchiveContractError("builder_git_head_not_commit")


def git_blob_bytes(head: str, relative_path: str) -> bytes:
    require_git_commit_object(head)
    result = subprocess.run(
        ["git", "cat-file", "blob", f"{head}:{relative_path}"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise ArchiveContractError("builder_git_blob_unavailable")
    return bytes(result.stdout)


def builder_identity(*, require_head_match: bool = False) -> dict[str, str]:
    source_path = Path(__file__).resolve()
    try:
        relative_path = source_path.relative_to(ROOT).as_posix()
    except ValueError as exc:
        raise ArchiveContractError("builder_outside_repository") from exc
    head = git_head()
    runtime_bytes = source_path.read_bytes()
    head_bytes = git_blob_bytes(head, relative_path)
    if require_head_match and runtime_bytes != head_bytes:
        raise ArchiveContractError("builder_source_differs_from_git_head")
    return {
        "git_head": head,
        "builder_sha256": sha256_bytes(runtime_bytes),
        "builder_git_blob_sha256": sha256_bytes(head_bytes),
    }


def verify_builder_identity(
    expected: Mapping[str, str], *, require_head_match: bool = False
) -> None:
    if builder_identity(require_head_match=require_head_match) != dict(expected):
        raise ArchiveContractError("builder_or_git_head_changed_during_collection")


def validate_recorded_builder_identity(
    *,
    git_commit: str,
    builder_sha: str,
    builder_git_blob_sha: str,
    fixture_mode: Any,
    snapshot_id: str,
) -> None:
    if (
        re.fullmatch(r"[0-9a-f]{40}", git_commit) is None
        or HEX64.fullmatch(builder_sha) is None
        or HEX64.fullmatch(builder_git_blob_sha) is None
        or type(fixture_mode) is not bool
        or (not fixture_mode and builder_sha != builder_git_blob_sha)
    ):
        raise ArchiveContractError(
            f"orphan_snapshot_builder_identity_invalid:{snapshot_id}"
        )
    require_git_commit_object(git_commit)
    if fixture_mode:
        return
    try:
        builder_relative = Path(__file__).resolve().relative_to(ROOT).as_posix()
    except ValueError as exc:
        raise ArchiveContractError("builder_outside_repository") from exc
    if sha256_bytes(git_blob_bytes(git_commit, builder_relative)) != builder_git_blob_sha:
        raise ArchiveContractError(f"snapshot_builder_git_blob_mismatch:{snapshot_id}")


def parse_utc(value: Any, *, field: str) -> datetime:
    raw = str(value or "")
    if raw.strip() != raw or UTC_EXACT.fullmatch(raw) is None:
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


def active_fred_api_key(contract: Mapping[str, Any]) -> str:
    key_name = str(contract["collection"]["fred_api_key_environment_variable"])
    secret = os.environ.get(key_name, "")
    if secret and (
        secret.strip() != secret or any(character in secret for character in "\r\n")
    ):
        raise ArchiveContractError("fred_api_key_malformed")
    return secret


def committed_result_with_receipt(
    output_root: Path, result: Mapping[str, Any]
) -> dict[str, Any]:
    persisted = {**dict(result), "last_attempt_receipt_written": True}
    try:
        atomic_write_json(output_root / "last_attempt.json", persisted)
        return persisted
    except Exception as exc:
        return {
            **dict(result),
            "last_attempt_receipt_written": False,
            "last_attempt_receipt_error": safe_blocker(exc),
        }


def raw_contains_secret(raw: bytes, secret: str) -> bool:
    if not secret:
        return False
    secret_bytes = secret.encode("utf-8")
    candidate = raw
    for _ in range(8):
        if secret_bytes in candidate:
            return True
        decoded = unquote_to_bytes(candidate)
        decoded = re.sub(
            rb"\\u([0-9a-fA-F]{4})",
            lambda match: (
                chr(int(match.group(1), 16)).encode("utf-8")
                if not 0xD800 <= int(match.group(1), 16) <= 0xDFFF
                else match.group(0)
            ),
            decoded,
        )
        if decoded == candidate:
            return False
        candidate = decoded
    if secret_bytes in candidate:
        return True
    raise ArchiveContractError("percent_encoding_nesting_exceeded")


def decoded_value_contains_secret(value: Any, secret: str) -> bool:
    if not secret:
        return False
    variants = {secret, quote(secret, safe="")}
    if isinstance(value, str):
        candidate_value = value
        for _ in range(8):
            if any(candidate in candidate_value for candidate in variants if candidate):
                return True
            decoded = unquote(candidate_value)
            if decoded == candidate_value:
                return False
            candidate_value = decoded
        if any(candidate in candidate_value for candidate in variants if candidate):
            return True
        raise ArchiveContractError("percent_encoding_nesting_exceeded")
    if isinstance(value, Mapping):
        return any(
            decoded_value_contains_secret(key, secret)
            or decoded_value_contains_secret(item, secret)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(decoded_value_contains_secret(item, secret) for item in value)
    return False


def strict_json_payload(raw: bytes, *, source_id: str) -> Any:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for key, value in pairs:
            if key in output:
                raise ArchiveContractError(f"{source_id}_duplicate_json_key")
            output[key] = value
        return output

    def reject_constant(_value: str) -> Any:
        raise ArchiveContractError(f"{source_id}_nonstandard_json_constant")

    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
    except ArchiveContractError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArchiveContractError(f"{source_id}_json_unreadable") from exc

    def reject_nonfinite(value: Any) -> None:
        if isinstance(value, float) and not math.isfinite(value):
            raise ArchiveContractError(f"{source_id}_nonfinite_json_number")
        if isinstance(value, Mapping):
            for key, item in value.items():
                reject_nonfinite(key)
                reject_nonfinite(item)
        elif isinstance(value, list):
            for item in value:
                reject_nonfinite(item)

    reject_nonfinite(payload)
    return payload


def exact_json_integer(value: Any, *, source_id: str, field: str) -> int:
    if type(value) is not int:
        raise ArchiveContractError(f"{source_id}_{field}_invalid")
    return value


def valid_url_text(value: Any, *, field: str) -> str:
    """Reject URL text whose parser-visible form differs from its evidence."""
    raw = str(value or "")
    if (
        not raw
        or raw != raw.strip()
        or any(
            character.isspace()
            or unicodedata.category(character) in {"Cc", "Cf", "Cs"}
            for character in raw
        )
    ):
        raise ArchiveContractError(f"{field}_invalid_url")
    return raw


def public_https_url(value: Any, *, field: str) -> str:
    """Return a credential-free public HTTPS URL or fail closed."""
    raw = valid_url_text(value, field=field)
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise ArchiveContractError(f"{field}_invalid_url") from exc
    hostname = str(parsed.hostname or "").lower().rstrip(".")
    public_host = False
    if hostname:
        try:
            public_host = ipaddress.ip_address(hostname).is_global
        except ValueError:
            try:
                ascii_host = hostname.encode("idna").decode("ascii")
            except UnicodeError:
                ascii_host = ""
            labels = ascii_host.split(".")
            public_host = (
                len(labels) >= 2
                and all(
                    re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                    is not None
                    for label in labels
                )
                and not all(label.isdigit() for label in labels)
                and ascii_host != "localhost"
                and not ascii_host.endswith(".localhost")
            )
    if (
        parsed.scheme.lower() != "https"
        or not public_host
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.query
        or parsed.fragment
    ):
        raise ArchiveContractError(f"{field}_credential_bearing_or_nonpublic_url")
    return raw


def network_origin(value: Any, *, field: str) -> tuple[str, int]:
    """Validate a network hop without ever returning its query string."""
    raw = valid_url_text(value, field=field)
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
    ):
        raise ArchiveContractError(f"{field}_unapproved_origin")
    return parsed.hostname.lower().rstrip("."), port


def sanitized_network_url(value: Any, *, field: str) -> str:
    """Bind a final URL while stripping secret-bearing query material."""
    raw = valid_url_text(value, field=field)
    network_origin(raw, field=field)
    parsed = urlsplit(raw)
    hostname = str(parsed.hostname or "").lower().rstrip(".")
    netloc = hostname if parsed.port in (None, 443) else f"{hostname}:{parsed.port}"
    return urlunsplit(("https", netloc, parsed.path or "/", "", ""))


def load_contract(path: Path) -> dict[str, Any]:
    if path.resolve() != DEFAULT_CONTRACT.resolve():
        raise ArchiveContractError("noncanonical_contract_path")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ArchiveContractError("contract_unreadable") from exc
    payload = strict_json_payload(raw, source_id="canonical_contract")
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
    if (
        collection.get("network_redirect_policy")
        != "MANUAL_HTTPS_SAME_ORIGIN_PREVALIDATED_EVERY_HOP"
    ):
        raise ArchiveContractError("network_redirect_policy_changed")
    if int(collection.get("maximum_redirect_hops", -1)) != 5:
        raise ArchiveContractError("network_redirect_limit_changed")
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
        != "STRICT_UTF8_OPTIONAL_BOM_RFC_QUOTE_AND_UNICODE_CONTROL_VALIDATED_CSV"
    ):
        raise ArchiveContractError("source_text_encoding_policy_changed")
    if (
        collection.get("official_network_builder_policy")
        != "EXECUTED_BUILDER_BYTES_EQUAL_HEAD_TRACKED_BLOB"
    ):
        raise ArchiveContractError("official_network_builder_policy_changed")
    if collection.get("network_response_status_policy") != "HTTP_200_ONLY":
        raise ArchiveContractError("network_response_status_policy_changed")
    if (
        collection.get("fixture_timestamp_policy")
        != "CALLER_TIME_MUST_NOT_EXCEED_RUNTIME_UTC"
    ):
        raise ArchiveContractError("fixture_timestamp_policy_changed")
    archive = payload.get("archive") or {}
    if (
        archive.get("verified_unindexed_snapshot_policy")
        != "RECOVER_SINGLE_EXACT_ORPHAN_BEFORE_NEXT_CAPTURE"
    ):
        raise ArchiveContractError("orphan_recovery_policy_changed")
    if (
        archive.get("orphan_source_contract_policy")
        != "EXACT_CANONICAL_SOURCE_SET_PROVIDER_KIND_AND_PUBLIC_URL"
    ):
        raise ArchiveContractError("orphan_source_contract_policy_changed")
    if (
        archive.get("recovered_normalized_object_policy")
        != "PARSE_CANONICAL_JSONL_AND_REVALIDATE_ROW_CONTRACT"
    ):
        raise ArchiveContractError("recovered_normalized_object_policy_changed")
    if (
        archive.get("abandoned_staging_policy")
        != "DELETE_EXACT_LOCAL_UNMOUNTED_STAGING_DIRECTORIES_UNDER_WRITER_LOCK"
    ):
        raise ArchiveContractError("abandoned_staging_policy_changed")
    if (
        archive.get("idempotent_receipt_policy")
        != "PRESERVE_MANIFEST_AND_INDEX_ENTRY_HASHES"
    ):
        raise ArchiveContractError("idempotent_receipt_policy_changed")
    if (
        archive.get("fixture_orphan_builder_policy")
        != "ALLOW_RECORDED_RUNTIME_AND_HEAD_BLOB_HASH_DIFFERENCE"
    ):
        raise ArchiveContractError("fixture_orphan_builder_policy_changed")
    if (
        archive.get("committed_receipt_failure_policy")
        != "RETURN_VERIFIED_SUCCESS_WITH_RECEIPT_FAILURE_DETAIL"
    ):
        raise ArchiveContractError("committed_receipt_failure_policy_changed")
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
    if (
        fred.get("response_json_policy")
        != "RFC_JSON_NO_DUPLICATE_KEYS_NO_NONFINITE_NUMBERS_EXACT_INTEGER_METADATA"
    ):
        raise ArchiveContractError("fred_response_json_policy_changed")
    if (
        fred.get("response_secret_policy")
        != "REJECT_ACTIVE_API_KEY_IN_RAW_OR_RECURSIVELY_PERCENT_DECODED_JSON_RESPONSE"
    ):
        raise ArchiveContractError("fred_response_secret_policy_changed")
    cboe = payload.get("cboe") or {}
    if (
        cboe.get("index_close_current_date_policy")
        != "REQUIRE_COMPLETED_NYSE_SESSION"
    ):
        raise ArchiveContractError("cboe_index_close_session_policy_changed")
    if (
        cboe.get("index_history_row_date_policy")
        != "NORMALIZE_ONLY_NYSE_SESSIONS_AND_COUNT_EXCLUDED_ROWS"
    ):
        raise ArchiveContractError("cboe_index_row_session_policy_changed")
    if int(cboe.get("daily_options_max_completed_nyse_session_lag", -1)) != 1:
        raise ArchiveContractError("daily_options_freshness_policy_changed")
    if int(cboe.get("index_history_max_completed_nyse_session_lag", -1)) != 1:
        raise ArchiveContractError("index_history_freshness_policy_changed")
    cross_asset = payload.get("cross_asset") or {}
    if (
        cross_asset.get("provenance_url_policy")
        != "PUBLIC_GLOBAL_HOST_HTTPS_WITHOUT_USERINFO_QUERY_PARAMS_FRAGMENT_WHITESPACE_OR_CONTROLS"
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
    if root.exists() and (
        root.is_symlink() or bool(getattr(root, "is_junction", lambda: False)())
    ):
        raise ArchiveContractError("archive_root_link_forbidden")
    root.mkdir(parents=True, exist_ok=True)
    for relative in (
        Path("objects"),
        Path("objects/raw"),
        Path("objects/normalized"),
        Path("snapshots"),
    ):
        child = root / relative
        if child.exists() and (
            child.is_symlink()
            or bool(getattr(child, "is_junction", lambda: False)())
        ):
            label = str(relative).replace("\\", "_").replace("/", "_")
            raise ArchiveContractError(f"archive_{label}_link_forbidden")


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


def linux_mount_points() -> set[Path]:
    """Read Linux mount points, including same-device bind mounts."""
    mountinfo = Path("/proc/self/mountinfo")
    if os.name == "nt" or not mountinfo.is_file():
        return set()
    try:
        lines = mountinfo.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ArchiveContractError("mount_table_unreadable") from exc
    mounts: set[Path] = set()
    for line in lines:
        fields = line.split(" - ", 1)[0].split()
        if len(fields) < 5:
            raise ArchiveContractError("mount_table_malformed")
        encoded = fields[4]
        decoded = re.sub(
            r"\\([0-7]{3})",
            lambda match: chr(int(match.group(1), 8)),
            encoded,
        )
        mounts.add(Path(decoded).absolute())
    return mounts


def path_contains_mount(path: Path, *, known_mounts: set[Path]) -> bool:
    """Return true when path itself or any lexical descendant is mounted."""
    absolute = path.absolute()
    try:
        if os.path.ismount(absolute):
            return True
    except OSError as exc:
        raise ArchiveContractError("mount_point_check_failed") from exc
    for mounted in known_mounts:
        try:
            mounted.relative_to(absolute)
            return True
        except ValueError:
            continue
    return False


def recover_abandoned_staging(root: Path) -> list[str]:
    """Discard only exact, local pre-rename staging under the writer lock."""
    snapshots_root = root / "snapshots"
    if not snapshots_root.exists():
        return []
    if snapshots_root.is_symlink() or not snapshots_root.is_dir():
        raise ArchiveContractError("archive_snapshots_root_invalid")
    resolved_root = snapshots_root.resolve()
    known_mounts = linux_mount_points()
    recovered: list[str] = []
    for candidate in sorted(snapshots_root.iterdir(), key=lambda path: path.name):
        if not candidate.name.startswith(".staging-"):
            continue
        is_junction = bool(
            getattr(candidate, "is_junction", lambda: False)()
        )
        if (
            re.fullmatch(r"\.staging-[0-9a-f]{32}", candidate.name) is None
            or candidate.is_symlink()
            or is_junction
            or not candidate.is_dir()
            or candidate.parent.resolve() != resolved_root
            or candidate.resolve().parent != resolved_root
            or path_contains_mount(candidate, known_mounts=known_mounts)
        ):
            raise ArchiveContractError(
                f"unsafe_abandoned_snapshot_staging:{candidate.name}"
            )
        for current, directories, files in os.walk(
            candidate, topdown=True, followlinks=False
        ):
            current_path = Path(current)
            for name in [*directories, *files]:
                descendant = current_path / name
                descendant_is_junction = bool(
                    getattr(descendant, "is_junction", lambda: False)()
                )
                if (
                    descendant.is_symlink()
                    or descendant_is_junction
                    or path_contains_mount(descendant, known_mounts=known_mounts)
                ):
                    raise ArchiveContractError(
                        f"linked_abandoned_snapshot_staging:{candidate.name}"
                    )
        shutil.rmtree(candidate)
        if candidate.exists():
            raise ArchiveContractError(
                f"abandoned_snapshot_staging_remove_failed:{candidate.name}"
            )
        recovered.append(candidate.name)
    return recovered


def validate_object_path(
    root: Path,
    relative: str,
    digest: str,
    *,
    role: str,
) -> Path:
    if HEX64.fullmatch(digest) is None:
        raise ArchiveContractError("invalid_object_digest")
    expected_by_role = {
        "raw": f"objects/raw/{digest}",
        "normalized": f"objects/normalized/{digest}.jsonl",
    }
    if role not in expected_by_role:
        raise ArchiveContractError("object_role_invalid")
    normalized = str(Path(relative)).replace("\\", "/")
    if normalized != expected_by_role[role]:
        raise ArchiveContractError("object_path_not_content_addressed")
    path = root / Path(normalized)
    if path.is_symlink() or not path.is_file() or sha256_file(path) != digest:
        raise ArchiveContractError(f"object_hash_mismatch:{normalized}")
    return path


def validate_normalized_object_rows(
    root: Path,
    source: Mapping[str, Any],
    *,
    snapshot_id: str,
    contract: Mapping[str, Any],
) -> list[dict[str, Any]]:
    source_id = str(source.get("source_id") or "")
    path = validate_object_path(
        root,
        str(source.get("normalized_object") or ""),
        str(source.get("normalized_sha256") or ""),
        role="normalized",
    )
    raw = path.read_bytes()
    if not raw or not raw.endswith(b"\n"):
        raise ArchiveContractError(
            f"snapshot_normalized_jsonl_invalid:{snapshot_id}:{source_id}"
        )
    lines = raw.splitlines()
    if any(not line for line in lines):
        raise ArchiveContractError(
            f"snapshot_normalized_jsonl_invalid:{snapshot_id}:{source_id}"
        )
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, 1):
        payload = strict_json_payload(
            line,
            source_id=f"snapshot_{source_id}_normalized_{line_number}",
        )
        if not isinstance(payload, dict):
            raise ArchiveContractError(
                f"snapshot_normalized_row_not_object:{snapshot_id}:{source_id}"
            )
        rows.append(payload)
    canonical = b"".join(canonical_json_bytes(row) + b"\n" for row in rows)
    if canonical != raw:
        raise ArchiveContractError(
            f"snapshot_normalized_jsonl_noncanonical:{snapshot_id}:{source_id}"
        )
    row_count = source.get("normalized_row_count")
    if type(row_count) is not int or row_count <= 0 or row_count != len(rows):
        raise ArchiveContractError(
            f"snapshot_normalized_row_count_mismatch:{snapshot_id}:{source_id}"
        )
    captured_at_text = str(source.get("captured_at_utc") or "")
    captured_at = parse_utc(captured_at_text, field="snapshot_source_captured_at")
    raw_sha = str(source.get("raw_sha256") or "")
    truth = str(source.get("truth_class") or "")
    expected = {
        "schema_version": "run287-chameleon-forward-observation-v1",
        "source_id": source_id,
        "provider": source.get("provider"),
        "source_kind": source.get("source_kind"),
        "available_from": captured_at_text,
        "collected_at_utc": captured_at_text,
        "raw_sha256": raw_sha,
        "truth_class": truth,
        "historical_ab_allowed": False,
    }
    observation_dates: list[str] = []
    seen_rows: set[str] = set()
    excluded_dates = set(source.get("excluded_non_session_dates") or [])
    for row in rows:
        if any(row.get(key) != value for key, value in expected.items()):
            raise ArchiveContractError(
                f"snapshot_normalized_row_contract_mismatch:{snapshot_id}:{source_id}"
            )
        observation = strict_iso_date(
            row.get("source_observation_date"),
            field="snapshot_normalized_observation_date",
        )
        if observation > captured_at.date() or observation.isoformat() in excluded_dates:
            raise ArchiveContractError(
                f"snapshot_normalized_observation_invalid:{snapshot_id}:{source_id}"
            )
        observation_dates.append(observation.isoformat())
        row_identity = semantic_sha256(row)
        if row_identity in seen_rows:
            raise ArchiveContractError(
                f"snapshot_normalized_duplicate_row:{snapshot_id}:{source_id}"
            )
        seen_rows.add(row_identity)
    if (
        source.get("first_observation_date") != min(observation_dates)
        or source.get("last_observation_date") != max(observation_dates)
    ):
        raise ArchiveContractError(
            f"snapshot_normalized_observation_bounds_mismatch:{snapshot_id}:{source_id}"
        )
    validate_normalized_source_specific_rows(
        rows,
        source=source,
        contract=contract,
        snapshot_id=snapshot_id,
        captured_at=captured_at,
    )
    return rows


def validate_normalized_source_specific_rows(
    rows: list[dict[str, Any]],
    *,
    source: Mapping[str, Any],
    contract: Mapping[str, Any],
    snapshot_id: str,
    captured_at: datetime,
) -> None:
    """Replay each source normalizer's canonical row contract on recovery."""
    source_id = str(source.get("source_id") or "")
    common_fields = {
        "schema_version",
        "source_id",
        "provider",
        "source_kind",
        "source_observation_date",
        "value",
        "available_from",
        "collected_at_utc",
        "raw_sha256",
        "truth_class",
        "historical_ab_allowed",
    }

    def require_fields(row: Mapping[str, Any], specific: set[str]) -> None:
        if set(row) != common_fields | specific:
            raise ArchiveContractError(
                f"snapshot_normalized_source_schema_mismatch:{snapshot_id}:{source_id}"
            )

    def number(value: Any, *, field: str, positive: bool = False) -> float:
        if type(value) not in {int, float}:
            raise ArchiveContractError(
                f"snapshot_normalized_{field}_type_invalid:{snapshot_id}:{source_id}"
            )
        parsed = float(value)
        if not math.isfinite(parsed) or (positive and parsed <= 0):
            raise ArchiveContractError(
                f"snapshot_normalized_{field}_invalid:{snapshot_id}:{source_id}"
            )
        return parsed

    if source_id.startswith("fred."):
        name = source_id.removeprefix("fred.")
        expected_series = str(
            (contract.get("fred") or {}).get("series", {}).get(name) or ""
        )
        request = source.get("public_request_params")
        if not expected_series or not isinstance(request, dict):
            raise ArchiveContractError(
                f"snapshot_normalized_fred_contract_invalid:{snapshot_id}:{source_id}"
            )
        expected_request = {
            "series_id": expected_series,
            "file_type": "json",
            "realtime_start": request.get("realtime_start"),
            "realtime_end": request.get("realtime_end"),
            "observation_start": request.get("observation_start"),
            "observation_end": request.get("observation_end"),
            "sort_order": "asc",
            "limit": 100000,
        }
        if (
            request != expected_request
            or request["realtime_start"] != request["realtime_end"]
        ):
            raise ArchiveContractError(
                f"snapshot_normalized_fred_request_mismatch:{snapshot_id}:{source_id}"
            )
        observation_start = strict_iso_date(
            request["observation_start"], field="snapshot_fred_observation_start"
        )
        observation_end = strict_iso_date(
            request["observation_end"], field="snapshot_fred_observation_end"
        )
        vintage = strict_iso_date(
            request["realtime_start"], field="snapshot_fred_vintage"
        )
        history_years = int(contract["collection"]["fred_observation_history_years"])
        if (
            observation_start != subtract_years(vintage, history_years)
            or observation_end != vintage
            or vintage != captured_at.date()
        ):
            raise ArchiveContractError(
                f"snapshot_normalized_fred_request_window_invalid:{snapshot_id}:{source_id}"
            )
        vintage_text = vintage.isoformat()
        seen_dates: set[date] = set()
        previous_observed: date | None = None
        for row in rows:
            require_fields(row, {"series_id", "vintage_start", "vintage_end"})
            observed = strict_iso_date(
                row["source_observation_date"], field="snapshot_fred_observation"
            )
            if (
                row.get("series_id") != expected_series
                or row.get("vintage_start") != vintage_text
                or row.get("vintage_end") != vintage_text
                or not observation_start <= observed <= observation_end
                or observed in seen_dates
                or (previous_observed is not None and observed <= previous_observed)
            ):
                raise ArchiveContractError(
                    f"snapshot_normalized_fred_row_mismatch:{snapshot_id}:{source_id}"
                )
            seen_dates.add(observed)
            previous_observed = observed
            number(row.get("value"), field="fred_value")
        return

    if source_id in {"cboe.vix", "cboe.vix3m", "cboe.vvix"}:
        instrument = source_id.removeprefix("cboe.").upper()
        observed_dates: list[date] = []
        for row in rows:
            require_fields(row, {"instrument", "value_field"})
            if row.get("instrument") != instrument or row.get("value_field") != "close":
                raise ArchiveContractError(
                    f"snapshot_normalized_cboe_index_row_mismatch:{snapshot_id}:{source_id}"
                )
            number(row.get("value"), field="cboe_index_value", positive=True)
            observed_dates.append(
                strict_iso_date(
                    row["source_observation_date"],
                    field="snapshot_cboe_index_observation",
                )
            )
        sessions = nyse_session_dates(min(observed_dates), max(observed_dates))
        if any(observed not in sessions for observed in observed_dates):
            raise ArchiveContractError(
                f"snapshot_normalized_cboe_index_session_mismatch:{snapshot_id}:{source_id}"
            )
        completed = completed_nyse_sessions(captured_at)
        latest = observed_dates[-1]
        lag = sum(session > latest for session in completed)
        if (
            latest not in completed
            or lag
            > int(contract["cboe"]["index_history_max_completed_nyse_session_lag"])
        ):
            raise ArchiveContractError(
                f"snapshot_normalized_cboe_index_stale:{snapshot_id}:{source_id}"
            )
        return

    if source_id == "cboe.daily_put_call":
        instruments: set[str] = set()
        dates: set[date] = set()
        for row in rows:
            require_fields(
                row,
                {
                    "instrument",
                    "value_field",
                    "call_volume",
                    "put_volume",
                    "total_volume",
                },
            )
            instrument = str(row.get("instrument") or "")
            if instrument not in {"EQUITY", "INDEX"} or instrument in instruments:
                raise ArchiveContractError(
                    f"snapshot_normalized_cboe_options_instrument_mismatch:{snapshot_id}:{source_id}"
                )
            instruments.add(instrument)
            if row.get("value_field") != "put_call_ratio":
                raise ArchiveContractError(
                    f"snapshot_normalized_cboe_options_row_mismatch:{snapshot_id}:{source_id}"
                )
            call = row.get("call_volume")
            put = row.get("put_volume")
            total = row.get("total_volume")
            if (
                type(call) is not int
                or type(put) is not int
                or type(total) is not int
                or call <= 0
                or put < 0
                or total != call + put
            ):
                raise ArchiveContractError(
                    f"snapshot_normalized_cboe_options_volume_mismatch:{snapshot_id}:{source_id}"
                )
            ratio = number(row.get("value"), field="cboe_options_value")
            if abs(ratio - put / call) > 0.02:
                raise ArchiveContractError(
                    f"snapshot_normalized_cboe_options_ratio_mismatch:{snapshot_id}:{source_id}"
                )
            dates.add(
                strict_iso_date(
                    row["source_observation_date"],
                    field="snapshot_cboe_options_observation",
                )
            )
        if instruments != {"EQUITY", "INDEX"} or len(dates) != 1:
            raise ArchiveContractError(
                f"snapshot_normalized_cboe_options_topology_mismatch:{snapshot_id}:{source_id}"
            )
        completed = completed_nyse_sessions(captured_at)
        latest = next(iter(dates))
        lag = sum(session > latest for session in completed)
        if (
            latest not in completed
            or lag
            > int(contract["cboe"]["daily_options_max_completed_nyse_session_lag"])
        ):
            raise ArchiveContractError(
                f"snapshot_normalized_cboe_options_session_mismatch:{snapshot_id}:{source_id}"
            )
        return

    if source_id == "cross_asset.daily_close":
        cross = contract.get("cross_asset") or {}
        required = {str(item).upper() for item in cross.get("required_tickers", [])}
        allowed_basis = {str(item) for item in cross.get("allowed_price_basis", [])}
        observed_tickers: set[str] = set()
        seen: set[tuple[str, str]] = set()
        observed_dates: list[date] = []
        for row in rows:
            require_fields(
                row,
                {
                    "instrument",
                    "value_field",
                    "price_basis",
                    "upstream_provider",
                    "upstream_source_url",
                },
            )
            ticker = str(row.get("instrument") or "")
            observed_date = strict_iso_date(
                row.get("source_observation_date"),
                field="snapshot_cross_asset_observation",
            )
            observed = observed_date.isoformat()
            if ticker not in required or (ticker, observed) in seen:
                raise ArchiveContractError(
                    f"snapshot_normalized_cross_asset_identity_mismatch:{snapshot_id}:{source_id}"
                )
            seen.add((ticker, observed))
            observed_tickers.add(ticker)
            observed_dates.append(observed_date)
            if (
                row.get("value_field") != "close"
                or row.get("price_basis") not in allowed_basis
            ):
                raise ArchiveContractError(
                    f"snapshot_normalized_cross_asset_row_mismatch:{snapshot_id}:{source_id}"
                )
            number(row.get("value"), field="cross_asset_value", positive=True)
            provider = str(row.get("upstream_provider") or "")
            if (
                not provider
                or provider != provider.strip()
                or any(
                    unicodedata.category(character) in {"Cc", "Cf", "Cs"}
                    for character in provider
                )
            ):
                raise ArchiveContractError(
                    f"snapshot_normalized_cross_asset_provider_invalid:{snapshot_id}:{source_id}"
                )
            public_https_url(
                row.get("upstream_source_url"),
                field="snapshot_cross_asset_source_url",
            )
        validate_cross_asset_close_sessions(
            observed_dates,
            captured_at=captured_at,
            source_id=f"snapshot_{source_id}",
        )
        missing = sorted(required - observed_tickers)
        if source.get("missing_tickers") != missing or source.get("status") != (
            "partial" if missing else "ready"
        ):
            raise ArchiveContractError(
                f"snapshot_normalized_cross_asset_coverage_mismatch:{snapshot_id}:{source_id}"
            )
        return

    raise ArchiveContractError(
        f"snapshot_normalized_unknown_source:{snapshot_id}:{source_id}"
    )


def validate_downstream_handoff(
    manifest: Mapping[str, Any],
    contract: Mapping[str, Any],
    *,
    snapshot_id: str,
) -> None:
    expected = contract.get("downstream")
    if not isinstance(expected, dict) or manifest.get("downstream_handoff") != expected:
        raise ArchiveContractError(f"snapshot_downstream_handoff_drift:{snapshot_id}")


def validate_recovered_raw_normalization(
    root: Path,
    source: Mapping[str, Any],
    normalized_rows: list[dict[str, Any]],
    *,
    contract: Mapping[str, Any],
    snapshot_id: str,
) -> None:
    """Re-normalize an orphan's raw evidence and require an exact row match."""
    source_id = str(source.get("source_id") or "")
    raw_path = validate_object_path(
        root,
        str(source.get("raw_object") or ""),
        str(source.get("raw_sha256") or ""),
        role="raw",
    )
    maximum_bytes = int(contract["collection"]["maximum_raw_bytes_per_source"])
    if raw_path.stat().st_size > maximum_bytes:
        raise ArchiveContractError(
            f"recovered_raw_object_too_large:{snapshot_id}:{source_id}"
        )
    raw = raw_path.read_bytes()
    if raw_contains_secret(raw, active_fred_api_key(contract)):
        raise ArchiveContractError(
            f"recovered_raw_contains_api_key:{snapshot_id}:{source_id}"
        )
    capture_time = parse_utc(
        source.get("captured_at_utc"), field="recovered_source_captured_at"
    )
    envelope = {
        "schema_version",
        "source_id",
        "provider",
        "source_kind",
        "available_from",
        "collected_at_utc",
        "raw_sha256",
        "truth_class",
        "historical_ab_allowed",
    }
    archived_rows = [
        {key: value for key, value in row.items() if key not in envelope}
        for row in normalized_rows
    ]

    if source_id.startswith("fred."):
        name = source_id.removeprefix("fred.")
        series_id = str(contract["fred"]["series"][name])
        request = source.get("public_request_params")
        if not isinstance(request, dict):
            raise ArchiveContractError(
                f"recovered_raw_request_invalid:{snapshot_id}:{source_id}"
            )
        active_secret = active_fred_api_key(contract)
        reparsed, missing_count = normalize_fred(
            raw,
            source_id=source_id,
            series_id=series_id,
            requested_vintage_date=str(request.get("realtime_start") or ""),
            requested_observation_start=str(request.get("observation_start") or ""),
            requested_observation_end=str(request.get("observation_end") or ""),
            missing_token=str(contract["fred"]["missing_value_token"]),
            active_secret=active_secret,
        )
        if missing_count != source.get("missing_value_count"):
            raise ArchiveContractError(
                f"recovered_raw_missing_count_mismatch:{snapshot_id}:{source_id}"
            )
    elif source_id in {"cboe.vix", "cboe.vix3m", "cboe.vvix"}:
        reparsed, excluded_dates = normalize_cboe_index(
            raw,
            source_id=source_id,
            symbol=source_id.removeprefix("cboe."),
            captured_at=capture_time,
            maximum_completed_session_lag=int(
                contract["cboe"]["index_history_max_completed_nyse_session_lag"]
            ),
        )
        if excluded_dates != source.get("excluded_non_session_dates"):
            raise ArchiveContractError(
                f"recovered_raw_excluded_dates_mismatch:{snapshot_id}:{source_id}"
            )
    elif source_id == "cboe.daily_put_call":
        reparsed = normalize_cboe_daily_options_page(
            raw,
            source_id=source_id,
            captured_at=capture_time,
            maximum_completed_session_lag=int(
                contract["cboe"]["daily_options_max_completed_nyse_session_lag"]
            ),
        )
    elif source_id == "cross_asset.daily_close":
        reparsed, missing_tickers = normalize_cross_asset(
            raw,
            source_id=source_id,
            required_tickers=contract["cross_asset"]["required_tickers"],
            allowed_price_basis=contract["cross_asset"]["allowed_price_basis"],
            captured_at=capture_time,
        )
        if missing_tickers != source.get("missing_tickers"):
            raise ArchiveContractError(
                f"recovered_raw_missing_tickers_mismatch:{snapshot_id}:{source_id}"
            )
    else:
        raise ArchiveContractError(
            f"recovered_raw_unknown_source:{snapshot_id}:{source_id}"
        )
    if reparsed != archived_rows:
        raise ArchiveContractError(
            f"recovered_raw_normalization_mismatch:{snapshot_id}:{source_id}"
        )


def index_hash(payload: Mapping[str, Any]) -> str:
    material = dict(payload)
    material.pop("entry_sha256", None)
    return semantic_sha256(material)


def load_archive_index(
    root: Path,
    contract: Mapping[str, Any],
    *,
    allow_unindexed_snapshots: bool = False,
) -> list[dict[str, Any]]:
    index_path = root / "archive_index.jsonl"
    snapshots_root = root / "snapshots"
    snapshot_dirs: list[Path] = []
    if snapshots_root.exists():
        linked_entries = sorted(
            path.name
            for path in snapshots_root.iterdir()
            if path.is_symlink()
            or bool(getattr(path, "is_junction", lambda: False)())
        )
        if linked_entries:
            raise ArchiveContractError(
                "snapshot_link_forbidden:" + ",".join(linked_entries)
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
        entry = strict_json_payload(
            line.encode("utf-8"), source_id=f"archive_index_{line_number}"
        )
        if not isinstance(entry, dict):
            raise ArchiveContractError(f"archive_index_row_not_object:{line_number}")
        expected_index_fields = {
            "schema_version",
            "snapshot_id",
            "collected_at_utc",
            "snapshot_manifest_sha256",
            "source_captured_count",
            "source_missing_count",
            "previous_entry_sha256",
            "entry_sha256",
        }
        if (
            set(entry) != expected_index_fields
            or entry.get("schema_version")
            != "run287-chameleon-forward-archive-index-v1"
        ):
            raise ArchiveContractError(f"archive_index_schema_mismatch:{line_number}")
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
        manifest, verified_manifest_sha = verify_recoverable_snapshot(
            root,
            snapshot_id,
            contract,
            replay_raw=True,
        )
        if verified_manifest_sha != manifest_sha:
            raise ArchiveContractError(
                f"snapshot_manifest_hash_mismatch:{snapshot_id}"
            )
        if manifest.get("collected_at_utc") != collected_at:
            raise ArchiveContractError(
                f"snapshot_manifest_collection_time_mismatch:{snapshot_id}"
            )
        for field in ("source_captured_count", "source_missing_count"):
            value = entry.get(field)
            if type(value) is not int or value < 0 or value != manifest.get(field):
                raise ArchiveContractError(
                    f"archive_index_manifest_counter_mismatch:{snapshot_id}:{field}"
                )
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


def canonical_source_definitions(
    contract: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    definitions: dict[str, dict[str, Any]] = {}
    fred_url = public_https_url(contract["fred"]["endpoint"], field="fred_endpoint")
    for name in contract["fred"]["series"]:
        definitions[f"fred.{name}"] = {
            "providers": {"FRED_ALFRED_API"},
            "source_kind": "FRED_SERIES_OBSERVATIONS",
            "public_url": fred_url,
        }
    for name, spec in contract["cboe"]["sources"].items():
        definitions[f"cboe.{name}"] = {
            "providers": {"CBOE"},
            "source_kind": str(spec["kind"]),
            "public_url": public_https_url(
                spec["url"], field=f"cboe.{name}_public_url"
            ),
        }
    definitions["cross_asset.daily_close"] = {
        "providers": {"SOURCE_BUNDLE_DECLARED_PROVIDER", "UNCONFIGURED"},
        "source_kind": "CROSS_ASSET_DAILY_CLOSE",
        "public_url": "",
    }
    return definitions


def validate_orphan_source_contract(
    sources: Any,
    *,
    contract: Mapping[str, Any],
    snapshot_id: str,
) -> set[str]:
    if not isinstance(sources, list) or not sources:
        raise ArchiveContractError(f"orphan_snapshot_sources_invalid:{snapshot_id}")
    definitions = canonical_source_definitions(contract)
    observed: set[str] = set()
    for source in sources:
        if not isinstance(source, dict):
            raise ArchiveContractError(f"orphan_snapshot_source_not_object:{snapshot_id}")
        source_id = str(source.get("source_id") or "")
        if not source_id or source_id in observed:
            raise ArchiveContractError(f"orphan_snapshot_source_id_invalid:{snapshot_id}")
        observed.add(source_id)
        definition = definitions.get(source_id)
        if definition is None:
            raise ArchiveContractError(f"orphan_snapshot_unknown_source:{source_id}")
        if (
            str(source.get("provider") or "") not in definition["providers"]
            or str(source.get("source_kind") or "") != definition["source_kind"]
            or str(source.get("public_url") or "") != definition["public_url"]
        ):
            raise ArchiveContractError(
                f"orphan_snapshot_source_definition_mismatch:{source_id}"
            )
        if source_id == "cross_asset.daily_close":
            expected_provider = (
                "UNCONFIGURED"
                if source.get("status") == "missing_or_unavailable"
                else "SOURCE_BUNDLE_DECLARED_PROVIDER"
            )
            if source.get("provider") != expected_provider:
                raise ArchiveContractError(
                    f"orphan_snapshot_source_definition_mismatch:{source_id}"
                )
    expected = set(definitions)
    if observed != expected:
        raise ArchiveContractError(
            f"orphan_snapshot_source_set_mismatch:{snapshot_id}"
        )
    return observed


def validate_fixture_source_mode_alignment(
    sources: Any,
    fixture_mode: Any,
    *,
    snapshot_id: str,
) -> None:
    if type(fixture_mode) is not bool or not isinstance(sources, list):
        raise ArchiveContractError(
            f"snapshot_fixture_source_mode_mismatch:{snapshot_id}"
        )
    expected_present_mode = "fixture" if fixture_mode else "official_network"
    for source in sources:
        if not isinstance(source, dict):
            raise ArchiveContractError(
                f"snapshot_fixture_source_mode_mismatch:{snapshot_id}"
            )
        status = source.get("status")
        mode = source.get("mode")
        if status in {"ready", "partial"} and mode != expected_present_mode:
            raise ArchiveContractError(
                f"snapshot_fixture_source_mode_mismatch:{snapshot_id}"
            )
        if status == "missing_or_unavailable" and mode != "missing":
            raise ArchiveContractError(
                f"snapshot_fixture_source_mode_mismatch:{snapshot_id}"
            )


def validate_source_audit_schema(
    source: Mapping[str, Any],
    *,
    fixture_mode: bool,
    snapshot_id: str,
) -> None:
    source_id = str(source.get("source_id") or "")
    status = source.get("status")
    expected_fields = (
        MISSING_SOURCE_AUDIT_FIELDS
        if status == "missing_or_unavailable"
        else PRESENT_SOURCE_AUDIT_FIELDS
    )
    if set(source) != expected_fields:
        raise ArchiveContractError(
            f"orphan_snapshot_source_schema_mismatch:{snapshot_id}:{source_id}"
        )
    if status == "missing_or_unavailable":
        reason = source.get("reason")
        network_failure = (
            isinstance(reason, str)
            and re.fullmatch(
                r"network_unavailable:[A-Za-z][A-Za-z0-9_]{0,127}", reason
            )
            is not None
        )
        if fixture_mode:
            reason_is_compatible = reason == "fixture_file_missing"
        elif source_id.startswith("fred."):
            reason_is_compatible = reason in {
                "fred_api_key_unavailable",
                "network_disabled",
            } or network_failure
        elif source_id.startswith("cboe."):
            reason_is_compatible = reason == "network_disabled" or network_failure
        elif source_id == "cross_asset.daily_close":
            reason_is_compatible = reason == "trusted_network_provider_not_configured"
        else:
            reason_is_compatible = False
        if (
            source.get("mode") != "missing"
            or source.get("resolved_url") is not None
            or source.get("public_request_params") != {}
            or not reason_is_compatible
            or source.get("truth_class") is not None
            or source.get("captured_at_utc") is not None
            or source.get("raw_sha256") is not None
            or source.get("raw_object") is not None
            or source.get("normalized_sha256") is not None
            or source.get("normalized_object") is not None
            or source.get("normalized_row_count") != 0
            or source.get("excluded_non_session_row_count") != 0
            or source.get("excluded_non_session_dates") != []
        ):
            raise ArchiveContractError(
                f"orphan_snapshot_missing_source_invalid:{snapshot_id}:{source_id}"
            )
        return
    request = source.get("public_request_params")
    missing_count = source.get("missing_value_count")
    missing_tickers = source.get("missing_tickers")
    if (
        source.get("reason") != ""
        or not isinstance(request, dict)
        or type(missing_count) is not int
        or missing_count < 0
        or not isinstance(missing_tickers, list)
        or any(not isinstance(item, str) for item in missing_tickers)
        or missing_tickers != sorted(set(missing_tickers))
    ):
        raise ArchiveContractError(
            f"orphan_snapshot_source_audit_metadata_invalid:{snapshot_id}:{source_id}"
        )
    if source_id.startswith("fred."):
        canonical = (
            missing_tickers == []
            and source.get("excluded_non_session_row_count") == 0
            and source.get("excluded_non_session_dates") == []
        )
    elif source_id.startswith("cboe."):
        canonical = request == {} and missing_count == 0 and missing_tickers == []
        if source_id == "cboe.daily_put_call":
            canonical = (
                canonical
                and source.get("excluded_non_session_row_count") == 0
                and source.get("excluded_non_session_dates") == []
            )
    elif source_id == "cross_asset.daily_close":
        canonical = (
            request == {}
            and missing_count == 0
            and source.get("excluded_non_session_row_count") == 0
            and source.get("excluded_non_session_dates") == []
        )
    else:
        canonical = False
    if not canonical:
        raise ArchiveContractError(
            f"orphan_snapshot_source_audit_metadata_invalid:{snapshot_id}:{source_id}"
        )


def verify_recoverable_snapshot(
    root: Path,
    snapshot_id: str,
    contract: Mapping[str, Any],
    *,
    replay_raw: bool = True,
) -> tuple[dict[str, Any], str]:
    contract_sha256 = semantic_sha256(contract)
    snapshot_dir = root / "snapshots" / snapshot_id
    manifest_path = snapshot_dir / "manifest.json"
    if (
        snapshot_dir.is_symlink()
        or bool(getattr(snapshot_dir, "is_junction", lambda: False)())
        or manifest_path.is_symlink()
        or not manifest_path.is_file()
    ):
        raise ArchiveContractError(f"orphan_snapshot_manifest_missing:{snapshot_id}")
    raw = manifest_path.read_bytes()
    manifest = strict_json_payload(
        raw, source_id=f"snapshot_manifest_{snapshot_id}"
    )
    if not isinstance(manifest, dict):
        raise ArchiveContractError(f"orphan_snapshot_manifest_not_object:{snapshot_id}")
    active_secret = active_fred_api_key(contract)
    if raw_contains_secret(raw, active_secret) or decoded_value_contains_secret(
        manifest, active_secret
    ):
        raise ArchiveContractError(
            f"snapshot_manifest_contains_api_key:{snapshot_id}"
        )
    if set(manifest) != SNAPSHOT_MANIFEST_FIELDS:
        raise ArchiveContractError(
            f"orphan_snapshot_manifest_schema_mismatch:{snapshot_id}"
        )
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ArchiveContractError(f"orphan_snapshot_schema_mismatch:{snapshot_id}")
    if manifest.get("snapshot_id") != snapshot_id:
        raise ArchiveContractError(f"orphan_snapshot_id_mismatch:{snapshot_id}")
    collected_at = parse_utc(
        manifest.get("collected_at_utc"), field="orphan_collected_at"
    )
    launch = parse_utc(
        contract.get("launch_not_before_utc"), field="launch_not_before"
    )
    verification_now = utc_now()
    if collected_at < launch:
        raise ArchiveContractError(
            f"snapshot_collection_precedes_archive_launch:{snapshot_id}"
        )
    if collected_at > verification_now:
        raise ArchiveContractError(f"snapshot_collection_in_future:{snapshot_id}")
    timestamp_key = collected_at.strftime("%Y%m%dT%H%M%SZ")
    if not snapshot_id.startswith(f"{timestamp_key}-"):
        raise ArchiveContractError(f"orphan_snapshot_timestamp_mismatch:{snapshot_id}")
    if manifest.get("contract_semantic_sha256") != contract_sha256:
        raise ArchiveContractError(f"orphan_snapshot_contract_drift:{snapshot_id}")
    calendar_engine = nyse_calendar_engine_identity()
    if manifest.get("calendar_engine") != calendar_engine:
        raise ArchiveContractError(
            f"orphan_snapshot_calendar_engine_drift:{snapshot_id}"
        )
    if manifest.get("archive_passed") is not True:
        raise ArchiveContractError(f"orphan_snapshot_not_passed:{snapshot_id}")
    if manifest.get("historical_ab_allowed") is not False:
        raise ArchiveContractError(f"orphan_snapshot_historical_ab_enabled:{snapshot_id}")
    if manifest.get("pit_verified_emitted") is not False:
        raise ArchiveContractError(f"orphan_snapshot_pit_verified:{snapshot_id}")
    if any(manifest.get(key) is not expected for key, expected in SAFETY.items()):
        raise ArchiveContractError(f"orphan_snapshot_safety_drift:{snapshot_id}")
    validate_downstream_handoff(manifest, contract, snapshot_id=snapshot_id)
    git_commit = str(manifest.get("git_head") or "")
    builder_sha = str(manifest.get("builder_sha256") or "")
    builder_git_blob_sha = str(manifest.get("builder_git_blob_sha256") or "")
    fixture_mode = manifest.get("fixture_mode")
    sources = manifest.get("sources")
    validate_fixture_source_mode_alignment(
        sources,
        fixture_mode,
        snapshot_id=snapshot_id,
    )
    validate_recorded_builder_identity(
        git_commit=git_commit,
        builder_sha=builder_sha,
        builder_git_blob_sha=builder_git_blob_sha,
        fixture_mode=fixture_mode,
        snapshot_id=snapshot_id,
    )
    validate_orphan_source_contract(
        sources,
        contract=contract,
        snapshot_id=snapshot_id,
    )
    assert isinstance(sources, list)
    seen_source_ids: set[str] = set()
    missing_count = 0
    partial_count = 0
    captured_count = 0
    source_truth_counts: Counter[str] = Counter()
    row_truth_counts: Counter[str] = Counter()
    for source in sources:
        if not isinstance(source, dict):
            raise ArchiveContractError(f"orphan_snapshot_source_not_object:{snapshot_id}")
        validate_source_audit_schema(
            source,
            fixture_mode=fixture_mode,
            snapshot_id=snapshot_id,
        )
        source_id = str(source.get("source_id") or "")
        if source_id in seen_source_ids:
            raise ArchiveContractError(f"orphan_snapshot_source_id_invalid:{snapshot_id}")
        seen_source_ids.add(source_id)
        status = str(source.get("status") or "")
        mode = str(source.get("mode") or "")
        truth = source.get("truth_class")
        excluded_dates = source.get("excluded_non_session_dates")
        excluded_count = source.get("excluded_non_session_row_count")
        if (
            not isinstance(excluded_dates, list)
            or type(excluded_count) is not int
            or excluded_count != len(excluded_dates)
            or excluded_dates != sorted(set(excluded_dates))
        ):
            raise ArchiveContractError(
                f"orphan_snapshot_excluded_session_metadata_invalid:{source_id}"
            )
        parsed_excluded = [
            strict_iso_date(item, field=f"orphan_{source_id}_excluded_session")
            for item in excluded_dates
        ]
        if excluded_dates and source.get("source_kind") != "INDEX_HISTORY":
            raise ArchiveContractError(
                f"orphan_snapshot_excluded_session_source_invalid:{source_id}"
            )
        if parsed_excluded:
            valid_excluded_range = nyse_session_dates(
                parsed_excluded[0], parsed_excluded[-1]
            )
            if any(item in valid_excluded_range for item in parsed_excluded):
                raise ArchiveContractError(
                    f"orphan_snapshot_excluded_session_date_invalid:{source_id}"
                )
        if status == "missing_or_unavailable":
            missing_count += 1
            if (
                mode != "missing"
                or truth is not None
                or source.get("captured_at_utc") is not None
                or source.get("resolved_url") is not None
                or source.get("public_request_params") != {}
                or source.get("raw_sha256") is not None
                or source.get("raw_object") is not None
                or source.get("normalized_sha256") is not None
                or source.get("normalized_object") is not None
                or source.get("normalized_row_count") != 0
                or not str(source.get("reason") or "")
            ):
                raise ArchiveContractError(f"orphan_snapshot_missing_source_invalid:{source_id}")
            continue
        if status not in {"ready", "partial"}:
            raise ArchiveContractError(f"orphan_snapshot_present_source_invalid:{source_id}")
        if status == "partial" and source_id != "cross_asset.daily_close":
            raise ArchiveContractError(f"orphan_snapshot_partial_source_invalid:{source_id}")
        captured_at = parse_utc(
            source.get("captured_at_utc"), field=f"orphan_{source_id}_captured_at"
        )
        if (
            captured_at < launch
            or captured_at > collected_at
            or captured_at > verification_now
        ):
            raise ArchiveContractError(
                f"snapshot_source_capture_chronology_invalid:{source_id}"
            )
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
            role="raw",
        )
        validate_object_path(
            root,
            str(source.get("normalized_object") or ""),
            str(source.get("normalized_sha256") or ""),
            role="normalized",
        )
        normalized_rows = validate_normalized_object_rows(
            root,
            source,
            snapshot_id=snapshot_id,
            contract=contract,
        )
        if replay_raw:
            validate_recovered_raw_normalization(
                root,
                source,
                normalized_rows,
                contract=contract,
                snapshot_id=snapshot_id,
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
        "builder_git_blob_sha256": builder_git_blob_sha,
        "contract_semantic_sha256": contract_sha256,
        "calendar_engine": calendar_engine,
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
    root: Path, contract: Mapping[str, Any]
) -> list[dict[str, Any]]:
    entries = load_archive_index(
        root,
        contract,
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
        return entries
    if len(orphan_ids) != 1:
        raise ArchiveContractError(
            "multiple_unindexed_snapshots:" + ",".join(orphan_ids)
        )
    snapshot_id = orphan_ids[0]
    manifest, manifest_sha = verify_recoverable_snapshot(
        root, snapshot_id, contract
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
    return load_archive_index(root, contract)


def stable_read(
    path: Path,
    consumed: dict[str, str],
    *,
    maximum_bytes: int,
) -> bytes:
    if (
        not path.is_file()
        or path.is_symlink()
        or bool(getattr(path, "is_junction", lambda: False)())
    ):
        raise ArchiveContractError(f"fixture_not_regular_file:{path.name}")
    if maximum_bytes <= 0 or path.stat().st_size > maximum_bytes:
        raise ArchiveContractError(f"fixture_too_large:{path.name}")
    with path.open("rb") as handle:
        raw = handle.read(maximum_bytes + 1)
    if len(raw) > maximum_bytes:
        raise ArchiveContractError(f"fixture_too_large:{path.name}")
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


def validate_csv_quote_structure(text: str, *, source_id: str) -> None:
    """Reject quote placement that Python's otherwise strict reader repairs."""
    state = "field_start"
    for character in text:
        if (
            unicodedata.category(character) in {"Cc", "Cf", "Cs"}
            and character not in "\t\r\n"
        ):
            raise ArchiveContractError(f"{source_id}_csv_control_character_invalid")
        if state == "field_start":
            if character == '"':
                state = "quoted"
            elif character not in ",\r\n":
                state = "unquoted"
        elif state == "unquoted":
            if character == '"':
                raise ArchiveContractError(f"{source_id}_csv_quote_structure_invalid")
            if character in ",\r\n":
                state = "field_start"
        elif state == "quoted":
            if character == '"':
                state = "after_quote"
        elif state == "after_quote":
            if character == '"':
                state = "quoted"
            elif character in ",\r\n":
                state = "field_start"
            else:
                raise ArchiveContractError(f"{source_id}_csv_quote_structure_invalid")
    if state == "quoted":
        raise ArchiveContractError(f"{source_id}_csv_quote_structure_invalid")


def decode_csv(raw: bytes, *, source_id: str) -> list[list[str]]:
    try:
        text = raw.decode("utf-8-sig")
        validate_csv_quote_structure(text, source_id=source_id)
        return list(csv.reader(io.StringIO(text), strict=True))
    except ArchiveContractError:
        raise
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
    active_secret: str = "",
) -> tuple[list[dict[str, Any]], int]:
    payload = strict_json_payload(raw, source_id=source_id)
    if raw_contains_secret(raw, active_secret) or decoded_value_contains_secret(
        payload, active_secret
    ):
        raise ArchiveContractError(f"{source_id}_raw_response_contains_api_key")
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
    limit = exact_json_integer(payload["limit"], source_id=source_id, field="limit")
    offset = exact_json_integer(payload["offset"], source_id=source_id, field="offset")
    if limit != 100000 or offset != 0:
        raise ArchiveContractError(f"{source_id}_unexpected_pagination")
    observations = payload["observations"]
    if not isinstance(observations, list):
        raise ArchiveContractError(f"{source_id}_observations_not_list")
    count = exact_json_integer(payload["count"], source_id=source_id, field="count")
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
    raw: bytes,
    *,
    source_id: str,
    symbol: str,
    captured_at: datetime,
    maximum_completed_session_lag: int,
) -> tuple[list[dict[str, Any]], list[str]]:
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
    if maximum_completed_session_lag < 0:
        raise ArchiveContractError(f"{source_id}_invalid_freshness_lag")
    completed_sessions = completed_nyse_sessions(captured_at)
    latest_completed_session = completed_sessions[-1]
    for row in rows[header_index + 1 :]:
        if not any(str(value).strip() for value in row):
            continue
        observed_date = parse_cboe_date(
            row_value(row, columns, "date", source_id=source_id),
            field=f"{source_id}_observation",
        )
        observed = observed_date.isoformat()
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
    if output:
        observed_dates = [
            strict_iso_date(
                item["source_observation_date"],
                field=f"{source_id}_observation_session",
            )
            for item in output
        ]
        if any(item > captured_at.date() for item in observed_dates):
            raise ArchiveContractError(f"{source_id}_future_observation_date")
        valid_sessions = nyse_session_dates(
            observed_dates[0], max(observed_dates[-1], latest_completed_session)
        )
        incomplete_session = next(
            (
                item
                for item in observed_dates
                if item > latest_completed_session and item in valid_sessions
            ),
            None,
        )
        if incomplete_session is not None:
            raise ArchiveContractError(
                f"{source_id}_current_date_close_session_incomplete"
            )
        excluded_non_session_dates = [
            item.isoformat() for item in observed_dates if item not in valid_sessions
        ]
        if excluded_non_session_dates:
            excluded = set(excluded_non_session_dates)
            output = [
                item
                for item in output
                if item["source_observation_date"] not in excluded
            ]
        if not output:
            return output, excluded_non_session_dates
        newest = strict_iso_date(
            output[-1]["source_observation_date"],
            field=f"{source_id}_latest_observation",
        )
        threshold_position = min(
            maximum_completed_session_lag + 1, len(completed_sessions)
        )
        oldest_acceptable = completed_sessions[-threshold_position]
        if newest < oldest_acceptable:
            raise ArchiveContractError(
                f"{source_id}_stale_index_history"
            )
        if newest not in completed_sessions:
            raise ArchiveContractError(
                f"{source_id}_latest_observation_not_completed_session"
            )
        session_lag = sum(session > newest for session in completed_sessions)
        if session_lag > maximum_completed_session_lag:
            raise ArchiveContractError(
                f"{source_id}_stale_index_history:lag={session_lag}"
            )
        return output, excluded_non_session_dates
    return output, []


def one_regex_match(
    text: str, pattern: str, *, source_id: str, field: str
) -> re.Match[str]:
    matches = list(re.finditer(pattern, text, flags=re.DOTALL))
    if len(matches) != 1:
        raise ArchiveContractError(
            f"{source_id}_{field}_match_count:{len(matches)}"
        )
    return matches[0]


def nyse_calendar_engine_identity() -> dict[str, str]:
    try:
        installed = importlib.metadata.version(NYSE_CALENDAR_ENGINE["package"])
    except importlib.metadata.PackageNotFoundError as exc:
        raise ArchiveContractError("nyse_calendar_dependency_unavailable") from exc
    if installed != NYSE_CALENDAR_ENGINE["version"]:
        raise ArchiveContractError(
            "nyse_calendar_version_mismatch:"
            f"expected={NYSE_CALENDAR_ENGINE['version']}:actual={installed}"
        )
    return dict(NYSE_CALENDAR_ENGINE)


def completed_nyse_sessions(captured_at: datetime) -> list[date]:
    """Return holiday-aware NYSE sessions whose official close has passed."""
    nyse_calendar_engine_identity()
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


@lru_cache(maxsize=64)
def nyse_session_dates(start_date: date, end_date: date) -> frozenset[date]:
    """Return every official NYSE session label in an inclusive date range."""
    if start_date > end_date:
        raise ArchiveContractError("nyse_session_range_invalid")
    nyse_calendar_engine_identity()
    try:
        import pandas_market_calendars as mcal
    except ImportError as exc:
        raise ArchiveContractError("nyse_calendar_dependency_unavailable") from exc
    try:
        schedule = mcal.get_calendar("NYSE").schedule(
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
        )
    except Exception as exc:
        raise ArchiveContractError("nyse_calendar_resolution_failed") from exc
    return frozenset(session_label.date() for session_label in schedule.index)


def validate_cross_asset_close_sessions(
    observation_dates: Iterable[date],
    *,
    captured_at: datetime,
    source_id: str,
) -> None:
    observed = list(observation_dates)
    if not observed:
        return
    completed = completed_nyse_sessions(captured_at)
    latest_completed = completed[-1]
    sessions = nyse_session_dates(
        min(observed), max(max(observed), latest_completed)
    )
    if any(item not in sessions for item in observed):
        raise ArchiveContractError(f"{source_id}_observation_not_nyse_session")
    if any(item > latest_completed for item in observed):
        raise ArchiveContractError(f"{source_id}_close_session_incomplete")


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
    captured_at: datetime,
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
    observed_dates: list[date] = []
    for row in rows[header_index + 1 :]:
        if not any(str(value).strip() for value in row):
            continue
        ticker = row_value(row, columns, "ticker", source_id=source_id).strip().upper()
        if ticker not in required:
            raise ArchiveContractError(f"{source_id}_unexpected_ticker:{ticker}")
        observed_date = strict_iso_date(
            row_value(row, columns, "observation_date", source_id=source_id),
            field=f"{source_id}_observation",
        )
        observed = observed_date.isoformat()
        key = (ticker, observed)
        if key in seen:
            raise ArchiveContractError(f"{source_id}_duplicate_ticker_date")
        seen.add(key)
        observed_dates.append(observed_date)
        price_basis = row_value(
            row, columns, "price_basis", source_id=source_id
        ).strip()
        if price_basis not in allowed_basis:
            raise ArchiveContractError(f"{source_id}_invalid_price_basis")
        raw_provider = row_value(row, columns, "provider", source_id=source_id)
        provider = raw_provider.strip()
        source_url = row_value(
            row, columns, "source_url", source_id=source_id
        )
        if (
            not provider
            or provider != raw_provider
            or any(
                unicodedata.category(character) in {"Cc", "Cf", "Cs"}
                for character in provider
            )
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
    validate_cross_asset_close_sessions(
        observed_dates,
        captured_at=captured_at,
        source_id=source_id,
    )
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
    maximum_redirect_hops: int = 5,
) -> tuple[bytes | None, str, datetime | None, str]:
    expected_origin = network_origin(url, field="network_requested_url")
    if maximum_redirect_hops < 0:
        raise ArchiveContractError("network_redirect_limit_invalid")
    redirect_statuses = {301, 302, 303, 307, 308}
    request_url = url
    request_params: Mapping[str, Any] | None = dict(params or {})
    raw = b""
    final_url = ""
    try:
        for hop_number in range(maximum_redirect_hops + 1):
            with requests.get(
                request_url,
                params=(dict(request_params) if request_params is not None else None),
                headers={"User-Agent": USER_AGENT},
                timeout=int(timeout_seconds),
                stream=True,
                allow_redirects=False,
            ) as response:
                status_code = response.status_code
                if type(status_code) is not int:
                    raise ArchiveContractError("official_network_http_status_invalid")
                response_url = str(response.url or "")
                if (
                    network_origin(response_url, field="network_response_url")
                    != expected_origin
                ):
                    raise ArchiveContractError("network_redirect_origin_mismatch")
                if status_code in redirect_statuses:
                    if hop_number >= maximum_redirect_hops:
                        raise ArchiveContractError("network_redirect_limit_exceeded")
                    location = valid_url_text(
                        response.headers.get("Location"),
                        field="network_redirect_location",
                    )
                    next_url = urljoin(response_url, location)
                    if (
                        network_origin(next_url, field="network_redirect_target")
                        != expected_origin
                    ):
                        raise ArchiveContractError("network_redirect_origin_mismatch")
                    request_url = next_url
                    request_params = None
                    continue
                if status_code != 200:
                    raise ArchiveContractError(
                        f"official_network_http_status_invalid:{status_code}"
                    )
                final_url = sanitized_network_url(
                    response_url, field="network_final_url"
                )
                content_length = str(
                    response.headers.get("Content-Length") or ""
                ).strip()
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
                break
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
        "excluded_non_session_row_count": 0,
        "excluded_non_session_dates": [],
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
    fred_key = active_fred_api_key(contract)

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
                raw = stable_read(
                    fixture_path,
                    consumed,
                    maximum_bytes=maximum_bytes,
                )
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
                maximum_redirect_hops=int(
                    contract["collection"]["maximum_redirect_hops"]
                ),
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
        expected_vintage = captured_at.date().isoformat()
        if (
            vintage_date != expected_vintage
            or observation_end != expected_vintage
            or observation_start
            != subtract_years(captured_at.date(), history_years).isoformat()
        ):
            raise ArchiveContractError(f"{source_id}_capture_window_mismatch")
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
            active_secret=fred_key,
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
                raw = stable_read(
                    fixture_path,
                    consumed,
                    maximum_bytes=maximum_bytes,
                )
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
                maximum_redirect_hops=int(
                    contract["collection"]["maximum_redirect_hops"]
                ),
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
            normalized, excluded_non_session_dates = normalize_cboe_index(
                raw,
                source_id=source_id,
                symbol=name,
                captured_at=captured_at,
                maximum_completed_session_lag=int(
                    contract["cboe"]["index_history_max_completed_nyse_session_lag"]
                ),
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
            excluded_non_session_dates = []
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
                "excluded_non_session_dates": excluded_non_session_dates,
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
        raw = stable_read(
            cross_fixture,
            consumed,
            maximum_bytes=maximum_bytes,
        )
        if len(raw) > maximum_bytes:
            raise ArchiveContractError(f"{cross_source_id}_raw_too_large")
        normalized, missing_tickers = normalize_cross_asset(
            raw,
            source_id=cross_source_id,
            required_tickers=cross_spec["required_tickers"],
            allowed_price_basis=cross_spec["allowed_price_basis"],
            captured_at=fixture_time,
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
    *,
    active_secret: str,
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
        if raw_contains_secret(raw, active_secret):
            raise ArchiveContractError(
                f"{capture.get('source_id')}_raw_response_contains_api_key"
            )
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
            "excluded_non_session_row_count": len(
                capture.get("excluded_non_session_dates") or []
            ),
            "excluded_non_session_dates": list(
                capture.get("excluded_non_session_dates") or []
            ),
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
            if fixture_time > utc_now():
                raise ArchiveContractError("fixture_collected_at_in_future")
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

        identity = builder_identity(require_head_match=not fixture_mode)

        writer_lock = acquire_archive_writer_lock(
            output_root,
            float(contract["collection"]["writer_lock_timeout_seconds"]),
        )
        recover_abandoned_staging(output_root)
        existing_entries = recover_verified_unindexed_snapshot(output_root, contract)
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
        verify_builder_identity(identity, require_head_match=not fixture_mode)
        audits, raw_objects, normalized_objects = materialize_sources(
            captures,
            missing_audits,
            active_secret=active_fred_api_key(contract),
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
        calendar_engine = nyse_calendar_engine_identity()
        snapshot_identity = {
            "schema_version": SCHEMA_VERSION,
            "collected_at_utc": collected_at,
            "git_head": identity["git_head"],
            "builder_sha256": identity["builder_sha256"],
            "builder_git_blob_sha256": identity["builder_git_blob_sha256"],
            "contract_semantic_sha256": CANONICAL_CONTRACT_SEMANTIC_SHA256,
            "calendar_engine": calendar_engine,
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
            return committed_result_with_receipt(output_root, result)
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
            "builder_git_blob_sha256": identity["builder_git_blob_sha256"],
            "contract_semantic_sha256": CANONICAL_CONTRACT_SEMANTIC_SHA256,
            "calendar_engine": calendar_engine,
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
            verify_builder_identity(identity, require_head_match=not fixture_mode)
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
            output_root, contract
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
        return committed_result_with_receipt(output_root, result)
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
