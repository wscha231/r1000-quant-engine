#!/usr/bin/env python3
"""Build a replay-only Run287 price cache from a prior GitHub artifact.

The input is an already extracted
``daily-operating-selection-refresh-<run_id>`` artifact.  No network access is
performed.  The caller must also provide the closed v2 GitHub provenance
metadata contract, including exact artifact, workflow, repository, commit
lineage, digest, and capture-time evidence.

Only explicitly requested tickers are materialized.  Every requested ticker
must have an exact bar for the selected NYSE session; stale, missing,
duplicate, or future source data fails closed before the cache is written.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_weekly_evaluation import px_cache_name  # noqa: E402
from tools.build_run287_catchup_price_capture import (  # noqa: E402
    CAPTURE_ARTIFACT_ROOT_MARKER,
    CAPTURE_MANIFEST_KEYS,
    CAPTURE_SCHEMA,
    CAPTURE_SESSION_FILE_KEYS,
    CAPTURE_SESSION_KEYS,
    CAPTURE_STATUS,
    PLAN_KEYS,
    PLAN_SCHEMA,
    PLAN_STATUS,
    PRICE_MANIFEST_SCHEMA,
    REQUIRED_BENCHMARKS,
    SAFETY_ENVELOPE as CAPTURE_SAFETY_ENVELOPE,
)


SCHEMA_VERSION = "run287-catchup-price-evidence-v1"
MANIFEST_SCHEMA_VERSION = "run287-catchup-price-cache-manifest-v1"
READY_STATUS = "READY_RUN287_CATCHUP_PRICE_EVIDENCE_REPLAY_ONLY"
BLOCKED_STATUS = "BLOCKED_RUN287_CATCHUP_PRICE_EVIDENCE"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
RUN_ID_RE = re.compile(r"^[1-9][0-9]*$")
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
TICKER_RE = re.compile(r"^[A-Z0-9.^=-]+$")
WORKFLOW_PATH = ".github/workflows/daily_operating_selection_refresh.yml"
APPROVED_LEGACY_RUN_ID = "29625744031"
APPROVED_LEGACY_ARTIFACT_ID = "8424009573"
APPROVED_LEGACY_HEAD_SHA = "4196e72f8450de0c652848c9b77d22c1b0bbcc37"
APPROVED_LEGACY_HEAD_BRANCH = (
    "codex/run287-paper-ledger-continuity-20260718"
)
ARTIFACT_METADATA_KEYS = frozenset(
    {
        "schema_version",
        "run_id",
        "artifact_id",
        "artifact_name",
        "artifact_zip_sha256",
        "artifact_api_digest",
        "artifact_captured_at_utc",
        "workflow_id",
        "workflow_path",
        "head_branch",
        "head_sha",
        "workflow_event",
        "workflow_status",
        "workflow_conclusion",
        "workflow_created_at_utc",
        "workflow_updated_at_utc",
        "workflow_run_attempt",
        "repository",
        "head_repository",
        "default_branch",
        "current_default_head_sha",
        "origin_verification_mode",
        "workflow_identity_verified",
        "repository_identity_verified",
        "head_lineage_verified",
    }
)
SOURCE_FILES = {
    "market_session_gate": Path("outputs/daily_market_session_gate/session.json"),
    "market_snapshot_summary": Path("outputs/daily_market_snapshot/summary.json"),
    "market_snapshot_csv": Path("outputs/daily_market_snapshot/market_snapshot.csv"),
}
CAPTURE_ROOT_RELATIVE = Path("outputs/run287_catchup_price_capture")
SNAPSHOT_COLUMNS = {
    "ticker",
    "price_available",
    "price_missing_reason",
    "latest_price_date",
    "open",
    "high",
    "low",
    "previous_close",
    "adjusted_close",
    "volume",
    "production_mutation_allowed",
    "live_trading_enabled",
}


class ContractError(ValueError):
    """Stable fail-closed contract error."""


def fail(code: str) -> None:
    raise ContractError(code)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(path: Path, *, label: str, relative_path: str) -> dict[str, Any]:
    return {
        "label": label,
        "path": relative_path.replace("\\", "/"),
        "bytes": int(path.stat().st_size),
        "sha256": sha256_file(path),
    }


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def read_json_object(path: Path, code: str) -> dict[str, Any]:
    if not path.is_file():
        fail(f"{code}_missing")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        fail(f"{code}_invalid_json")
    if not isinstance(value, dict):
        fail(f"{code}_not_object")
    return value


def artifact_regular_file(
    artifact_root: Path,
    relative: Path,
    *,
    code: str,
) -> Path:
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        fail(f"{code}_path_invalid")
    path = artifact_root / relative
    current = artifact_root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            fail(f"{code}_symlink")
    try:
        if not path.is_file() or artifact_root.resolve() not in path.resolve().parents:
            fail(f"{code}_missing_or_unsafe")
    except OSError:
        fail(f"{code}_missing_or_unsafe")
    return path


def require_fingerprint(
    artifact_root: Path,
    record: Any,
    *,
    expected_path: str,
    code: str,
) -> Path:
    if not isinstance(record, dict) or set(record) != {"path", "bytes", "sha256"}:
        fail(f"{code}_record")
    if (
        record.get("path") != expected_path
        or not isinstance(record.get("bytes"), int)
        or isinstance(record.get("bytes"), bool)
        or record["bytes"] <= 0
        or not SHA256_RE.fullmatch(str(record.get("sha256") or ""))
    ):
        fail(f"{code}_record")
    path = artifact_regular_file(
        artifact_root,
        Path(expected_path),
        code=code,
    )
    if path.stat().st_size != record["bytes"] or sha256_file(path) != record["sha256"]:
        fail(f"{code}_hash")
    return path


def resolve_capture_source_files(
    *,
    artifact_root: Path,
    selected_date: pd.Timestamp,
    artifact_identity: dict[str, Any],
    captured_at: pd.Timestamp,
    ingested_at: pd.Timestamp,
) -> tuple[dict[str, Path], list[tuple[Path, str, str]], str]:
    capture_relative = CAPTURE_ROOT_RELATIVE / "manifest.json"
    capture_path = artifact_regular_file(
        artifact_root,
        capture_relative,
        code="capture_manifest",
    )
    capture = read_json_object(capture_path, "capture_manifest")
    if (
        set(capture) != CAPTURE_MANIFEST_KEYS
        or capture.get("schema_version") != CAPTURE_SCHEMA
        or capture.get("status") != CAPTURE_STATUS
    ):
        fail("capture_manifest_schema")
    for key, expected in CAPTURE_SAFETY_ENVELOPE.items():
        if capture.get(key) != expected:
            fail(f"capture_manifest_safety:{key}")
    source = capture.get("source")
    expected_source_keys = {
        "repository",
        "source_sha",
        "run_id",
        "run_attempt",
        "event_name",
        "job_key",
    }
    if (
        not isinstance(source, dict)
        or set(source) != expected_source_keys
        or source.get("repository") != artifact_identity["repository"]
        or source.get("source_sha") != artifact_identity["head_sha"]
        or source.get("run_id") != artifact_identity["run_id"]
        or source.get("run_attempt") != "1"
        or source.get("run_attempt") != artifact_identity["workflow_run_attempt"]
        or source.get("event_name") != artifact_identity["workflow_event"]
        or source.get("job_key") != "capture_catchup_evidence"
        or artifact_identity["workflow_event"] != "workflow_dispatch"
        or artifact_identity["workflow_conclusion"] != "success"
    ):
        fail("capture_manifest_source_identity")
    try:
        session_count = int(capture.get("pending_session_count"))
        ticker_count = int(capture.get("ticker_union_count"))
    except Exception:
        fail("capture_manifest_counts")
    sessions = capture.get("sessions")
    tickers = capture.get("ticker_union")
    if (
        not isinstance(sessions, list)
        or len(sessions) != session_count
        or not isinstance(tickers, list)
        or any(
            not isinstance(ticker, str) or not TICKER_RE.fullmatch(ticker)
            for ticker in tickers
        )
        or tickers != sorted(set(tickers))
        or len(tickers) != ticker_count
        or session_count <= 0
        or ticker_count <= 0
    ):
        fail("capture_manifest_counts")
    ticker_sources = capture.get("ticker_sources")
    if not isinstance(ticker_sources, dict) or not ticker_sources:
        fail("capture_ticker_sources")
    source_union: set[str] = set()
    for label, values in ticker_sources.items():
        if (
            not isinstance(label, str)
            or not label
            or not isinstance(values, list)
            or values != sorted(set(values))
            or any(value not in tickers for value in values)
        ):
            fail("capture_ticker_sources")
        source_union.update(values)
    if source_union != set(tickers) or ticker_sources.get("required") != sorted(
        REQUIRED_BENCHMARKS
    ):
        fail("capture_ticker_sources")

    canonical_date = parse_session_date(
        capture.get("canonical_as_of_date"),
        "capture_canonical_asof_invalid",
    )
    through_date = parse_session_date(
        capture.get("through_session_date"),
        "capture_through_session_invalid",
    )
    if through_date <= canonical_date:
        fail("capture_session_range_invalid")
    schedule = mcal.get_calendar("NYSE").schedule(
        start_date=(canonical_date + pd.Timedelta(days=1)).date(),
        end_date=through_date.date(),
    )
    expected_sessions = [
        pd.Timestamp(value).date().isoformat() for value in schedule.index
    ]
    if not expected_sessions or expected_sessions[-1] != through_date.date().isoformat():
        fail("capture_session_range_invalid")

    expected_top = {
        (CAPTURE_ROOT_RELATIVE / name).as_posix()
        for name in (
            "manifest.json",
            "plan.json",
            "paper_selection.json",
            "ticker_union.csv",
            "source_price_cache_manifest.json",
        )
    }
    marker_path = require_fingerprint(
        artifact_root,
        capture.get("artifact_root_marker"),
        expected_path=CAPTURE_ARTIFACT_ROOT_MARKER.as_posix(),
        code="capture_artifact_root_marker",
    )
    marker = read_json_object(marker_path, "capture_artifact_root_marker")
    if marker != {
        "schema_version": "run287-catchup-price-capture-artifact-root-v1",
        "capture_manifest_path": capture_relative.as_posix(),
        "repository": artifact_identity["repository"],
        "source_sha": artifact_identity["head_sha"],
        "run_id": artifact_identity["run_id"],
        "read_only": True,
        "production_mutation_allowed": False,
        "live_trading_enabled": False,
    }:
        fail("capture_artifact_root_marker_contract")
    expected_top.add(CAPTURE_ARTIFACT_ROOT_MARKER.as_posix())
    plan_path = require_fingerprint(
        artifact_root,
        capture.get("capture_plan"),
        expected_path=(CAPTURE_ROOT_RELATIVE / "plan.json").as_posix(),
        code="capture_plan",
    )
    plan = read_json_object(plan_path, "capture_plan")
    if (
        set(plan) != PLAN_KEYS
        or plan.get("schema_version") != PLAN_SCHEMA
        or plan.get("status") != PLAN_STATUS
    ):
        fail("capture_plan_contract")
    for key, expected in CAPTURE_SAFETY_ENVELOPE.items():
        if plan.get(key) != expected:
            fail(f"capture_plan_safety:{key}")
    for key in (
        "canonical_as_of_date",
        "through_session_date",
        "pending_session_count",
        "ticker_union",
        "ticker_union_count",
        "ticker_sources",
        "paper",
    ):
        if plan.get(key) != capture.get(key):
            fail(f"capture_plan_manifest_mismatch:{key}")
    if plan.get("pending_sessions") != expected_sessions:
        fail("capture_plan_session_sequence")
    plan_generated = parse_utc(
        plan.get("generated_at_utc"), "capture_plan_generated_at_invalid"
    )
    capture_generated = parse_utc(
        capture.get("generated_at_utc"), "capture_generated_at_invalid"
    )
    through_close = exact_nyse_close(through_date)
    if (
        plan_generated < through_close + pd.Timedelta(minutes=90)
        or capture_generated < plan_generated
        or capture_generated > captured_at
        or captured_at > ingested_at
    ):
        fail("capture_time_order_invalid")

    ticker_book_path = require_fingerprint(
        artifact_root,
        capture.get("ticker_book"),
        expected_path=(CAPTURE_ROOT_RELATIVE / "ticker_union.csv").as_posix(),
        code="capture_ticker_book",
    )
    ticker_book_record = capture["ticker_book"]
    if plan.get("ticker_book") != {
        "path": "ticker_union.csv",
        "bytes": ticker_book_record["bytes"],
        "sha256": ticker_book_record["sha256"],
    }:
        fail("capture_plan_ticker_book_mismatch")
    try:
        ticker_book = pd.read_csv(ticker_book_path, dtype=str)
    except Exception:
        fail("capture_ticker_book_invalid")
    if (
        list(ticker_book.columns) != ["ticker"]
        or ticker_book["ticker"].tolist() != tickers
    ):
        fail("capture_ticker_book_contract")

    source_price_manifest_path = require_fingerprint(
        artifact_root,
        capture.get("source_price_cache_manifest"),
        expected_path=(CAPTURE_ROOT_RELATIVE / "source_price_cache_manifest.json").as_posix(),
        code="capture_source_price_manifest",
    )
    source_price_manifest = read_json_object(
        source_price_manifest_path, "capture_source_price_manifest"
    )
    source_price_files = capture.get("source_price_cache_files")
    if (
        source_price_manifest.get("schema_version") != PRICE_MANIFEST_SCHEMA
        or source_price_manifest.get("status") not in {"completed", "already_cached"}
        or source_price_manifest.get("exact_operating_universe") is not True
        or source_price_manifest.get("refresh_through_date")
        != capture.get("through_session_date")
        or source_price_manifest.get("refresh_through_exact_coverage") is not True
        or source_price_manifest.get("refresh_through_ticker_count") != ticker_count
        or source_price_manifest.get("refresh_through_exact_ticker_count")
        != ticker_count
        or source_price_manifest.get("review_only") is not True
        or source_price_manifest.get("production_mutation_allowed") is not False
        or source_price_manifest.get("live_trading_enabled") is not False
        or source_price_manifest.get("cache_files") != source_price_files
        or not isinstance(source_price_files, dict)
        or sorted(source_price_files) != tickers
    ):
        fail("capture_source_price_file_map_mismatch")
    for ticker in tickers:
        record = source_price_files[ticker]
        if (
            not isinstance(record, dict)
            or set(record) != {"file", "sha256", "bytes"}
            or record.get("file") != px_cache_name(ticker)
            or not SHA256_RE.fullmatch(str(record.get("sha256") or ""))
            or not isinstance(record.get("bytes"), int)
            or isinstance(record.get("bytes"), bool)
            or record["bytes"] <= 0
        ):
            fail(f"capture_source_price_file_record:{ticker}")
    selection_record = ((capture.get("paper") or {}).get("immutable_heads") or {})
    selection_path = artifact_regular_file(
        artifact_root,
        CAPTURE_ROOT_RELATIVE / "paper_selection.json",
        code="capture_paper_selection",
    )
    if (
        selection_path.stat().st_size != selection_record.get("selection_bytes")
        or sha256_file(selection_path) != selection_record.get("selection_sha256")
    ):
        fail("capture_paper_selection_hash")

    selected_text = selected_date.date().isoformat()
    selected_paths: dict[str, Path] | None = None
    selected_specs: list[tuple[Path, str, str]] = []
    expected_tree = set(expected_top)
    observed_sessions: list[str] = []
    for index, record in enumerate(sessions):
        if not isinstance(record, dict) or set(record) != CAPTURE_SESSION_KEYS:
            fail(f"capture_session_record:{index}")
        session_text = str(record.get("session_date") or "")
        parsed = parse_session_date(session_text, "capture_session_date")
        if observed_sessions and parsed <= parse_session_date(
            observed_sessions[-1], "capture_session_date"
        ):
            fail("capture_sessions_not_strictly_ordered")
        observed_sessions.append(session_text)
        files = record.get("files")
        if (
            record.get("ticker_count") != ticker_count
            or not isinstance(files, dict)
            or set(files) != CAPTURE_SESSION_FILE_KEYS
        ):
            fail(f"capture_session_contract:{session_text}")
        official_close = exact_nyse_close(parsed)
        if parse_utc(
            record.get("official_market_close_utc"),
            "capture_session_close_invalid",
        ) != official_close:
            fail(f"capture_session_close_mismatch:{session_text}")
        base = CAPTURE_ROOT_RELATIVE / "sessions" / session_text / "outputs"
        expected = {
            "market_session_gate": base / "daily_market_session_gate/session.json",
            "market_snapshot_csv": base / "daily_market_snapshot/market_snapshot.csv",
            "market_snapshot_summary": base / "daily_market_snapshot/summary.json",
            "market_snapshot_report": base / "daily_market_snapshot/report.md",
        }
        verified: dict[str, Path] = {}
        for label, relative in expected.items():
            expected_path = relative.as_posix()
            verified[label] = require_fingerprint(
                artifact_root,
                files.get(label),
                expected_path=expected_path,
                code=f"capture_session_{label}",
            )
            expected_tree.add(expected_path)
        gate = read_json_object(
            verified["market_session_gate"], "capture_session_gate"
        )
        gate_checked_at = validate_gate(
            gate,
            selected_date=parsed,
            official_close=official_close,
        )
        summary = read_json_object(
            verified["market_snapshot_summary"],
            "capture_session_summary",
        )
        validate_summary(
            summary,
            selected_date=parsed,
            official_close=official_close,
            gate_checked_at=gate_checked_at,
            captured_at=captured_at,
            ingested_at=ingested_at,
        )
        if (
            summary.get("asof_date") != session_text
            or summary.get("latest_price_date_min") != session_text
            or summary.get("exact_asof_close_required") is not True
            or summary.get("exact_asof_close_count") != ticker_count
            or summary.get("exact_asof_close_missing_count") != 0
            or summary.get("exact_asof_close_missing_tickers") != []
            or summary.get("ticker_count") != ticker_count
        ):
            fail(f"capture_session_summary_contract:{session_text}")
        if session_text == selected_text:
            if selected_paths is not None:
                fail("capture_selected_session_duplicate")
            selected_paths = {
                "market_session_gate": verified["market_session_gate"],
                "market_snapshot_summary": verified["market_snapshot_summary"],
                "market_snapshot_csv": verified["market_snapshot_csv"],
            }
            selected_specs = [
                (
                    verified[label],
                    label,
                    expected[label].as_posix(),
                )
                for label in (
                    "market_session_gate",
                    "market_snapshot_summary",
                    "market_snapshot_csv",
                )
            ]
    if selected_paths is None:
        fail("capture_selected_session_missing")
    if observed_sessions != expected_sessions:
        fail("capture_session_sequence")
    actual_tree: set[str] = set()
    for path in artifact_root.rglob("*"):
        if path.is_symlink():
            fail("capture_tree_symlink")
        if path.is_file():
            actual_tree.add(path.relative_to(artifact_root).as_posix())
        elif not path.is_dir():
            fail("capture_tree_non_regular")
    if actual_tree != expected_tree:
        fail("capture_tree_file_set")
    return (
        selected_paths,
        [
            (
                capture_path,
                "catchup_price_capture_manifest",
                capture_relative.as_posix(),
            ),
            *selected_specs,
        ],
        "MULTI_SESSION_READ_ONLY_CAPTURE",
    )


def resolve_source_files(
    *,
    artifact_root: Path,
    selected_date: pd.Timestamp,
    artifact_identity: dict[str, Any],
    captured_at: pd.Timestamp,
    ingested_at: pd.Timestamp,
) -> tuple[dict[str, Path], list[tuple[Path, str, str]], str]:
    capture_manifest = artifact_root / CAPTURE_ROOT_RELATIVE / "manifest.json"
    flat_paths = {
        label: artifact_root / relative for label, relative in SOURCE_FILES.items()
    }
    flat_present = [path.is_file() for path in flat_paths.values()]
    if capture_manifest.is_file():
        if any(flat_present):
            fail("artifact_source_layout_ambiguous")
        return resolve_capture_source_files(
            artifact_root=artifact_root,
            selected_date=selected_date,
            artifact_identity=artifact_identity,
            captured_at=captured_at,
            ingested_at=ingested_at,
        )
    if not all(flat_present):
        missing = [
            label for (label, path), present in zip(flat_paths.items(), flat_present)
            if not present
        ]
        fail("artifact_source_missing:" + ",".join(sorted(missing)))
    unsafe = [
        label
        for label, path in flat_paths.items()
        if path.is_symlink() or artifact_root not in path.resolve().parents
    ]
    if unsafe:
        fail("artifact_source_unsafe:" + ",".join(sorted(unsafe)))
    return (
        flat_paths,
        [
            (flat_paths[label], label, str(SOURCE_FILES[label]))
            for label in sorted(flat_paths)
        ],
        "LEGACY_SINGLE_SESSION_DAILY_ARTIFACT",
    )


def parse_session_date(value: Any, code: str) -> pd.Timestamp:
    text = str(value or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        fail(code)
    try:
        stamp = pd.Timestamp(text)
    except Exception:
        fail(code)
    if stamp.strftime("%Y-%m-%d") != text:
        fail(code)
    return stamp.normalize()


def parse_utc(value: Any, code: str) -> pd.Timestamp:
    text = str(value or "").strip()
    if not text:
        fail(code)
    try:
        stamp = pd.Timestamp(text)
    except Exception:
        fail(code)
    if pd.isna(stamp) or stamp.tzinfo is None:
        fail(code)
    return stamp.tz_convert("UTC")


def strict_bool(value: Any, code: str) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    fail(code)


def clean_ticker(value: Any) -> str:
    ticker = str(value or "").strip().upper()
    if not ticker or not TICKER_RE.fullmatch(ticker):
        fail("invalid_ticker")
    return ticker


def nonblank(value: Any) -> bool:
    return not pd.isna(value) and bool(str(value).strip())


def validate_github_compare_payload(
    payload: dict[str, Any],
    *,
    source_sha: str,
    current_sha: str,
) -> None:
    """Require the source commit to be the current head or its ancestor.

    GitHub's compare response does not expose a ``head_commit`` object.  The
    caller obtains the response from the explicit ``source...current`` API
    route, while the base and merge-base fields plus ahead/behind counters
    prove the required lineage.
    """
    if not SHA1_RE.fullmatch(source_sha) or not SHA1_RE.fullmatch(current_sha):
        fail("artifact_compare_sha_invalid")
    status = payload.get("status")
    ahead_by = payload.get("ahead_by")
    behind_by = payload.get("behind_by")
    identity_valid = (
        status == "identical"
        and source_sha == current_sha
        and ahead_by == 0
        and behind_by == 0
    )
    ancestor_valid = (
        status == "ahead"
        and source_sha != current_sha
        and isinstance(ahead_by, int)
        and not isinstance(ahead_by, bool)
        and ahead_by > 0
        and behind_by == 0
    )
    if (
        str((payload.get("base_commit") or {}).get("sha") or "")
        != source_sha
        or str((payload.get("merge_base_commit") or {}).get("sha") or "")
        != source_sha
        or not (identity_valid or ancestor_valid)
    ):
        fail("artifact_source_not_current_default_ancestor")


def requested_tickers(values: list[str]) -> list[str]:
    tickers = [clean_ticker(value) for value in values]
    if len(tickers) != len(set(tickers)):
        fail("required_tickers_duplicate")
    return sorted(tickers)


def exact_nyse_close(session_date: pd.Timestamp) -> pd.Timestamp:
    schedule = mcal.get_calendar("NYSE").schedule(
        start_date=session_date.date(),
        end_date=session_date.date(),
    )
    if len(schedule) != 1:
        fail("selected_date_not_nyse_session")
    close = pd.Timestamp(schedule.iloc[0]["market_close"])
    return close.tz_localize("UTC") if close.tzinfo is None else close.tz_convert("UTC")


def validate_metadata(
    metadata: dict[str, Any],
    *,
    artifact_root: Path,
) -> tuple[dict[str, Any], pd.Timestamp]:
    if (
        metadata.get("schema_version")
        != "github-artifact-download-metadata-v2"
        or set(metadata) != ARTIFACT_METADATA_KEYS
    ):
        fail("artifact_metadata_schema")
    run_id = str(metadata.get("run_id") or "").strip()
    if not RUN_ID_RE.fullmatch(run_id):
        fail("artifact_run_id_invalid")
    artifact_id = str(metadata.get("artifact_id") or "").strip()
    workflow_id = str(metadata.get("workflow_id") or "").strip()
    run_attempt = str(
        metadata.get("workflow_run_attempt") or ""
    ).strip()
    if not all(
        RUN_ID_RE.fullmatch(value)
        for value in (artifact_id, workflow_id, run_attempt)
    ):
        fail("artifact_numeric_identity_invalid")
    zip_digest = str(
        metadata.get("artifact_zip_sha256") or ""
    ).strip().lower()
    if not SHA256_RE.fullmatch(zip_digest):
        fail("artifact_zip_sha256_invalid")
    expected_name = f"daily-operating-selection-refresh-{run_id}"
    metadata_name = str(metadata.get("artifact_name") or "").strip()
    if metadata_name != expected_name:
        fail("artifact_name_invalid")
    if artifact_root.name != expected_name:
        fail("artifact_root_run_id_mismatch")
    if (
        str(metadata.get("artifact_api_digest") or "").strip()
        != f"sha256:{zip_digest}"
        or metadata.get("workflow_path") != WORKFLOW_PATH
        or metadata.get("workflow_event")
        not in {"schedule", "workflow_dispatch"}
        or metadata.get("workflow_status") != "completed"
        or metadata.get("workflow_conclusion")
        not in {"success", "failure"}
        or metadata.get("workflow_identity_verified") is not True
        or metadata.get("repository_identity_verified") is not True
        or metadata.get("head_lineage_verified") is not True
    ):
        fail("artifact_workflow_identity_invalid")
    head_sha = str(metadata.get("head_sha") or "").strip()
    current_head_sha = str(
        metadata.get("current_default_head_sha") or ""
    ).strip()
    head_branch = str(metadata.get("head_branch") or "").strip()
    default_branch = str(
        metadata.get("default_branch") or ""
    ).strip()
    repository = str(metadata.get("repository") or "").strip()
    head_repository = str(
        metadata.get("head_repository") or ""
    ).strip()
    if (
        not SHA1_RE.fullmatch(head_sha)
        or not SHA1_RE.fullmatch(current_head_sha)
        or not head_branch
        or not default_branch
        or not repository
        or head_repository != repository
    ):
        fail("artifact_source_repository_invalid")
    origin_mode = str(
        metadata.get("origin_verification_mode") or ""
    ).strip()
    if origin_mode == "APPROVED_LEGACY_ARTIFACT_PIN":
        if (
            run_id != APPROVED_LEGACY_RUN_ID
            or artifact_id != APPROVED_LEGACY_ARTIFACT_ID
            or head_sha != APPROVED_LEGACY_HEAD_SHA
            or head_branch != APPROVED_LEGACY_HEAD_BRANCH
            or metadata.get("workflow_event") != "workflow_dispatch"
            or metadata.get("workflow_conclusion") != "success"
        ):
            fail("approved_legacy_artifact_identity_invalid")
    elif origin_mode == "DEFAULT_BRANCH_ANCESTOR":
        if head_branch != default_branch:
            fail("artifact_default_branch_identity_invalid")
    else:
        fail("artifact_origin_verification_mode_invalid")
    captured_at = parse_utc(
        metadata.get("artifact_captured_at_utc"),
        "artifact_capture_time_invalid",
    )
    workflow_created_at = parse_utc(
        metadata.get("workflow_created_at_utc"),
        "artifact_workflow_created_at_invalid",
    )
    workflow_updated_at = parse_utc(
        metadata.get("workflow_updated_at_utc"),
        "artifact_workflow_updated_at_invalid",
    )
    if not (
        workflow_created_at
        <= captured_at
        <= workflow_updated_at
    ):
        fail("artifact_workflow_time_order_invalid")
    artifact = {
        "run_id": run_id,
        "artifact_id": artifact_id,
        "artifact_name": expected_name,
        "expected_zip_sha256": zip_digest,
        "api_digest": f"sha256:{zip_digest}",
        "workflow_id": workflow_id,
        "workflow_path": WORKFLOW_PATH,
        "head_branch": head_branch,
        "head_sha": head_sha,
        "workflow_event": metadata["workflow_event"],
        "workflow_status": metadata["workflow_status"],
        "workflow_conclusion": metadata["workflow_conclusion"],
        "workflow_run_attempt": run_attempt,
        "repository": repository,
        "head_repository": head_repository,
        "default_branch": default_branch,
        "current_default_head_sha": current_head_sha,
        "origin_verification_mode": origin_mode,
        "workflow_identity_verified": True,
        "repository_identity_verified": True,
        "head_lineage_verified": True,
        "run_id_verified_against_artifact_root": True,
    }
    return artifact, captured_at


def validate_gate(
    gate: dict[str, Any],
    *,
    selected_date: pd.Timestamp,
    official_close: pd.Timestamp,
) -> pd.Timestamp:
    if gate.get("schema_version") != "daily-market-session-gate-v1":
        fail("session_gate_schema")
    if str(gate.get("calendar") or "") != "NYSE":
        fail("session_gate_calendar")
    if strict_bool(gate.get("ready"), "session_gate_ready_invalid") is not True:
        fail("session_gate_not_ready")
    if not str(gate.get("status") or "").startswith("READY_"):
        fail("session_gate_status")
    gate_date = parse_session_date(gate.get("session_date"), "session_gate_date_invalid")
    if gate_date != selected_date:
        fail("session_gate_date_mismatch")
    gate_close = parse_utc(gate.get("market_close_utc"), "session_gate_close_invalid")
    if gate_close != official_close:
        fail("session_gate_close_mismatch")
    checked_at = parse_utc(gate.get("checked_at_utc"), "session_gate_checked_at_invalid")
    if checked_at < official_close:
        fail("session_gate_checked_before_close")
    return checked_at


def validate_summary(
    summary: dict[str, Any],
    *,
    selected_date: pd.Timestamp,
    official_close: pd.Timestamp,
    gate_checked_at: pd.Timestamp,
    captured_at: pd.Timestamp | None,
    ingested_at: pd.Timestamp,
) -> pd.Timestamp:
    if summary.get("schema_version") != "daily-market-snapshot-v1":
        fail("market_snapshot_summary_schema")
    if summary.get("status") != "completed":
        fail("market_snapshot_summary_status")
    max_date = parse_session_date(
        summary.get("latest_price_date_max"),
        "market_snapshot_latest_price_date_max_invalid",
    )
    if max_date != selected_date:
        fail("market_snapshot_latest_price_date_max_mismatch")
    if strict_bool(summary.get("review_only"), "summary_review_only_invalid") is not True:
        fail("summary_not_review_only")
    if (
        strict_bool(
            summary.get("production_mutation_allowed"),
            "summary_production_flag_invalid",
        )
        is not False
    ):
        fail("summary_production_mutation_allowed")
    if (
        strict_bool(
            summary.get("live_trading_enabled"),
            "summary_live_trading_flag_invalid",
        )
        is not False
    ):
        fail("summary_live_trading_enabled")
    generated_at = parse_utc(
        summary.get("generated_at_utc"),
        "market_snapshot_generated_at_invalid",
    )
    if generated_at <= official_close:
        fail("market_snapshot_generated_not_after_close")
    if generated_at < gate_checked_at:
        fail("market_snapshot_generated_before_gate_check")
    if generated_at > ingested_at:
        fail("market_snapshot_generated_in_future")
    if captured_at is not None:
        if generated_at > captured_at:
            fail("market_snapshot_generated_after_artifact_capture")
        if captured_at > ingested_at:
            fail("artifact_capture_in_future")
    return generated_at


def numeric_value(row: pd.Series, column: str, *, positive: bool) -> float:
    try:
        value = float(row[column])
    except Exception:
        fail(f"used_row_{column}_invalid")
    if not math.isfinite(value):
        fail(f"used_row_{column}_invalid")
    if positive and value <= 0.0:
        fail(f"used_row_{column}_not_positive")
    if not positive and value < 0.0:
        fail(f"used_row_{column}_negative")
    return value


def validate_snapshot(
    path: Path,
    *,
    summary: dict[str, Any],
    selected_date: pd.Timestamp,
    requested: list[str],
) -> tuple[
    dict[str, pd.DataFrame],
    dict[str, int],
    list[str],
    list[dict[str, Any]],
]:
    try:
        snapshot = pd.read_csv(path, dtype={"ticker": "string"})
    except Exception:
        fail("market_snapshot_csv_invalid")
    if snapshot.empty:
        fail("market_snapshot_empty")
    missing_columns = sorted(SNAPSHOT_COLUMNS - set(snapshot.columns))
    if missing_columns:
        fail("market_snapshot_columns_missing:" + ",".join(missing_columns))

    raw_tickers = snapshot["ticker"].fillna("").astype(str)
    normalized = raw_tickers.map(clean_ticker)
    if not raw_tickers.eq(normalized).all():
        fail("market_snapshot_ticker_not_canonical")
    if normalized.duplicated(keep=False).any():
        fail("market_snapshot_duplicate_ticker")
    snapshot = snapshot.copy()
    snapshot["ticker"] = normalized

    try:
        summary_count = int(summary.get("ticker_count"))
    except Exception:
        fail("market_snapshot_ticker_count_invalid")
    if summary_count != len(snapshot):
        fail("market_snapshot_ticker_count_mismatch")

    available = snapshot["price_available"].map(
        lambda value: strict_bool(value, "market_snapshot_price_available_invalid")
    )
    raw_dates = snapshot["latest_price_date"].fillna("").astype(str).str.strip()
    valid_date_format = raw_dates.str.fullmatch(r"\d{4}-\d{2}-\d{2}")
    if (available & ~valid_date_format).any():
        fail("market_snapshot_available_date_invalid")
    parsed_dates = pd.to_datetime(raw_dates.where(valid_date_format), errors="coerce")
    if (available & parsed_dates.isna()).any():
        fail("market_snapshot_available_date_missing")
    normalized_dates = parsed_dates.dt.normalize()
    if (normalized_dates > selected_date).fillna(False).any():
        fail("market_snapshot_future_date")
    actual_max = normalized_dates.max()
    if pd.isna(actual_max) or actual_max != selected_date:
        fail("market_snapshot_computed_max_date_mismatch")
    exact_mask = normalized_dates.eq(selected_date)
    required = requested or sorted(snapshot.loc[exact_mask, "ticker"].tolist())
    if not required:
        fail("exact_date_tickers_empty")

    for flag, code in (
        ("production_mutation_allowed", "market_snapshot_production_flag"),
        ("live_trading_enabled", "market_snapshot_live_trading_flag"),
    ):
        values = snapshot[flag].map(lambda value: strict_bool(value, f"{code}_invalid"))
        if values.any():
            fail(code)

    indexed = snapshot.set_index("ticker", drop=False)
    missing = sorted(set(required) - set(indexed.index))
    if missing:
        fail("required_ticker_missing:" + ",".join(missing))

    frames: dict[str, pd.DataFrame] = {}
    reference_ohlc_anomalies: list[dict[str, Any]] = []
    for ticker in required:
        row = indexed.loc[ticker]
        if not isinstance(row, pd.Series):
            fail(f"required_ticker_not_unique:{ticker}")
        if strict_bool(row["price_available"], "used_row_price_available_invalid") is not True:
            fail(f"required_ticker_price_missing:{ticker}")
        if nonblank(row.get("price_missing_reason")):
            fail(f"required_ticker_price_missing_reason:{ticker}")
        row_date = pd.to_datetime(row["latest_price_date"], errors="coerce")
        if pd.isna(row_date):
            fail(f"required_ticker_date_missing:{ticker}")
        row_date = pd.Timestamp(row_date).normalize()
        if row_date < selected_date:
            fail(f"required_ticker_stale:{ticker}")
        if row_date > selected_date:
            fail(f"required_ticker_future:{ticker}")

        open_value = numeric_value(row, "open", positive=True)
        high_value = numeric_value(row, "high", positive=True)
        low_value = numeric_value(row, "low", positive=True)
        close_value = numeric_value(row, "previous_close", positive=True)
        adjusted_value = numeric_value(row, "adjusted_close", positive=True)
        volume_value = numeric_value(row, "volume", positive=False)
        tolerance = max(abs(high_value), abs(low_value), 1.0) * 1e-10
        if high_value + tolerance < low_value:
            fail(f"required_ticker_high_below_low:{ticker}")
        if open_value > high_value + tolerance or open_value < low_value - tolerance:
            reference_ohlc_anomalies.append(
                {
                    "ticker": ticker,
                    "session_date": selected_date.date().isoformat(),
                    "code": "OPEN_OUTSIDE_LOW_HIGH",
                    "open": open_value,
                    "high": high_value,
                    "low": low_value,
                    "source_values_preserved": True,
                    "used_for_replay_mark_or_fill": False,
                }
            )
        if close_value > high_value + tolerance or close_value < low_value - tolerance:
            fail(f"required_ticker_close_outside_range:{ticker}")

        index = pd.DatetimeIndex([selected_date], name="Date")
        frames[ticker] = pd.DataFrame(
            {
                "Open": [open_value],
                "High": [high_value],
                "Low": [low_value],
                "Close": [close_value],
                "Adj Close": [adjusted_value],
                "Volume": [volume_value],
            },
            index=index,
        )

    return frames, {
        "source_row_count": int(len(snapshot)),
        "exact_date_source_row_count": int(exact_mask.sum()),
        "stale_source_row_count_excluded": int(
            (normalized_dates < selected_date).fillna(False).sum()
        ),
        "missing_date_source_row_count_excluded": int(parsed_dates.isna().sum()),
        "future_source_row_count": int(
            (normalized_dates > selected_date).fillna(False).sum()
        ),
    }, required, reference_ohlc_anomalies


def base_evidence(
    *,
    ingested_at: pd.Timestamp,
    artifact_root: Path,
    metadata_path: Path,
    selected_date_text: str,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": BLOCKED_STATUS,
        "contract_failures": [],
        "selected_session_date": selected_date_text,
        "artifact_root_name": artifact_root.name,
        "artifact_metadata_file": metadata_path.name,
        "ingested_at_utc": ingested_at.isoformat(),
        "replay_only": True,
        "forward_promotion_eligible": False,
        "review_only": True,
        "network_requests_executed": 0,
        "backtest_executed": False,
        "fullrun_executed": False,
        "orders_generated": False,
        "target_books_mutated": False,
        "production_mutation_allowed": False,
        "live_trading_enabled": False,
        "cache_materialized": False,
    }


def build(args: argparse.Namespace) -> dict[str, Any]:
    ingested_at = pd.Timestamp.now(tz="UTC")
    artifact_root = Path(args.artifact_root).resolve()
    metadata_path = Path(args.artifact_metadata).resolve()
    output_cache = Path(args.output_cache).resolve()
    output_evidence = Path(args.output_evidence).resolve()
    selected_text = str(args.session_date or "").strip()
    evidence = base_evidence(
        ingested_at=ingested_at,
        artifact_root=artifact_root,
        metadata_path=metadata_path,
        selected_date_text=selected_text,
    )

    try:
        if not artifact_root.is_dir():
            fail("artifact_root_missing")
        if output_cache == artifact_root or artifact_root in output_cache.parents:
            fail("output_cache_inside_artifact_root")
        if output_evidence == artifact_root or artifact_root in output_evidence.parents:
            fail("output_evidence_inside_artifact_root")
        if output_evidence == metadata_path:
            fail("output_evidence_overwrites_artifact_metadata")
        if output_evidence == output_cache or output_cache in output_evidence.parents:
            fail("output_evidence_inside_output_cache")
        if output_cache.exists() and (
            not output_cache.is_dir() or any(output_cache.iterdir())
        ):
            fail("output_cache_not_empty")

        selected_date = parse_session_date(selected_text, "selected_session_date_invalid")
        official_close = exact_nyse_close(selected_date)
        requested = requested_tickers(list(getattr(args, "ticker", []) or []))
        metadata = read_json_object(metadata_path, "artifact_metadata")
        artifact_identity, captured_at = validate_metadata(
            metadata,
            artifact_root=artifact_root,
        )
        run_id = str(artifact_identity["run_id"])
        artifact_name = str(artifact_identity["artifact_name"])

        source_paths, resolved_source_specs, source_layout = resolve_source_files(
            artifact_root=artifact_root,
            selected_date=selected_date,
            artifact_identity=artifact_identity,
            captured_at=captured_at,
            ingested_at=ingested_at,
        )
        source_specs = [
            (metadata_path, "artifact_metadata", metadata_path.name),
            *resolved_source_specs,
        ]
        sources_before = [
            fingerprint(path, label=label, relative_path=relative)
            for path, label, relative in source_specs
        ]

        gate = read_json_object(source_paths["market_session_gate"], "session_gate")
        summary = read_json_object(
            source_paths["market_snapshot_summary"],
            "market_snapshot_summary",
        )
        gate_checked_at = validate_gate(
            gate,
            selected_date=selected_date,
            official_close=official_close,
        )
        source_generated_at = validate_summary(
            summary,
            selected_date=selected_date,
            official_close=official_close,
            gate_checked_at=gate_checked_at,
            captured_at=captured_at,
            ingested_at=ingested_at,
        )
        (
            frames,
            counts,
            required,
            reference_ohlc_anomalies,
        ) = validate_snapshot(
            source_paths["market_snapshot_csv"],
            summary=summary,
            selected_date=selected_date,
            requested=requested,
        )
        sources = [
            fingerprint(path, label=label, relative_path=relative)
            for path, label, relative in source_specs
        ]
        if sources != sources_before:
            fail("artifact_source_changed_during_validation")

        output_cache.parent.mkdir(parents=True, exist_ok=True)
        if output_cache.exists():
            output_cache.rmdir()
        stage = Path(
            tempfile.mkdtemp(
                prefix=f".{output_cache.name}.",
                dir=str(output_cache.parent),
            )
        )
        try:
            file_records: list[dict[str, Any]] = []
            for ticker in required:
                filename = px_cache_name(ticker)
                destination = stage / filename
                frames[ticker].to_parquet(destination)
                verified = pd.read_parquet(destination)
                verified.index = pd.to_datetime(verified.index, errors="coerce")
                if (
                    len(verified) != 1
                    or pd.isna(verified.index[0])
                    or pd.Timestamp(verified.index[0]).normalize() != selected_date
                    or list(verified.columns)
                    != ["Open", "High", "Low", "Close", "Adj Close", "Volume"]
                ):
                    fail(f"materialized_parquet_verification:{ticker}")
                file_records.append(
                    {
                        "ticker": ticker,
                        "path": filename,
                        "rows": 1,
                        "session_date": selected_text,
                        "bytes": int(destination.stat().st_size),
                        "sha256": sha256_file(destination),
                        "reference_ohlc_anomaly_codes": sorted(
                            row["code"]
                            for row in reference_ohlc_anomalies
                            if row["ticker"] == ticker
                        ),
                    }
                )

            manifest = {
                "schema_version": MANIFEST_SCHEMA_VERSION,
                "status": READY_STATUS,
                "selected_session_date": selected_text,
                "official_market_close_utc": official_close.isoformat(),
                "source_generated_at_utc": source_generated_at.isoformat(),
                "artifact_captured_at_utc": (
                    captured_at.isoformat() if captured_at is not None else ""
                ),
                "ingested_at_utc": ingested_at.isoformat(),
                "artifact": artifact_identity,
                "source_layout": source_layout,
                "source_files": sources,
                "required_tickers": required,
                "ticker_selection_mode": (
                    "EXPLICIT_USED_TICKERS"
                    if requested
                    else "ALL_EXACT_SESSION_TICKERS"
                ),
                "ticker_count": len(required),
                "price_files": file_records,
                "price_usage_scope": (
                    "REPLAY_MARK_AND_NEXT_CLOSE_FILL_ONLY"
                ),
                "ohlc_execution_eligible": False,
                "reference_ohlc_anomaly_count": len(
                    reference_ohlc_anomalies
                ),
                "reference_ohlc_anomalies": (
                    reference_ohlc_anomalies
                ),
                **counts,
                "replay_only": True,
                "forward_promotion_eligible": False,
                "review_only": True,
                "network_requests_executed": 0,
                "backtest_executed": False,
                "fullrun_executed": False,
                "orders_generated": False,
                "target_books_mutated": False,
                "production_mutation_allowed": False,
                "live_trading_enabled": False,
            }
            write_json_atomic(stage / "manifest.json", manifest)
            os.replace(stage, output_cache)
        finally:
            if stage.exists():
                shutil.rmtree(stage)

        manifest_path = output_cache / "manifest.json"
        evidence.update(
            {
                "status": READY_STATUS,
                "selected_session_date": selected_text,
                "official_market_close_utc": official_close.isoformat(),
                "source_generated_at_utc": source_generated_at.isoformat(),
                "artifact_captured_at_utc": (
                    captured_at.isoformat() if captured_at is not None else ""
                ),
                "artifact": artifact_identity,
                "source_layout": source_layout,
                "required_tickers": required,
                "ticker_selection_mode": (
                    "EXPLICIT_USED_TICKERS"
                    if requested
                    else "ALL_EXACT_SESSION_TICKERS"
                ),
                "materialized_ticker_count": len(required),
                "price_usage_scope": (
                    "REPLAY_MARK_AND_NEXT_CLOSE_FILL_ONLY"
                ),
                "ohlc_execution_eligible": False,
                "reference_ohlc_anomaly_count": len(
                    reference_ohlc_anomalies
                ),
                "reference_ohlc_anomalies": (
                    reference_ohlc_anomalies
                ),
                **counts,
                "source_files": sources,
                "cache_manifest": fingerprint(
                    manifest_path,
                    label="cache_manifest",
                    relative_path="manifest.json",
                ),
                "cache_materialized": True,
            }
        )
    except ContractError as exc:
        evidence["contract_failures"] = [str(exc)]
    except Exception as exc:
        evidence["contract_failures"] = [f"unexpected:{type(exc).__name__}"]

    write_json_atomic(output_evidence, evidence)
    return evidence


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", required=True)
    parser.add_argument("--artifact-metadata", required=True)
    parser.add_argument("--session-date", required=True)
    parser.add_argument(
        "--ticker",
        action="append",
        default=[],
        help=(
            "Ticker used by the catch-up mark; repeat as needed. If omitted, "
            "all exact-session tickers are materialized."
        ),
    )
    parser.add_argument("--output-cache", required=True)
    parser.add_argument("--output-evidence", required=True)
    return parser.parse_args()


def main() -> int:
    payload = build(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if payload.get("status") == READY_STATUS else 2


if __name__ == "__main__":
    raise SystemExit(main())
