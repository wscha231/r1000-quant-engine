#!/usr/bin/env python3
"""Plan and build an immutable, read-only catch-up price capture.

The capture is derived from an integrity-verified canonical paper ledger and
its complete immutable-head chain.  It downloads nothing itself and never
mutates the supplied ledger, head chain, targets, orders, or accepted state.
The caller first creates a closed ticker/session plan, materializes a separate
price cache, then builds one exact-close snapshot per missing NYSE session.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import pandas_market_calendars as mcal

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.build_daily_market_snapshot import (  # noqa: E402
    build_rows,
    render_report,
    summarize,
)
from tools.run_daily_market_session_gate import (  # noqa: E402
    evaluate_market_session,
)
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402
from tools.run287_paper_ledger_integrity import (  # noqa: E402
    INTEGRITY_FILE,
    build_integrity_verifier_receipt,
    integrity_verifier_receipt_bytes,
    select_verified_immutable_paper_head,
)
from tools.validate_daily_close_prices import (  # noqa: E402
    collect_required_tickers,
)


PLAN_SCHEMA = "run287-catchup-price-capture-plan-v1"
PLAN_STATUS = "READY_RUN287_CATCHUP_PRICE_CAPTURE_PLAN"
CAPTURE_SCHEMA = "run287-catchup-price-capture-v1"
CAPTURE_STATUS = "READY_RUN287_CATCHUP_PRICE_CAPTURE"
PRICE_MANIFEST_SCHEMA = "run287-replay-price-cache-manifest-v2"
CAPTURE_ARTIFACT_ROOT = Path("outputs/run287_catchup_price_capture")
CAPTURE_ARTIFACT_ROOT_MARKER = Path(
    "run287_catchup_price_capture_artifact_root.json"
)
REQUIRED_BENCHMARKS = ("QQQ", "SMH", "SOXX", "SPY")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
RUN_ID_RE = re.compile(r"^[1-9][0-9]*$")
SAFETY_ENVELOPE = {
    "read_only": True,
    "replay_only": True,
    "forward_promotion_eligible": False,
    "network_requests_executed_by_capture_builder": 0,
    "drive_mutated": False,
    "ledger_mutated": False,
    "target_books_mutated": False,
    "orders_generated": False,
    "catchup_executed": False,
    "fullrun_executed": False,
    "production_mutation_allowed": False,
    "live_trading_enabled": False,
    "automatic_promotion_allowed": False,
}
PLAN_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "generated_at_utc",
        "canonical_as_of_date",
        "through_session_date",
        "pending_sessions",
        "pending_session_count",
        "ticker_union",
        "ticker_union_count",
        "ticker_sources",
        "ticker_book",
        "paper",
        *SAFETY_ENVELOPE,
    }
)
CAPTURE_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "generated_at_utc",
        "source",
        "canonical_as_of_date",
        "through_session_date",
        "pending_session_count",
        "ticker_union",
        "ticker_union_count",
        "ticker_sources",
        "paper",
        "capture_plan",
        "ticker_book",
        "source_price_cache_manifest",
        "source_price_cache_files",
        "artifact_root_marker",
        "sessions",
        *SAFETY_ENVELOPE,
    }
)
CAPTURE_SESSION_KEYS = frozenset(
    {"session_date", "official_market_close_utc", "ticker_count", "files"}
)
CAPTURE_SESSION_FILE_KEYS = frozenset(
    {
        "market_session_gate",
        "market_snapshot_csv",
        "market_snapshot_summary",
        "market_snapshot_report",
    }
)


class CaptureError(ValueError):
    """Stable fail-closed capture error."""


def fail(code: str) -> None:
    raise CaptureError(code)


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")


def strict_json_object(path: Path, code: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                fail(f"{code}_duplicate_key:{key}")
            result[key] = value
        return result

    try:
        payload = json.loads(
            regular_file_bytes(path, code),
            object_pairs_hook=reject_duplicates,
        )
    except CaptureError:
        raise
    except Exception:
        fail(f"{code}_invalid_json")
    if not isinstance(payload, dict):
        fail(f"{code}_not_object")
    return payload


def no_symlink_components(path: Path, code: str) -> Path:
    absolute = path.absolute()
    probe = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        probe = probe / part
        if probe.exists() or probe.is_symlink():
            try:
                mode = probe.lstat().st_mode
            except OSError:
                fail(f"{code}_unreadable")
            if stat.S_ISLNK(mode):
                fail(f"{code}_symlink")
    return absolute


def regular_file_bytes(path: Path, code: str) -> bytes:
    safe = no_symlink_components(path, code)
    try:
        mode = safe.lstat().st_mode
    except OSError:
        fail(f"{code}_missing")
    if not stat.S_ISREG(mode):
        fail(f"{code}_not_regular")
    try:
        return safe.read_bytes()
    except OSError:
        fail(f"{code}_unreadable")


def write_bytes_atomic(path: Path, raw: bytes) -> None:
    output = no_symlink_components(path, "output")
    output.parent.mkdir(parents=True, exist_ok=True)
    no_symlink_components(output.parent, "output_parent")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        no_symlink_components(output, "output")
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    write_bytes_atomic(path, canonical_json_bytes(payload))


def parse_session(value: Any, code: str) -> pd.Timestamp:
    text = str(value or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        fail(code)
    try:
        stamp = pd.Timestamp(text)
    except Exception:
        fail(code)
    if stamp.tzinfo is not None or stamp.strftime("%Y-%m-%d") != text:
        fail(code)
    return stamp.normalize()


def parse_utc(value: Any, code: str) -> pd.Timestamp:
    try:
        stamp = pd.Timestamp(str(value or ""))
    except Exception:
        fail(code)
    if pd.isna(stamp) or stamp.tzinfo is None:
        fail(code)
    return stamp.tz_convert("UTC")


def utc_now_text(value: str = "") -> str:
    stamp = parse_utc(value, "generated_at_invalid") if value else pd.Timestamp.now(tz="UTC")
    return stamp.isoformat()


def fingerprint(path: Path, *, relative_to: Path | None = None) -> dict[str, Any]:
    raw = regular_file_bytes(path, "fingerprint_source")
    label = (
        path.relative_to(relative_to).as_posix()
        if relative_to is not None
        else path.name
    )
    return {"path": label, "bytes": len(raw), "sha256": sha256_bytes(raw)}


def staged_session_fingerprint(path: Path, *, stage: Path) -> dict[str, Any]:
    result = fingerprint(path, relative_to=stage)
    result["path"] = (
        CAPTURE_ARTIFACT_ROOT / "sessions" / result["path"]
    ).as_posix()
    return result


def artifact_fingerprint(path: Path, relative: str) -> dict[str, Any]:
    result = fingerprint(path)
    result["path"] = (CAPTURE_ARTIFACT_ROOT / relative).as_posix()
    return result


def ensure_disjoint(output: Path, protected_roots: Iterable[Path]) -> None:
    candidate = output.absolute()
    for protected in protected_roots:
        root = protected.absolute()
        if candidate == root or root in candidate.parents or candidate in root.parents:
            fail("output_overlaps_protected_root")


def pending_sessions(
    accepted_asof: pd.Timestamp,
    through: pd.Timestamp,
) -> list[str]:
    if through <= accepted_asof:
        fail("through_session_not_after_canonical")
    schedule = mcal.get_calendar("NYSE").schedule(
        start_date=(accepted_asof + pd.Timedelta(days=1)).date(),
        end_date=through.date(),
    )
    sessions = [pd.Timestamp(value).date().isoformat() for value in schedule.index]
    if not sessions or sessions[-1] != through.date().isoformat():
        fail("through_date_not_nyse_session")
    if len(sessions) > 366:
        fail("pending_session_count_exceeds_bound")
    return sessions


def build_paper_identity(
    *,
    state_dir: Path,
    heads_root: Path,
    selection_path: Path,
    write_selection: bool,
) -> dict[str, Any]:
    selection = select_verified_immutable_paper_head(heads_root)
    if write_selection:
        write_json_atomic(selection_path, selection)
    supplied = strict_json_object(selection_path, "paper_selection")
    if supplied != selection:
        fail("paper_selection_mismatch")
    receipt = build_integrity_verifier_receipt(
        state_dir,
        immutable_head_selection=selection_path,
    )
    receipt_raw = integrity_verifier_receipt_bytes(receipt)
    manifest_raw = regular_file_bytes(
        state_dir / INTEGRITY_FILE, "paper_integrity_manifest"
    )
    raw = receipt["raw_manifest"]
    immutable = receipt["immutable_head_selection"]
    if (
        raw.get("sha256") != sha256_bytes(manifest_raw)
        or raw.get("snapshot_hash") != selection.get("selected_snapshot_hash")
        or immutable.get("terminal_snapshot_hash") != raw.get("snapshot_hash")
    ):
        fail("paper_identity_internal_mismatch")
    return {
        "canonical_manifest": {
            "sha256": sha256_bytes(manifest_raw),
            "bytes": len(manifest_raw),
            "schema_version": raw["schema_version"],
            "file_count": raw["file_count"],
            "files_sha256": raw["files_sha256"],
            "as_of_date": raw["as_of_date"],
            "snapshot_hash": raw["snapshot_hash"],
            "previous_snapshot_hash": raw["previous_snapshot_hash"],
            "genesis_identity_sha256": raw["genesis_identity_sha256"],
        },
        "immutable_heads": {
            "selection_sha256": sha256_file(selection_path),
            "selection_bytes": selection_path.stat().st_size,
            "verifier_receipt_sha256": sha256_bytes(receipt_raw),
            "verifier_receipt_bytes": len(receipt_raw),
            "head_count": immutable["immutable_head_count"],
            "root_snapshot_hash": immutable["root_snapshot_hash"],
            "terminal_snapshot_hash": immutable["terminal_snapshot_hash"],
            "chain_snapshot_hashes": immutable["chain_snapshot_hashes"],
        },
    }


def plan_payload(args: argparse.Namespace) -> dict[str, Any]:
    state_dir = Path(args.state_dir).absolute()
    heads_root = Path(args.heads_root).absolute()
    plan_output = Path(args.plan_output).absolute()
    ticker_book = Path(args.ticker_book).absolute()
    selection_path = Path(args.selection_output).absolute()
    for output in (plan_output, ticker_book, selection_path):
        ensure_disjoint(output, (state_dir, heads_root))
    through = parse_session(args.through_session_date, "through_session_invalid")
    now = parse_utc(args.generated_at_utc, "generated_at_invalid") if args.generated_at_utc else pd.Timestamp.now(tz="UTC")
    through_schedule = mcal.get_calendar("NYSE").schedule(
        start_date=through.date(), end_date=through.date()
    )
    if len(through_schedule) != 1:
        fail("through_date_not_nyse_session")
    through_close = pd.Timestamp(through_schedule.iloc[0]["market_close"])
    through_close = through_close.tz_localize("UTC") if through_close.tzinfo is None else through_close.tz_convert("UTC")
    if now < through_close + pd.Timedelta(minutes=90):
        fail("through_session_close_not_settled")

    paper = build_paper_identity(
        state_dir=state_dir,
        heads_root=heads_root,
        selection_path=selection_path,
        write_selection=True,
    )
    accepted_asof = parse_session(
        paper["canonical_manifest"]["as_of_date"], "canonical_asof_invalid"
    )
    sessions = pending_sessions(accepted_asof, through)
    targets = [
        state_dir / portfolio / "effective_target_latest.csv"
        for portfolio in ("main", "concentrated")
    ]
    tickers, ticker_sources = collect_required_tickers(
        targets=targets,
        accounts=[],
        state_dir=state_dir,
        required_tickers=REQUIRED_BENCHMARKS,
        session_date=through,
    )
    ordered_tickers = sorted(tickers)
    if not ordered_tickers:
        fail("ticker_union_empty")
    ticker_book.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"ticker": ordered_tickers}).to_csv(ticker_book, index=False)
    payload = {
        "schema_version": PLAN_SCHEMA,
        "status": PLAN_STATUS,
        "generated_at_utc": now.isoformat(),
        "canonical_as_of_date": accepted_asof.date().isoformat(),
        "through_session_date": through.date().isoformat(),
        "pending_sessions": sessions,
        "pending_session_count": len(sessions),
        "ticker_union": ordered_tickers,
        "ticker_union_count": len(ordered_tickers),
        "ticker_sources": ticker_sources,
        "ticker_book": fingerprint(ticker_book),
        "paper": paper,
        **SAFETY_ENVELOPE,
    }
    write_json_atomic(plan_output, payload)
    return payload


def require_plan_shape(plan: dict[str, Any]) -> None:
    if (
        set(plan) != PLAN_KEYS
        or plan.get("schema_version") != PLAN_SCHEMA
        or plan.get("status") != PLAN_STATUS
    ):
        fail("capture_plan_schema")
    for key, expected in SAFETY_ENVELOPE.items():
        if plan.get(key) is not expected and plan.get(key) != expected:
            fail(f"capture_plan_safety:{key}")


def verify_price_cache(
    *,
    price_cache: Path,
    tickers: list[str],
    through_session: str,
) -> tuple[dict[str, Any], bytes]:
    manifest_path = price_cache / "replay_price_cache_manifest.json"
    manifest_raw = regular_file_bytes(manifest_path, "price_cache_manifest")
    manifest = strict_json_object(manifest_path, "price_cache_manifest")
    cache_files = manifest.get("cache_files")
    if (
        manifest.get("schema_version") != PRICE_MANIFEST_SCHEMA
        or manifest.get("status") not in {"completed", "already_cached"}
        or manifest.get("review_only") is not True
        or manifest.get("production_mutation_allowed") is not False
        or manifest.get("live_trading_enabled") is not False
        or manifest.get("exact_operating_universe") is not True
        or manifest.get("refresh_through_date") != through_session
        or manifest.get("refresh_through_exact_coverage") is not True
        or manifest.get("refresh_through_ticker_count") != len(tickers)
        or manifest.get("refresh_through_exact_ticker_count") != len(tickers)
        or not isinstance(cache_files, dict)
        or sorted(cache_files) != tickers
    ):
        fail("price_cache_manifest_contract")
    expected_files: set[str] = set()
    for ticker in tickers:
        entry = cache_files.get(ticker)
        filename = px_cache_name(ticker)
        if (
            not isinstance(entry, dict)
            or set(entry) != {"file", "sha256", "bytes"}
            or entry.get("file") != filename
            or not SHA256_RE.fullmatch(str(entry.get("sha256") or ""))
            or not isinstance(entry.get("bytes"), int)
            or isinstance(entry.get("bytes"), bool)
            or entry["bytes"] <= 0
        ):
            fail(f"price_cache_file_record:{ticker}")
        path = price_cache / filename
        raw = regular_file_bytes(path, f"price_cache_file:{ticker}")
        if len(raw) != entry["bytes"] or sha256_bytes(raw) != entry["sha256"]:
            fail(f"price_cache_file_hash:{ticker}")
        expected_files.add(filename)
    actual_parquet = {
        path.name
        for path in price_cache.glob("*.parquet")
        if path.is_file() and not path.is_symlink()
    }
    if actual_parquet != expected_files:
        fail("price_cache_unexpected_parquet_set")
    return manifest, manifest_raw


def validate_source_identity(args: argparse.Namespace) -> dict[str, str]:
    repository = str(args.repository or "").strip()
    source_sha = str(args.source_sha or "").strip().lower()
    run_id = str(args.run_id or "").strip()
    run_attempt = str(args.run_attempt or "").strip()
    event_name = str(args.event_name or "").strip()
    job_key = str(args.job_key or "").strip()
    if (
        not repository
        or not SHA1_RE.fullmatch(source_sha)
        or not RUN_ID_RE.fullmatch(run_id)
        or run_attempt != "1"
        or event_name != "workflow_dispatch"
        or job_key != "capture_catchup_evidence"
    ):
        fail("source_identity_invalid")
    return {
        "repository": repository,
        "source_sha": source_sha,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "event_name": event_name,
        "job_key": job_key,
    }


def validate_session_snapshot(
    snapshot: pd.DataFrame,
    *,
    tickers: list[str],
    session_text: str,
) -> None:
    required_columns = {
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
    if len(snapshot) != len(tickers) or not required_columns.issubset(snapshot):
        fail(f"session_snapshot_contract:{session_text}")
    observed = snapshot["ticker"].fillna("").astype(str).tolist()
    if observed != tickers or len(set(observed)) != len(observed):
        fail(f"session_snapshot_tickers:{session_text}")
    for row in snapshot.to_dict("records"):
        ticker = str(row["ticker"])
        if (
            bool(row["price_available"]) is not True
            or str(row.get("price_missing_reason") or "")
            or str(row.get("latest_price_date") or "") != session_text
            or bool(row["production_mutation_allowed"]) is not False
            or bool(row["live_trading_enabled"]) is not False
        ):
            fail(f"session_snapshot_row:{session_text}:{ticker}")
        try:
            open_value = float(row["open"])
            high_value = float(row["high"])
            low_value = float(row["low"])
            close_value = float(row["previous_close"])
            adjusted_value = float(row["adjusted_close"])
            volume_value = float(row["volume"])
        except Exception:
            fail(f"session_snapshot_numeric:{session_text}:{ticker}")
        values = (
            open_value,
            high_value,
            low_value,
            close_value,
            adjusted_value,
            volume_value,
        )
        tolerance = max(abs(high_value), abs(low_value), 1.0) * 1e-10
        if (
            not all(math.isfinite(value) for value in values)
            or min(
                open_value,
                high_value,
                low_value,
                close_value,
                adjusted_value,
            )
            <= 0.0
            or volume_value < 0.0
            or high_value + tolerance < low_value
            or close_value > high_value + tolerance
            or close_value < low_value - tolerance
        ):
            fail(f"session_snapshot_numeric:{session_text}:{ticker}")


def build_capture(args: argparse.Namespace) -> dict[str, Any]:
    state_dir = Path(args.state_dir).absolute()
    heads_root = Path(args.heads_root).absolute()
    selection_path = Path(args.selection).absolute()
    plan_path = Path(args.plan).absolute()
    ticker_book = Path(args.ticker_book).absolute()
    price_cache = Path(args.price_cache).absolute()
    output_root = Path(args.output_root).absolute()
    artifact_root_marker = Path(args.artifact_root_marker).absolute()
    ensure_disjoint(output_root, (state_dir, heads_root, price_cache))
    ensure_disjoint(artifact_root_marker, (state_dir, heads_root, price_cache))
    if output_root in artifact_root_marker.parents or artifact_root_marker in output_root.parents:
        fail("artifact_root_marker_overlaps_capture_root")
    plan_raw_before = regular_file_bytes(plan_path, "capture_plan")
    plan = strict_json_object(plan_path, "capture_plan")
    require_plan_shape(plan)
    if plan.get("ticker_book") != fingerprint(ticker_book):
        fail("ticker_book_mismatch")
    tickers = plan.get("ticker_union")
    sessions = plan.get("pending_sessions")
    if (
        not isinstance(tickers, list)
        or tickers != sorted(set(str(value) for value in tickers))
        or plan.get("ticker_union_count") != len(tickers)
        or not isinstance(sessions, list)
        or sessions != pending_sessions(
            parse_session(plan["canonical_as_of_date"], "canonical_asof_invalid"),
            parse_session(plan["through_session_date"], "through_session_invalid"),
        )
        or plan.get("pending_session_count") != len(sessions)
    ):
        fail("capture_plan_content")
    paper = build_paper_identity(
        state_dir=state_dir,
        heads_root=heads_root,
        selection_path=selection_path,
        write_selection=False,
    )
    if paper != plan.get("paper"):
        fail("paper_state_changed_after_plan")
    price_manifest, price_manifest_raw = verify_price_cache(
        price_cache=price_cache,
        tickers=tickers,
        through_session=plan["through_session_date"],
    )
    if regular_file_bytes(plan_path, "capture_plan") != plan_raw_before:
        fail("capture_plan_changed_during_validation")
    identity = validate_source_identity(args)
    generated_at = utc_now_text(args.generated_at_utc)
    now_stamp = parse_utc(generated_at, "generated_at_invalid")

    output_root.mkdir(parents=True, exist_ok=True)
    sessions_destination = output_root / "sessions"
    if sessions_destination.exists() or sessions_destination.is_symlink():
        fail("capture_sessions_destination_exists")
    stage = Path(
        tempfile.mkdtemp(
            prefix=".run287-catchup-price-sessions-",
            dir=output_root.parent,
        )
    )
    session_records: list[dict[str, Any]] = []
    source_sets = {
        ticker: set(
            source
            for source, source_tickers in plan["ticker_sources"].items()
            if ticker in source_tickers
        )
        for ticker in tickers
    }
    try:
        for session_text in sessions:
            session = parse_session(session_text, "pending_session_invalid")
            gate = evaluate_market_session(
                now_utc=now_stamp,
                force=True,
                session_date=session_text,
                min_close_age_minutes=90,
                max_close_age_hours=18.0,
            )
            if (
                gate.get("ready") is not True
                or gate.get("session_date") != session_text
                or gate.get("calendar") != "NYSE"
            ):
                fail(f"session_gate_not_ready:{session_text}")
            session_root = stage / session_text / "outputs"
            gate_path = session_root / "daily_market_session_gate" / "session.json"
            write_json_atomic(gate_path, gate)
            snapshot_dir = session_root / "daily_market_snapshot"
            snapshot = build_rows(
                tickers=tickers,
                sources=source_sets,
                price_cache=price_cache,
                info=pd.DataFrame(columns=["ticker"]),
                benchmark_tickers=set(REQUIRED_BENCHMARKS),
                today=session.date(),
            )
            snapshot["price_cache_path"] = snapshot["ticker"].map(
                lambda ticker: (
                    Path("source_price_cache") / px_cache_name(str(ticker))
                ).as_posix()
            )
            official_snapshot_dir = (
                CAPTURE_ARTIFACT_ROOT
                / "sessions"
                / session_text
                / "outputs/daily_market_snapshot"
            )
            summary = summarize(
                snapshot,
                output_dir=official_snapshot_dir,
                data_lake_dir=official_snapshot_dir / "unused_data_lake",
                asof=session.date(),
                require_exact_asof_close=True,
                generated_at=now_stamp,
            )
            if (
                summary.get("status") != "completed"
                or summary.get("exact_asof_close_count") != len(tickers)
                or summary.get("exact_asof_close_missing_tickers") != []
                or summary.get("latest_price_date_min") != session_text
                or summary.get("latest_price_date_max") != session_text
            ):
                missing = ",".join(summary.get("exact_asof_close_missing_tickers") or [])
                fail(f"exact_session_price_coverage:{session_text}:{missing}")
            validate_session_snapshot(
                snapshot,
                tickers=tickers,
                session_text=session_text,
            )
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            snapshot_path = snapshot_dir / "market_snapshot.csv"
            summary_path = snapshot_dir / "summary.json"
            report_path = snapshot_dir / "report.md"
            snapshot.to_csv(snapshot_path, index=False)
            write_json_atomic(summary_path, summary)
            write_bytes_atomic(report_path, render_report(summary).encode("utf-8"))
            session_records.append(
                {
                    "session_date": session_text,
                    "official_market_close_utc": gate["market_close_utc"],
                    "ticker_count": len(tickers),
                    "files": {
                        "market_session_gate": staged_session_fingerprint(
                            gate_path, stage=stage
                        ),
                        "market_snapshot_csv": staged_session_fingerprint(
                            snapshot_path, stage=stage
                        ),
                        "market_snapshot_summary": staged_session_fingerprint(
                            summary_path, stage=stage
                        ),
                        "market_snapshot_report": staged_session_fingerprint(
                            report_path, stage=stage
                        ),
                    },
                }
            )
        os.replace(stage, sessions_destination)
    finally:
        if stage.exists():
            shutil.rmtree(stage)

    source_manifest_path = output_root / "source_price_cache_manifest.json"
    write_bytes_atomic(source_manifest_path, price_manifest_raw)
    if regular_file_bytes(source_manifest_path, "source_price_manifest_copy") != price_manifest_raw:
        fail("source_price_manifest_copy_mismatch")
    marker_payload = {
        "schema_version": "run287-catchup-price-capture-artifact-root-v1",
        "capture_manifest_path": (
            CAPTURE_ARTIFACT_ROOT / "manifest.json"
        ).as_posix(),
        "repository": identity["repository"],
        "source_sha": identity["source_sha"],
        "run_id": identity["run_id"],
        "read_only": True,
        "production_mutation_allowed": False,
        "live_trading_enabled": False,
    }
    write_json_atomic(artifact_root_marker, marker_payload)
    payload = {
        "schema_version": CAPTURE_SCHEMA,
        "status": CAPTURE_STATUS,
        "generated_at_utc": generated_at,
        "source": identity,
        "canonical_as_of_date": plan["canonical_as_of_date"],
        "through_session_date": plan["through_session_date"],
        "pending_session_count": len(session_records),
        "ticker_union": tickers,
        "ticker_union_count": len(tickers),
        "ticker_sources": plan["ticker_sources"],
        "paper": paper,
        "capture_plan": artifact_fingerprint(plan_path, "plan.json"),
        "ticker_book": artifact_fingerprint(ticker_book, "ticker_union.csv"),
        "source_price_cache_manifest": artifact_fingerprint(
            source_manifest_path, "source_price_cache_manifest.json"
        ),
        "source_price_cache_files": price_manifest["cache_files"],
        "artifact_root_marker": {
            **fingerprint(artifact_root_marker),
            "path": CAPTURE_ARTIFACT_ROOT_MARKER.as_posix(),
        },
        "sessions": session_records,
        **SAFETY_ENVELOPE,
    }
    if set(payload) != CAPTURE_MANIFEST_KEYS:
        fail("capture_manifest_internal_schema")
    write_json_atomic(output_root / "manifest.json", payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan = subparsers.add_parser("plan")
    plan.add_argument("--state-dir", required=True)
    plan.add_argument("--heads-root", required=True)
    plan.add_argument("--through-session-date", required=True)
    plan.add_argument("--selection-output", required=True)
    plan.add_argument("--ticker-book", required=True)
    plan.add_argument("--plan-output", required=True)
    plan.add_argument("--generated-at-utc", default="")

    build = subparsers.add_parser("build")
    build.add_argument("--state-dir", required=True)
    build.add_argument("--heads-root", required=True)
    build.add_argument("--selection", required=True)
    build.add_argument("--plan", required=True)
    build.add_argument("--ticker-book", required=True)
    build.add_argument("--price-cache", required=True)
    build.add_argument("--output-root", required=True)
    build.add_argument("--artifact-root-marker", required=True)
    build.add_argument("--repository", required=True)
    build.add_argument("--source-sha", required=True)
    build.add_argument("--run-id", required=True)
    build.add_argument("--run-attempt", required=True)
    build.add_argument("--event-name", required=True)
    build.add_argument("--job-key", required=True)
    build.add_argument("--generated-at-utc", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        payload = plan_payload(args) if args.command == "plan" else build_capture(args)
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "reason": f"{type(exc).__name__}:{exc}"}, indent=2))
        return 2
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
