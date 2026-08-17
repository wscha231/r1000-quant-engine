#!/usr/bin/env python3
"""Build immutable, review-only price evidence for a stalled Run287 catch-up.

This tool never downloads data and never mutates an accepted paper state.  It
binds three independently supplied inputs: a verified accepted paper snapshot,
a fresh one-session OHLCV cache, and a pinned After-Close research artifact.
Every ticker required by the accepted targets, positions, pending orders, and
benchmarks must have one exact-session bar.  The After-Close artifact is only a
cross-source anchor; missing anchor rows never substitute for missing prices.
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
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

import pandas as pd
import pandas_market_calendars as mcal


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run287_paper_ledger_integrity import (  # noqa: E402
    verify_integrity_manifest,
)
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402
from tools.validate_daily_close_prices import (  # noqa: E402
    collect_required_tickers,
)


CONTRACT_SCHEMA = "run287-recovery-price-evidence-contract-v1"
SCHEMA_VERSION = "run287-recovery-price-evidence-v1"
READY_STATUS = "READY_REVIEW_ONLY_RECOVERY_PRICE_EVIDENCE"
BLOCKED_STATUS = "BLOCKED_RECOVERY_PRICE_EVIDENCE"
METADATA_SCHEMA = "github-artifact-download-metadata-v3"
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
RUN_ID_RE = re.compile(r"^[1-9][0-9]*$")
TICKER_RE = re.compile(r"^[A-Z0-9.^=-]+$")
ARTIFACT_METADATA_KEYS = frozenset(
    {
        "schema_version",
        "role",
        "run_id",
        "artifact_id",
        "artifact_name",
        "artifact_zip_sha256",
        "artifact_api_digest",
        "artifact_created_at_utc",
        "downloaded_at_utc",
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
        "head_lineage_verified",
    }
)
PRICE_COLUMNS = ("Open", "High", "Low", "Close", "Adj Close", "Volume")
PORTFOLIOS = ("main", "concentrated")


class ContractError(ValueError):
    """Stable fail-closed validation error."""


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


def read_json(path: Path, code: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        fail(f"{code}_missing_or_unsafe")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        fail(f"{code}_invalid_json")
    if not isinstance(payload, dict):
        fail(f"{code}_not_object")
    return payload


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    staged.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(staged, path)


def parse_utc(value: Any, code: str) -> pd.Timestamp:
    try:
        stamp = pd.Timestamp(str(value or "").strip())
    except Exception:
        fail(code)
    if pd.isna(stamp) or stamp.tzinfo is None:
        fail(code)
    return stamp.tz_convert("UTC")


def parse_session(value: Any, code: str) -> pd.Timestamp:
    text = str(value or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        fail(code)
    try:
        stamp = pd.Timestamp(text).normalize()
    except Exception:
        fail(code)
    if stamp.date().isoformat() != text:
        fail(code)
    schedule = mcal.get_calendar("NYSE").schedule(
        start_date=stamp.date(), end_date=stamp.date()
    )
    if len(schedule) != 1:
        fail("selected_date_not_nyse_session")
    return stamp


def clean_ticker(value: Any) -> str:
    ticker = str(value or "").strip().upper()
    if ticker in {"", "NAN", "NONE", "CASH"}:
        return ""
    if not TICKER_RE.fullmatch(ticker):
        fail("invalid_ticker")
    return ticker


def strict_bool(value: Any, code: str) -> bool:
    if isinstance(value, bool):
        return value
    fail(code)


def finite_number(value: Any, code: str, *, positive: bool = False) -> float:
    try:
        number = float(value)
    except Exception:
        fail(code)
    if not math.isfinite(number) or (positive and number <= 0.0):
        fail(code)
    return number


def load_contract(path: Path) -> dict[str, Any]:
    contract = read_json(path, "contract")
    if contract.get("schema_version") != CONTRACT_SCHEMA:
        fail("contract_schema")
    if contract.get("output_schema_version") != SCHEMA_VERSION:
        fail("contract_output_schema")
    if contract.get("required_status") != READY_STATUS:
        fail("contract_status")
    safety = contract.get("safety")
    if not isinstance(safety, dict) or safety != {
        "review_only": True,
        "catchup_consumption_allowed": False,
        "network_allowed_only_in_manual_evidence_workflow": True,
        "backtest_allowed": False,
        "fullrun_allowed": False,
        "orders_allowed": False,
        "target_book_mutation_allowed": False,
        "paper_ledger_mutation_allowed": False,
        "durable_state_mutation_allowed": False,
        "production_mutation_allowed": False,
        "live_trading_allowed": False,
        "automatic_promotion_allowed": False,
    }:
        fail("contract_safety")
    return contract


def validate_metadata(
    metadata: dict[str, Any],
    *,
    role: str,
    contract: dict[str, Any],
) -> dict[str, Any]:
    if metadata.get("schema_version") != METADATA_SCHEMA:
        fail(f"{role}_metadata_schema")
    if set(metadata) != ARTIFACT_METADATA_KEYS or metadata.get("role") != role:
        fail(f"{role}_metadata_shape")
    role_contract = (
        contract["after_close_anchor"]
        if role == "after_close"
        else contract["accepted_paper"]
    )
    for key in ("run_id", "artifact_id", "workflow_id", "workflow_run_attempt"):
        if not RUN_ID_RE.fullmatch(str(metadata.get(key) or "")):
            fail(f"{role}_{key}_invalid")
    run_id = str(metadata.get("run_id") or "")
    artifact_name = str(metadata.get("artifact_name") or "")
    if not re.fullmatch(str(role_contract["artifact_name_pattern"]), artifact_name):
        fail(f"{role}_artifact_name")
    if not artifact_name.endswith(f"-{run_id}"):
        fail(f"{role}_artifact_run_id_parity")
    zip_digest = str(metadata.get("artifact_zip_sha256") or "").lower()
    if not SHA256_RE.fullmatch(zip_digest):
        fail(f"{role}_zip_sha256")
    if metadata.get("artifact_api_digest") != f"sha256:{zip_digest}":
        fail(f"{role}_artifact_digest_parity")
    repository = str(contract["repository"])
    default_branch = str(contract["default_branch"])
    if (
        metadata.get("repository") != repository
        or metadata.get("head_repository") != repository
        or metadata.get("default_branch") != default_branch
        or metadata.get("head_branch") != default_branch
        or metadata.get("workflow_path") != role_contract["workflow_path"]
        or metadata.get("workflow_event") not in {"schedule", "workflow_dispatch"}
        or metadata.get("workflow_status") != "completed"
        or metadata.get("workflow_conclusion") != "success"
        or metadata.get("head_lineage_verified") is not True
    ):
        fail(f"{role}_workflow_identity")
    for key in ("head_sha", "current_default_head_sha"):
        if not SHA1_RE.fullmatch(str(metadata.get(key) or "")):
            fail(f"{role}_{key}_invalid")
    workflow_created = parse_utc(
        metadata.get("workflow_created_at_utc"), f"{role}_workflow_created_at"
    )
    workflow_updated = parse_utc(
        metadata.get("workflow_updated_at_utc"), f"{role}_workflow_updated_at"
    )
    artifact_created = parse_utc(
        metadata.get("artifact_created_at_utc"), f"{role}_artifact_created_at"
    )
    downloaded_at = parse_utc(
        metadata.get("downloaded_at_utc"), f"{role}_downloaded_at"
    )
    if not (
        workflow_created <= artifact_created <= downloaded_at
        and workflow_created <= workflow_updated <= downloaded_at
    ):
        fail(f"{role}_time_order")
    return {
        key: metadata[key]
        for key in (
            "run_id",
            "artifact_id",
            "artifact_name",
            "artifact_api_digest",
            "workflow_id",
            "workflow_path",
            "head_sha",
            "workflow_event",
            "repository",
            "current_default_head_sha",
        )
    }


def validate_archive(path: Path, metadata: dict[str, Any], role: str) -> None:
    if not path.is_file() or path.is_symlink():
        fail(f"{role}_archive_missing_or_unsafe")
    if sha256_file(path) != metadata.get("artifact_zip_sha256"):
        fail(f"{role}_archive_digest")
    try:
        with zipfile.ZipFile(path) as archive:
            seen: set[str] = set()
            total_uncompressed = 0
            for info in archive.infolist():
                name = info.filename
                member = PurePosixPath(name)
                mode = info.external_attr >> 16
                if (
                    not name
                    or "\\" in name
                    or member.is_absolute()
                    or any(part in {"", ".", ".."} for part in member.parts)
                    or name in seen
                    or stat.S_ISLNK(mode)
                ):
                    fail(f"{role}_archive_member_unsafe")
                seen.add(name)
                total_uncompressed += int(info.file_size)
            if not seen or total_uncompressed > 1_000_000_000:
                fail(f"{role}_archive_size")
    except ContractError:
        raise
    except Exception:
        fail(f"{role}_archive_invalid")


def verify_archive_member(
    archive_path: Path,
    *,
    member_suffix: str,
    extracted_path: Path,
    code: str,
) -> None:
    suffix = member_suffix.replace("\\", "/").lstrip("/")
    try:
        with zipfile.ZipFile(archive_path) as archive:
            matches = [
                info
                for info in archive.infolist()
                if not info.is_dir()
                and (
                    info.filename.replace("\\", "/").lstrip("/") == suffix
                    or info.filename.replace("\\", "/").lstrip("/").endswith(
                        "/" + suffix
                    )
                )
            ]
            if len(matches) != 1:
                fail(f"{code}_archive_member_count")
            archived_hash = hashlib.sha256(archive.read(matches[0])).hexdigest()
    except ContractError:
        raise
    except Exception:
        fail(f"{code}_archive_member_invalid")
    if archived_hash != sha256_file(extracted_path):
        fail(f"{code}_archive_member_hash")


def verify_paper_state_archive(
    archive_path: Path,
    *,
    state: Path,
    integrity: dict[str, Any],
) -> None:
    prefix = "outputs/daily_simulated_fill_ledger/"
    verify_archive_member(
        archive_path,
        member_suffix=prefix + "snapshot_integrity.json",
        extracted_path=state / "snapshot_integrity.json",
        code="accepted_paper_integrity",
    )
    files = integrity.get("files")
    if not isinstance(files, dict) or not files:
        fail("accepted_paper_integrity_files")
    for relative, expected_hash in sorted(files.items()):
        path = state / str(relative)
        if not path.is_file() or path.is_symlink():
            fail("accepted_paper_archive_file_missing")
        verify_archive_member(
            archive_path,
            member_suffix=prefix + str(relative),
            extracted_path=path,
            code="accepted_paper_file",
        )
        if expected_hash != sha256_file(path):
            fail("accepted_paper_integrity_file_hash")


def safe_source(root: Path, relative: str, code: str) -> Path:
    path = root / relative
    if not path.is_file() or path.is_symlink() or root not in path.resolve().parents:
        fail(code)
    return path


def validate_paper_state(
    state: Path,
    *,
    session: pd.Timestamp,
    contract: dict[str, Any],
) -> tuple[dict[str, Any], list[str], list[str], dict[str, list[str]]]:
    if not state.is_dir() or state.is_symlink():
        fail("accepted_paper_state_missing_or_unsafe")
    try:
        integrity = verify_integrity_manifest(state, require=True)
    except Exception as exc:
        fail(f"accepted_paper_integrity:{type(exc).__name__}")
    if integrity.get("schema_version") != contract["accepted_paper"][
        "required_integrity_schema"
    ]:
        fail("accepted_paper_integrity_schema")
    paper_as_of = parse_session(integrity.get("as_of_date"), "accepted_paper_as_of")
    if paper_as_of >= session:
        fail("accepted_paper_not_prior_to_recovery_session")
    summary = read_json(state / "summary.json", "accepted_paper_summary")
    if (
        summary.get("as_of_date") != paper_as_of.date().isoformat()
        or strict_bool(summary.get("review_only"), "accepted_summary_review_only")
        is not True
        or strict_bool(
            summary.get("production_mutation_allowed"),
            "accepted_summary_production_flag",
        )
        is not False
        or strict_bool(
            summary.get("live_trading_enabled"), "accepted_summary_live_flag"
        )
        is not False
    ):
        fail("accepted_paper_summary_contract")

    targets: list[Path] = []
    accounts: list[Path] = []
    for portfolio in PORTFOLIOS:
        manifest = read_json(state / portfolio / "manifest.json", f"{portfolio}_manifest")
        account = read_json(
            state / portfolio / "account_state_latest.json", f"{portfolio}_account"
        )
        target = state / portfolio / "effective_target_latest.csv"
        if not target.is_file() or target.is_symlink():
            fail(f"{portfolio}_target_missing_or_unsafe")
        for payload, label in ((manifest, "manifest"), (account, "account")):
            if (
                payload.get("as_of_date") != paper_as_of.date().isoformat()
                or payload.get("review_only") is not True
                or payload.get("production_mutation_allowed") is not False
                or payload.get("live_trading_enabled") is not False
            ):
                fail(f"{portfolio}_{label}_safety_contract")
        targets.append(target)
        accounts.append(state / portfolio / "account_state_latest.json")

    benchmarks = [clean_ticker(value) for value in contract["price_cache"][
        "required_benchmark_tickers"
    ]]
    if not all(benchmarks) or len(benchmarks) != len(set(benchmarks)):
        fail("contract_benchmark_tickers")
    required, sources = collect_required_tickers(
        targets=targets,
        accounts=accounts,
        state_dir=state,
        required_tickers=benchmarks,
        session_date=session,
    )
    if not required:
        fail("accepted_operating_tickers_empty")
    operating = sorted(required - set(benchmarks))
    if not operating:
        fail("accepted_operating_equities_empty")
    return integrity, sorted(required), operating, sources


def validate_price_cache(
    price_cache: Path,
    *,
    session: pd.Timestamp,
    required: list[str],
    contract: dict[str, Any],
) -> tuple[dict[str, dict[str, float]], dict[str, Any], list[dict[str, Any]]]:
    manifest_path = price_cache / "replay_price_cache_manifest.json"
    manifest = read_json(manifest_path, "price_cache_manifest")
    cache_contract = contract["price_cache"]
    if (
        manifest.get("schema_version") != cache_contract["required_manifest_schema"]
        or manifest.get("review_only") is not True
        or manifest.get("production_mutation_allowed") is not False
        or manifest.get("live_trading_enabled") is not False
        or manifest.get("exact_operating_universe") is not True
        or manifest.get("refresh_through_exact_coverage") is not True
        or manifest.get("refresh_through_date") != session.date().isoformat()
        or manifest.get("common_coverage_end") != session.date().isoformat()
        or manifest.get("end") != session.date().isoformat()
    ):
        fail("price_cache_manifest_contract")
    cache_files = manifest.get("cache_files")
    if not isinstance(cache_files, dict):
        fail("price_cache_files_contract")
    actual_tickers = {clean_ticker(value) for value in cache_files}
    if "" in actual_tickers:
        fail("price_cache_ticker_invalid")
    required_set = set(required)
    missing = sorted(required_set - actual_tickers)
    extra = sorted(actual_tickers - required_set)
    if missing:
        fail("price_cache_missing_required:" + ",".join(missing))
    if extra and cache_contract.get("extra_tickers_allowed") is not True:
        fail("price_cache_extra_tickers:" + ",".join(extra))

    values: dict[str, dict[str, float]] = {}
    files: list[dict[str, Any]] = []
    for ticker in required:
        record = cache_files.get(ticker)
        if not isinstance(record, dict):
            fail(f"price_cache_record:{ticker}")
        filename = px_cache_name(ticker)
        path = price_cache / filename
        if (
            record.get("file") != filename
            or not path.is_file()
            or path.is_symlink()
            or price_cache not in path.resolve().parents
            or record.get("sha256") != sha256_file(path)
            or int(record.get("bytes", -1)) != path.stat().st_size
        ):
            fail(f"price_cache_file_identity:{ticker}")
        try:
            frame = pd.read_parquet(path)
        except Exception:
            fail(f"price_cache_parquet:{ticker}")
        if not set(PRICE_COLUMNS).issubset(frame.columns):
            fail(f"price_cache_columns:{ticker}")
        dates = pd.to_datetime(frame.index, errors="coerce")
        if dates.isna().any():
            fail(f"price_cache_date_invalid:{ticker}")
        dates = pd.DatetimeIndex(dates).tz_localize(None).normalize()
        if dates.duplicated().any():
            fail(f"price_cache_duplicate_date:{ticker}")
        if (dates > session).any():
            fail(f"price_cache_future_row:{ticker}")
        matches = frame.loc[dates == session, list(PRICE_COLUMNS)]
        if len(matches) != 1:
            fail(f"price_cache_exact_session_row:{ticker}")
        row = matches.iloc[0]
        ohlcv = {
            "open": finite_number(row["Open"], f"price_open:{ticker}", positive=True),
            "high": finite_number(row["High"], f"price_high:{ticker}", positive=True),
            "low": finite_number(row["Low"], f"price_low:{ticker}", positive=True),
            "close": finite_number(row["Close"], f"price_close:{ticker}", positive=True),
            "adjusted_close": finite_number(
                row["Adj Close"], f"price_adjusted_close:{ticker}", positive=True
            ),
            "volume": finite_number(row["Volume"], f"price_volume:{ticker}"),
        }
        if ohlcv["volume"] < 0:
            fail(f"price_volume_negative:{ticker}")
        tolerance = max(ohlcv["high"], ohlcv["low"], 1.0) * 1e-10
        if (
            ohlcv["high"] + tolerance < max(
                ohlcv["open"], ohlcv["close"], ohlcv["low"]
            )
            or ohlcv["low"] - tolerance > min(
                ohlcv["open"], ohlcv["close"], ohlcv["high"]
            )
        ):
            fail(f"price_cache_ohlc_order:{ticker}")
        values[ticker] = ohlcv
        files.append(
            fingerprint(path, label=f"price:{ticker}", relative_path=filename)
        )
    return values, manifest, files


def close_enough(left: float, right: float, relative_tolerance: float) -> bool:
    return math.isclose(left, right, rel_tol=relative_tolerance, abs_tol=1e-10)


def validate_after_close(
    artifact_root: Path,
    *,
    session: pd.Timestamp,
    operating: list[str],
    prices: dict[str, dict[str, float]],
    contract: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    anchor = contract["after_close_anchor"]
    summary_path = safe_source(
        artifact_root,
        anchor["summary_relative_path"],
        "after_close_summary_missing_or_unsafe",
    )
    ticker_path = safe_source(
        artifact_root,
        anchor["ticker_relative_path"],
        "after_close_ticker_file_missing_or_unsafe",
    )
    summary = read_json(summary_path, "after_close_summary")
    if (
        summary.get("status") != "completed"
        or summary.get("research_only") is not True
        or summary.get("production_activation_allowed") is not False
        or summary.get("latest_price_date") != session.date().isoformat()
    ):
        fail("after_close_summary_contract")
    try:
        frame = pd.read_csv(ticker_path, low_memory=False)
    except Exception:
        fail("after_close_ticker_csv")
    required_columns = {"ticker", "price_status", "price_date", "close", "volume"}
    if frame.empty or not required_columns.issubset(frame.columns):
        fail("after_close_ticker_columns")
    normalized = frame["ticker"].map(clean_ticker)
    if normalized.eq("").any() or normalized.duplicated(keep=False).any():
        fail("after_close_ticker_identity")
    frame = frame.copy()
    frame["ticker"] = normalized
    dates = pd.to_datetime(frame["price_date"], errors="coerce").dt.tz_localize(None).dt.normalize()
    if dates.isna().any() or (dates > session).any():
        fail("after_close_price_date")
    frame["_price_date"] = dates
    exact = frame[frame["_price_date"].eq(session)].set_index("ticker", drop=False)
    overlaps = sorted(set(operating) & set(exact.index))
    minimum_count = int(anchor["minimum_operating_ticker_overlap_count"])
    minimum_ratio = float(anchor["minimum_operating_ticker_overlap_ratio"])
    ratio = len(overlaps) / len(operating)
    if len(overlaps) < minimum_count or ratio + 1e-15 < minimum_ratio:
        fail("after_close_operating_overlap_insufficient")
    crosschecks: list[dict[str, Any]] = []
    for ticker in overlaps:
        row = exact.loc[ticker]
        if not isinstance(row, pd.Series) or str(row["price_status"]).strip().lower() != "ok":
            fail(f"after_close_price_status:{ticker}")
        anchor_close = finite_number(
            row["close"], f"after_close_close:{ticker}", positive=True
        )
        anchor_volume = finite_number(row["volume"], f"after_close_volume:{ticker}")
        if anchor_volume < 0:
            fail(f"after_close_volume_negative:{ticker}")
        close_match = close_enough(
            anchor_close,
            prices[ticker]["close"],
            float(anchor["close_relative_tolerance"]),
        )
        volume_match = close_enough(
            anchor_volume,
            prices[ticker]["volume"],
            float(anchor["volume_relative_tolerance"]),
        )
        if not close_match or not volume_match:
            fail(f"after_close_cross_source_mismatch:{ticker}")
        crosschecks.append(
            {
                "ticker": ticker,
                "session_date": session.date().isoformat(),
                "after_close_close_at_capture": anchor_close,
                "fresh_raw_close": prices[ticker]["close"],
                "volume": prices[ticker]["volume"],
                "close_match": True,
                "volume_match": True,
            }
        )
    overlap = {
        "operating_ticker_count": len(operating),
        "exact_anchor_ticker_count": len(overlaps),
        "exact_anchor_overlap_ratio": ratio,
        "missing_anchor_tickers": sorted(set(operating) - set(overlaps)),
        "anchor_is_substitute_for_price_cache": False,
    }
    source_files = [
        fingerprint(
            summary_path,
            label="after_close_summary",
            relative_path=anchor["summary_relative_path"],
        ),
        fingerprint(
            ticker_path,
            label="after_close_ticker_leadership",
            relative_path=anchor["ticker_relative_path"],
        ),
    ]
    return crosschecks, overlap, source_files


def base_status(session_text: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": BLOCKED_STATUS,
        "contract_failures": [],
        "selected_session_date": session_text,
        "review_only": True,
        "catchup_consumption_allowed": False,
        "backtest_executed": False,
        "fullrun_executed": False,
        "orders_generated": False,
        "target_books_mutated": False,
        "paper_ledger_mutated": False,
        "durable_state_mutated": False,
        "production_mutation_allowed": False,
        "live_trading_enabled": False,
        "automatic_promotion_allowed": False,
        "output_materialized": False,
    }


def build(args: argparse.Namespace) -> dict[str, Any]:
    session_text = str(args.session_date or "").strip()
    status = base_status(session_text)
    status["generated_at_utc"] = pd.Timestamp.now(tz="UTC").isoformat()
    output_dir = Path(args.output_dir).resolve()
    status_path = Path(args.output_status).resolve()
    contract_path = Path(args.contract).resolve()
    paper_state = Path(args.accepted_paper_state).resolve()
    after_close_root = Path(args.after_close_root).resolve()
    price_cache = Path(args.price_cache).resolve()
    accepted_metadata_path = Path(args.accepted_paper_metadata).resolve()
    after_metadata_path = Path(args.after_close_metadata).resolve()
    accepted_archive_path = Path(args.accepted_paper_archive).resolve()
    after_archive_path = Path(args.after_close_archive).resolve()

    try:
        roots = (paper_state, after_close_root, price_cache)
        if output_dir in roots or any(root in output_dir.parents for root in roots):
            fail("output_inside_input")
        if status_path == output_dir or output_dir in status_path.parents:
            fail("status_inside_output")
        if output_dir.exists() and (
            not output_dir.is_dir() or any(output_dir.iterdir())
        ):
            fail("output_not_empty")
        session = parse_session(session_text, "selected_session_date")
        contract = load_contract(contract_path)
        accepted_metadata = read_json(accepted_metadata_path, "accepted_metadata")
        after_metadata = read_json(after_metadata_path, "after_close_metadata")
        accepted_identity = validate_metadata(
            accepted_metadata, role="accepted_paper", contract=contract
        )
        after_identity = validate_metadata(
            after_metadata, role="after_close", contract=contract
        )
        validate_archive(
            accepted_archive_path, accepted_metadata, "accepted_paper"
        )
        validate_archive(after_archive_path, after_metadata, "after_close")
        integrity, required, operating, ticker_sources = validate_paper_state(
            paper_state, session=session, contract=contract
        )
        verify_paper_state_archive(
            accepted_archive_path,
            state=paper_state,
            integrity=integrity,
        )
        prices, price_manifest, price_files = validate_price_cache(
            price_cache, session=session, required=required, contract=contract
        )
        crosschecks, overlap, anchor_files = validate_after_close(
            after_close_root,
            session=session,
            operating=operating,
            prices=prices,
            contract=contract,
        )
        for source in anchor_files:
            verify_archive_member(
                after_archive_path,
                member_suffix=str(source["path"]),
                extracted_path=after_close_root / str(source["path"]),
                code=str(source["label"]),
            )

        source_files = [
            fingerprint(contract_path, label="contract", relative_path=contract_path.name),
            fingerprint(
                accepted_metadata_path,
                label="accepted_paper_artifact_metadata",
                relative_path=accepted_metadata_path.name,
            ),
            fingerprint(
                after_metadata_path,
                label="after_close_artifact_metadata",
                relative_path=after_metadata_path.name,
            ),
            fingerprint(
                paper_state / "snapshot_integrity.json",
                label="accepted_paper_snapshot_integrity",
                relative_path="snapshot_integrity.json",
            ),
            fingerprint(
                price_cache / "replay_price_cache_manifest.json",
                label="fresh_price_cache_manifest",
                relative_path="replay_price_cache_manifest.json",
            ),
            *anchor_files,
        ]

        output_dir.parent.mkdir(parents=True, exist_ok=True)
        if output_dir.exists():
            output_dir.rmdir()
        stage = Path(
            tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent)
        )
        try:
            cache_stage = stage / "price_cache"
            cache_stage.mkdir()
            materialized: list[dict[str, Any]] = []
            review_rows: list[dict[str, Any]] = []
            crosscheck_by_ticker = {row["ticker"]: row for row in crosschecks}
            source_price_by_ticker = {
                str(row["label"]).split(":", 1)[1]: row
                for row in price_files
            }
            for ticker in required:
                filename = px_cache_name(ticker)
                source = price_cache / filename
                destination = cache_stage / filename
                shutil.copyfile(source, destination)
                expected_source_hash = source_price_by_ticker[ticker]["sha256"]
                if (
                    sha256_file(source) != expected_source_hash
                    or sha256_file(destination) != expected_source_hash
                ):
                    fail(f"price_cache_source_changed_during_copy:{ticker}")
                materialized.append(
                    fingerprint(
                        destination,
                        label=f"price:{ticker}",
                        relative_path=f"price_cache/{filename}",
                    )
                    | {"ticker": ticker, "session_date": session_text}
                )
                review_rows.append(
                    {
                        "session_date": session_text,
                        "ticker": ticker,
                        **prices[ticker],
                        "operating_equity": ticker in set(operating),
                        "after_close_crosscheck_present": ticker in crosscheck_by_ticker,
                        "after_close_close_match": (
                            crosscheck_by_ticker.get(ticker, {}).get("close_match", False)
                        ),
                        "after_close_volume_match": (
                            crosscheck_by_ticker.get(ticker, {}).get("volume_match", False)
                        ),
                    }
                )
            pd.DataFrame(review_rows).to_csv(stage / "prices.csv", index=False)
            manifest = {
                **base_status(session_text),
                "status": READY_STATUS,
                "contract_failures": [],
                "generated_at_utc": status["generated_at_utc"],
                "accepted_paper_artifact": accepted_identity,
                "after_close_artifact": after_identity,
                "accepted_paper_as_of_date": integrity["as_of_date"],
                "accepted_paper_snapshot_hash": integrity["snapshot_hash"],
                "required_tickers": required,
                "operating_tickers": operating,
                "ticker_sources": ticker_sources,
                "required_ticker_count": len(required),
                "exact_close_ticker_count": len(required),
                "exact_close_coverage": 1.0,
                "prior_session_fallback_allowed": False,
                "future_rows_allowed": False,
                "after_close_overlap": overlap,
                "after_close_crosschecks": crosschecks,
                "source_files": source_files,
                "source_price_files": price_files,
                "price_cache_source_status": price_manifest.get("status"),
                "materialized_price_files": materialized,
                "requires_follow_up_consumption_review": True,
                "output_materialized": True,
            }
            write_json_atomic(stage / "manifest.json", manifest)
            os.replace(stage, output_dir)
        finally:
            if stage.exists():
                shutil.rmtree(stage)

        status.update(
            {
                "status": READY_STATUS,
                "accepted_paper_as_of_date": integrity["as_of_date"],
                "accepted_paper_snapshot_hash": integrity["snapshot_hash"],
                "required_ticker_count": len(required),
                "operating_ticker_count": len(operating),
                "exact_close_ticker_count": len(required),
                "exact_close_coverage": 1.0,
                "after_close_overlap": overlap,
                "output_manifest": fingerprint(
                    output_dir / "manifest.json",
                    label="recovery_price_evidence_manifest",
                    relative_path="manifest.json",
                ),
                "output_materialized": True,
            }
        )
    except ContractError as exc:
        status["contract_failures"] = [str(exc)]
    except Exception as exc:
        status["contract_failures"] = [f"unexpected:{type(exc).__name__}"]

    write_json_atomic(status_path, status)
    return status


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-date", required=True)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--accepted-paper-state", required=True)
    parser.add_argument("--accepted-paper-metadata", required=True)
    parser.add_argument("--accepted-paper-archive", required=True)
    parser.add_argument("--after-close-root", required=True)
    parser.add_argument("--after-close-metadata", required=True)
    parser.add_argument("--after-close-archive", required=True)
    parser.add_argument("--price-cache", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--output-status", required=True)
    return parser.parse_args()


def main() -> int:
    payload = build(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if payload.get("status") == READY_STATUS else 2


if __name__ == "__main__":
    raise SystemExit(main())
