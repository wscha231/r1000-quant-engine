#!/usr/bin/env python3
"""Build the data freshness contract used before operating selection.

The engine intentionally keeps large data outside git. This tool turns the
restored local copy into a machine-readable contract:

* which source was restored;
* how fresh each source is;
* whether operating target books are current enough for recommendations;
* which data snapshot was used by this run.

It is read-only. It never mutates target books, scores, gates, or production
policy. Downstream tools should treat ``selection_allowed=false`` as
DO_NOT_USE for current recommendations, even when research artifacts exist.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent


DATA_SOURCES: list[dict[str, Any]] = [
    {
        "name": "prices",
        "layer": "prices",
        "provider": "yfinance_cache_reconciled_later",
        "path": "cache_prices/replay_price_cache_manifest.json",
        "alternate_path": "data_raw/free/prices/replay_price_cache_manifest.json",
        "cadence_days": 3,
        "owner_workflow": "free_data_daily_update.yml",
        "hard_required_for_selection": True,
        "latest_key": "end",
    },
    {
        "name": "daily_market_snapshot",
        "layer": "market_snapshot",
        "provider": "price_cache_plus_yfinance_shares",
        "path": "data_pit/free/market_snapshot/latest_manifest.json",
        "alternate_path": "outputs/daily_market_snapshot/summary.json",
        "cadence_days": 3,
        "owner_workflow": "daily_operating_selection_refresh.yml",
        "hard_required_for_selection": False,
        "latest_key": "generated_at_utc",
    },
    {
        "name": "macro",
        "layer": "macro",
        "provider": "FRED_yfinance_market_snapshot",
        "path": "data_pit/macro",
        "alternate_path": "data_raw/free/macro",
        "cadence_days": 3,
        "owner_workflow": "daily_crisis_monitor.yml/free_data_daily_update.yml",
        "hard_required_for_selection": True,
    },
    {
        "name": "sec_companyfacts",
        "layer": "fundamentals",
        "provider": "SEC_companyfacts_bulk",
        "path": "data_raw/free/sec/companyfacts.zip",
        "cadence_days": 7,
        "owner_workflow": "data_readiness_preflight.yml/free_data_daily_update.yml",
        "hard_required_for_selection": False,
    },
    {
        "name": "form4_transactions",
        "layer": "form4",
        "provider": "SEC_EDGAR_Archives",
        "path": "data_pit/sec/form4_transactions.parquet",
        "cadence_days": 5,
        "owner_workflow": "sec_form4_daily_refresh.yml",
        "hard_required_for_selection": False,
    },
    {
        "name": "institutional_13f_holdings",
        "layer": "13f",
        "provider": "SEC_EDGAR_13F",
        "path": "data_pit/sec/institutional_13f_holdings.parquet",
        "cadence_days": 100,
        "owner_workflow": "sec_13f_quarterly_refresh.yml",
        "hard_required_for_selection": False,
    },
    {
        "name": "etf_holdings",
        "layer": "etf",
        "provider": "ETF_provider_plus_SEC_NPORT",
        "path": "data_pit/etf_holdings/etf_holdings.parquet",
        "cadence_days": 40,
        "owner_workflow": "etf_holdings_monthly_refresh.yml",
        "hard_required_for_selection": False,
    },
    {
        "name": "free_data_manifest",
        "layer": "manifest",
        "provider": "internal_manifest",
        "path": "manifests/free_data/latest_manifest.json",
        "cadence_days": 3,
        "owner_workflow": "free_data_daily_update.yml",
        "hard_required_for_selection": False,
        "latest_key": "generated_at_utc",
    },
]

COVERAGE_KEYS = {
    "etf": "coverage_etf_ratio",
    "sec_v1_evidence": "coverage_ratio",
    "13f": "coverage_13f_ratio",
    "smart_money": "coverage_smart_money_ratio",
    "top_manager": "coverage_top_manager_ratio",
}

COVERAGE_FLOORS = {
    "etf": 0.30,
    "sec_v1_evidence": 0.20,
    "13f": 0.50,
    "smart_money": 0.50,
    "top_manager": 0.05,
}

CORE_CANDIDATE_REQUIRED_COLUMNS = (
    "ticker",
    "px",
    "score_total",
    "mom_1m",
    "mom_3m",
    "mom_6m",
    "mom_12m",
    "relative_strength_composite",
    "valuation_price_cutoff_date",
    "feature_available_from",
)
CORE_CANDIDATE_NUMERIC_COLUMNS = {
    "px",
    "score_total",
    "mom_1m",
    "mom_3m",
    "mom_6m",
    "mom_12m",
    "relative_strength_composite",
}
CORE_CANDIDATE_DATETIME_COLUMNS = {
    "valuation_price_cutoff_date",
    "feature_available_from",
}
CORE_CANDIDATE_CASH_TICKERS = {"CASH", "__CASH__", "USD", "BIL", "SHV", "SGOV"}
CORE_CANDIDATE_INVALID_TICKERS = {
    "",
    "N/A",
    "NA",
    "NAN",
    "NONE",
    "NULL",
    "UNKNOWN",
}


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def parse_dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        out = datetime.fromisoformat(text[:10] if len(text) == 10 else text)
    except ValueError:
        return None
    if out.tzinfo is None:
        out = out.replace(tzinfo=timezone.utc)
    return out.astimezone(timezone.utc)


def parse_date(value: Any) -> date | None:
    dt = parse_dt(value)
    return dt.date() if dt else None


def days_old(value: Any, *, today: date | None = None) -> float | None:
    dt = parse_date(value)
    if dt is None:
        return None
    today = today or now_utc().date()
    return float((today - dt).days)


def sha256_file(path: Path, *, max_bytes: int | None = 50_000_000) -> str:
    if (
        not path.exists()
        or not path.is_file()
        or (max_bytes is not None and path.stat().st_size > max_bytes)
    ):
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def path_stats(
    path: Path,
    *,
    hash_max_bytes: int | None = 50_000_000,
) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "path": str(path)}
    if path.is_dir():
        files = [p for p in path.rglob("*") if p.is_file()]
        latest_mtime = max((p.stat().st_mtime for p in files), default=None)
        return {
            "exists": True,
            "path": str(path),
            "kind": "dir",
            "file_count": len(files),
            "bytes": int(sum(p.stat().st_size for p in files)),
            "modified_utc": datetime.fromtimestamp(latest_mtime, tz=timezone.utc).isoformat()
            if latest_mtime
            else "",
        }
    stat = path.stat()
    return {
        "exists": True,
        "path": str(path),
        "kind": "file",
        "bytes": int(stat.st_size),
        "modified_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        "sha256": sha256_file(path, max_bytes=hash_max_bytes),
    }


def csv_summary(path: Path, date_cols: tuple[str, ...] = ("rebalance_date", "date")) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "path": str(path), "rows": 0}
    rows = 0
    tickers: set[str] = set()
    dates: list[date] = []
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        for row in reader:
            rows += 1
            ticker = str(row.get("ticker") or "").strip().upper()
            if ticker and ticker not in {"CASH", "__CASH__"}:
                tickers.add(ticker)
            for col in date_cols:
                if col in fields:
                    dt = parse_date(row.get(col))
                    if dt:
                        dates.append(dt)
                    break
    return {
        "exists": True,
        "path": str(path),
        "rows": rows,
        "ticker_count": len(tickers),
        "min_date": min(dates).isoformat() if dates else "",
        "max_date": max(dates).isoformat() if dates else "",
    }


def select_existing_path(primary: str, alternate: str = "", alternate_paths: list[str] | None = None) -> Path:
    p = repo_path(primary)
    if p.exists():
        return p
    candidates = list(alternate_paths or [])
    if alternate:
        candidates.append(alternate)
    for candidate in candidates:
        alt = repo_path(candidate)
        if alt.exists():
            return alt
    return p


def directory_manifest_watermark(path: Path) -> tuple[str, str, str]:
    for name in ("latest_manifest.json", "manifest.json", "summary.json", "latest.json"):
        candidate = path / name
        payload = read_json(candidate)
        if not payload:
            continue
        for key in (
            "latest_asof",
            "asof_date",
            "latest_observable_close_date",
            "effective_latest_target_date",
            "generated_at_utc",
            "end",
            "date",
        ):
            value = str(payload.get(key) or "")
            if value:
                return value, str(candidate), key
    return "", "", ""


def source_watermark(spec: dict[str, Any], today: date) -> dict[str, Any]:
    path = select_existing_path(
        str(spec["path"]),
        str(spec.get("alternate_path") or ""),
        list(spec.get("alternate_paths") or []),
    )
    stats = path_stats(path)
    latest_value = ""
    freshness_basis = ""
    manifest_payload: dict[str, Any] = {}
    if path.is_file() and path.suffix.lower() == ".json":
        manifest_payload = read_json(path)
        latest_key = str(spec.get("latest_key") or "")
        if latest_key:
            latest_value = str(manifest_payload.get(latest_key) or "")
            if latest_value:
                freshness_basis = f"manifest:{latest_key}"
    if path.is_dir():
        latest_value, manifest_path, manifest_key = directory_manifest_watermark(path)
        if latest_value:
            freshness_basis = f"manifest:{manifest_key}"
            stats["freshness_manifest_path"] = manifest_path
    if not latest_value:
        latest_value = str(stats.get("modified_utc") or "")
        if latest_value:
            freshness_basis = "directory_mtime_proxy" if path.is_dir() else "file_mtime"
    age = days_old(latest_value, today=today)
    cadence = int(spec.get("cadence_days") or 0)
    exists = bool(stats.get("exists"))
    hard = bool(spec.get("hard_required_for_selection"))
    status = "ok"
    if not exists:
        status = "missing"
    elif age is None:
        status = "unknown"
    elif cadence > 0 and age > cadence:
        status = "stale"
    return {
        "source_name": spec["name"],
        "layer": spec["layer"],
        "provider": spec["provider"],
        "canonical_path": str(spec["path"]),
        "resolved_path": str(path),
        "owner_workflow": spec["owner_workflow"],
        "cadence_days": cadence,
        "latest_asof": latest_value,
        "freshness_basis": freshness_basis or "missing",
        "age_days": age,
        "status": status,
        "hard_required_for_selection": hard,
        "stats": stats,
    }


def operating_book_status(latest_run: Path, require_current: bool) -> tuple[dict[str, Any], list[str], list[str]]:
    blockers: list[str] = []
    warnings: list[str] = []
    summary_path = latest_run / "reports" / "operating_target_books_summary.json"
    payload = read_json(summary_path)
    books = []
    if payload:
        books = list(payload.get("books") or [])
        if payload.get("status") == "blocked":
            blockers.append(str(payload.get("blocked_reason") or "operating target book builder reported blocked"))
        if require_current:
            for row in books:
                if not bool(row.get("operating_book_current")):
                    blockers.append(f"{row.get('portfolio')}: operating target book is not current")
    else:
        warnings.append("operating_target_books_summary.json is missing")

    fallback_books = {
        "main": csv_summary(latest_run / "reports" / "operating_main_target_book.csv"),
        "concentrated": csv_summary(latest_run / "reports" / "operating_concentrated_target_book.csv"),
    }
    if require_current and not payload:
        for name, item in fallback_books.items():
            if not item.get("exists"):
                blockers.append(f"{name}: operating target book is missing")
    return {
        "summary_path": str(summary_path),
        "summary_exists": bool(payload),
        "require_current": bool(require_current),
        "builder_status": payload.get("status") if payload else "",
        "books": books,
        "fallback_books": fallback_books,
    }, blockers, warnings


def readiness_status(latest_run: Path) -> tuple[dict[str, Any], list[str], list[str]]:
    path = latest_run / "data_readiness" / "summary.json"
    payload = read_json(path)
    blockers: list[str] = []
    warnings: list[str] = []
    if not payload:
        blockers.append("data_readiness/summary.json is missing")
        return {"path": str(path), "exists": False}, blockers, warnings
    blockers.extend(str(item) for item in (payload.get("blockers") or []) if str(item).strip())
    warnings.extend(str(item) for item in (payload.get("warnings") or []) if str(item).strip())
    if not bool(payload.get("ready_for_policy_replay")):
        blockers.append("data_readiness.ready_for_policy_replay is false")
    future_rows = int(
        ((payload.get("feature_source_coverage") or {}).get("overall") or {}).get("pit_future_available_from_rows")
        or 0
    )
    if future_rows:
        blockers.append(f"feature_source_coverage has {future_rows} future available_from row(s)")
    return {
        "path": str(path),
        "exists": True,
        "status": payload.get("status"),
        "ready_for_fullrun": bool(payload.get("ready_for_fullrun")),
        "ready_for_policy_replay": bool(payload.get("ready_for_policy_replay")),
        "latest_target_date": payload.get("latest_target_date"),
        "latest_observable_close_date": payload.get("latest_observable_close_date"),
        "effective_latest_target_date": payload.get("effective_latest_target_date"),
        "pit_future_available_from_rows": future_rows,
    }, blockers, warnings


def coverage_status(latest_run: Path, required_layers: set[str], warn_layers: set[str]) -> tuple[dict[str, Any], list[str], list[str]]:
    path = latest_run / "sec_enriched_candidate_replay" / "summary.json"
    payload = read_json(path)
    blockers: list[str] = []
    warnings: list[str] = []
    layers: list[dict[str, Any]] = []
    if not payload:
        warnings.append("sec_enriched_candidate_replay/summary.json is missing; evidence is not proven materialized")
        return {"path": str(path), "exists": False, "layers": layers}, blockers, warnings
    for layer, key in COVERAGE_KEYS.items():
        raw = payload.get(key)
        try:
            value = float(raw) if raw is not None else None
        except (TypeError, ValueError):
            value = None
        floor = float(COVERAGE_FLOORS[layer])
        ok = value is not None and value >= floor
        severity = "required" if layer in required_layers else "warn"
        status = "ok" if ok else ("FAIL" if severity == "required" else "WARN")
        item = {
            "layer": layer,
            "source_key": key,
            "coverage": value,
            "floor": floor,
            "status": status,
            "severity": severity,
            "present": key in payload,
        }
        layers.append(item)
        if not ok:
            message = f"{layer} coverage {value} < floor {floor}"
            if layer in required_layers and layer not in warn_layers:
                blockers.append(message)
            else:
                warnings.append(message)
    return {
        "path": str(path),
        "exists": True,
        "status": payload.get("status"),
        "row_count": payload.get("row_count"),
        "production_activation_allowed": bool(payload.get("production_activation_allowed", False)),
        "layers": layers,
    }, blockers, warnings


def _core_value_is_valid(column: str, value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if column == "ticker":
        return text.upper() not in CORE_CANDIDATE_INVALID_TICKERS
    if column in CORE_CANDIDATE_NUMERIC_COLUMNS:
        try:
            numeric = float(text)
            return math.isfinite(numeric) and (column != "px" or numeric > 0.0)
        except (TypeError, ValueError):
            return False
    if column in CORE_CANDIDATE_DATETIME_COLUMNS:
        return parse_dt(text) is not None
    return True


def core_candidate_ticker_set_sha256(tickers: list[str] | tuple[str, ...] | set[str]) -> str:
    normalized = sorted(
        {
            str(value or "").strip().upper()
            for value in tickers
            if str(value or "").strip().upper() not in CORE_CANDIDATE_CASH_TICKERS
        }
    )
    payload = ("\n".join(normalized) + ("\n" if normalized else "")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def core_candidate_coverage_semantic_view(
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return the portable coverage contract, excluding location-only metadata."""
    return {
        key: value
        for key, value in dict(payload or {}).items()
        if key != "path"
    }


def core_candidate_coverage_for_path(
    path: Path,
    *,
    minimum_ratio: float,
    expected_row_count: int | None = None,
    expected_valuation_date: str = "",
    decision_time_utc: str = "",
    expected_ticker_set_sha256: str = "",
) -> tuple[dict[str, Any], list[str]]:
    required = minimum_ratio > 0.0
    expected_date = parse_date(expected_valuation_date)
    decision_time = parse_dt(decision_time_utc)
    result: dict[str, Any] = {
        "schema_version": "run287-core-candidate-coverage-v1",
        "path": str(path),
        "coverage_semantics": (
            "complete finite core candidate data fields over the declared "
            "expected candidate universe; ranking eligibility flags are "
            "validated by the exact-packet selector, not counted as data coverage"
        ),
        "required_for_target_mutation": required,
        "minimum_coverage_ratio": float(minimum_ratio),
        "expected_row_count": (
            int(expected_row_count) if expected_row_count is not None else None
        ),
        "expected_valuation_date": (
            expected_date.isoformat() if expected_date is not None else ""
        ),
        "decision_time_utc": (
            decision_time.isoformat() if decision_time is not None else ""
        ),
        "expected_ticker_set_sha256": str(expected_ticker_set_sha256 or "").lower(),
        "ticker_set_sha256": "",
        "ticker_set_matches_expected": None,
        "source_sha256": "",
        "source_bytes": 0,
        "required_columns": list(CORE_CANDIDATE_REQUIRED_COLUMNS),
        "exists": path.is_file(),
        "row_count": 0,
        "coverage_denominator_count": 0,
        "missing_expected_row_count": 0,
        "unexpected_row_count": 0,
        "complete_row_count": 0,
        "invalid_row_count": 0,
        "coverage_ratio": 0.0,
        "missing_columns": list(CORE_CANDIDATE_REQUIRED_COLUMNS),
        "invalid_by_column": {},
        "hard_integrity_invalid_by_column": {},
        "duplicate_ticker_count": 0,
        "invalid_examples": [],
        "passed": False,
    }
    blockers: list[str] = []
    if expected_row_count is not None and expected_row_count <= 0:
        blockers.append("core candidate expected row count must be positive")
    if expected_valuation_date and expected_date is None:
        blockers.append("core candidate expected valuation date is invalid")
    if decision_time_utc and decision_time is None:
        blockers.append("core candidate decision time is invalid")
    expected_ticker_hash = str(expected_ticker_set_sha256 or "").lower()
    if expected_ticker_hash and (
        len(expected_ticker_hash) != 64
        or any(character not in "0123456789abcdef" for character in expected_ticker_hash)
    ):
        blockers.append("core candidate expected ticker-set SHA-256 is invalid")
    if not path.is_file():
        if required:
            blockers.append("core candidate coverage source scored_latest.csv is missing")
        return result, blockers

    source_before = path_stats(path, hash_max_bytes=None)
    result["source_sha256"] = str(source_before.get("sha256") or "")
    result["source_bytes"] = int(source_before.get("bytes") or 0)
    invalid_by_column = {column: 0 for column in CORE_CANDIDATE_REQUIRED_COLUMNS}
    invalid_examples: list[dict[str, Any]] = []
    seen_tickers: set[str] = set()
    duplicate_tickers: set[str] = set()
    row_count = 0
    complete_count = 0
    with path.open("r", encoding="utf-8-sig", errors="strict", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        missing_columns = [
            column for column in CORE_CANDIDATE_REQUIRED_COLUMNS if column not in fields
        ]
        result["missing_columns"] = missing_columns
        for row_number, row in enumerate(reader, start=2):
            ticker = str(row.get("ticker") or "").strip().upper()
            if ticker in CORE_CANDIDATE_CASH_TICKERS:
                continue
            row_count += 1
            if ticker:
                if ticker in seen_tickers:
                    duplicate_tickers.add(ticker)
                seen_tickers.add(ticker)
            invalid_fields = [
                column
                for column in CORE_CANDIDATE_REQUIRED_COLUMNS
                if column in fields and not _core_value_is_valid(column, row.get(column))
            ]
            if (
                "valuation_price_cutoff_date" in fields
                and expected_date is not None
                and parse_date(row.get("valuation_price_cutoff_date"))
                != expected_date
            ):
                invalid_fields.append("valuation_price_cutoff_date")
            if "feature_available_from" in fields and decision_time is not None:
                available_from = parse_dt(row.get("feature_available_from"))
                if available_from is None or available_from > decision_time:
                    invalid_fields.append("feature_available_from")
            invalid_fields.extend(missing_columns)
            invalid_fields = sorted(set(invalid_fields))
            if invalid_fields:
                for column in invalid_fields:
                    invalid_by_column[column] += 1
                if len(invalid_examples) < 10:
                    invalid_examples.append(
                        {
                            "row_number": row_number,
                            "ticker": ticker,
                            "invalid_fields": invalid_fields,
                        }
                    )
            else:
                complete_count += 1

    source_after = path_stats(path, hash_max_bytes=None)
    if (
        source_after.get("sha256") != source_before.get("sha256")
        or source_after.get("bytes") != source_before.get("bytes")
    ):
        blockers.append("core candidate coverage source changed while being validated")
    result["source_sha256"] = str(source_after.get("sha256") or "")
    result["source_bytes"] = int(source_after.get("bytes") or 0)
    ticker_set_sha256 = core_candidate_ticker_set_sha256(seen_tickers)
    ticker_set_matches_expected = (
        ticker_set_sha256 == expected_ticker_hash if expected_ticker_hash else None
    )
    denominator = (
        int(expected_row_count)
        if expected_row_count is not None and expected_row_count > 0
        else row_count
    )
    missing_expected = max(denominator - row_count, 0)
    unexpected_rows = max(row_count - denominator, 0)
    ratio = float(complete_count / denominator) if denominator else 0.0
    result.update(
        {
            "row_count": int(row_count),
            "coverage_denominator_count": int(denominator),
            "missing_expected_row_count": int(missing_expected),
            "unexpected_row_count": int(unexpected_rows),
            "complete_row_count": int(complete_count),
            "invalid_row_count": int(row_count - complete_count),
            "coverage_ratio": ratio,
            "invalid_by_column": {
                column: int(count)
                for column, count in invalid_by_column.items()
                if count
            },
            "duplicate_ticker_count": int(len(duplicate_tickers)),
            "duplicate_ticker_examples": sorted(duplicate_tickers)[:10],
            "ticker_set_sha256": ticker_set_sha256,
            "ticker_set_matches_expected": ticker_set_matches_expected,
            "invalid_examples": invalid_examples,
        }
    )
    hard_integrity_counts = {
        column: int(invalid_by_column.get(column) or 0)
        for column in (
            "ticker",
            "px",
            "valuation_price_cutoff_date",
            "feature_available_from",
        )
        if int(invalid_by_column.get(column) or 0) > 0
    }
    result["hard_integrity_invalid_by_column"] = hard_integrity_counts
    if required:
        for column, count in hard_integrity_counts.items():
            blockers.append(
                f"core candidate hard integrity violation in {column}: {count} row(s)"
            )
    result["passed"] = bool(
        row_count > 0
        and not result["missing_columns"]
        and ratio >= minimum_ratio
        and not duplicate_tickers
        and unexpected_rows == 0
        and not hard_integrity_counts
        and ticker_set_matches_expected is not False
        and not blockers
    )
    if required:
        if row_count <= 0:
            blockers.append("core candidate coverage has no non-cash rows")
        if result["missing_columns"]:
            blockers.append(
                "core candidate coverage is missing required columns: "
                + ",".join(result["missing_columns"])
            )
        if ratio < minimum_ratio:
            blockers.append(
                f"core candidate coverage {ratio:.6f} < required {minimum_ratio:.6f}"
            )
        if duplicate_tickers:
            blockers.append(
                f"core candidate coverage has {len(duplicate_tickers)} duplicate ticker(s)"
            )
        if unexpected_rows:
            blockers.append(
                f"core candidate coverage has {unexpected_rows} row(s) above the expected universe"
            )
        if ticker_set_matches_expected is False:
            blockers.append("core candidate ticker set does not match the expected universe")
    result["passed"] = bool(result["passed"] and not blockers)
    return result, blockers


def core_candidate_coverage_status(
    latest_run: Path,
    *,
    minimum_ratio: float,
) -> tuple[dict[str, Any], list[str]]:
    return core_candidate_coverage_for_path(
        latest_run / "scored_latest.csv",
        minimum_ratio=minimum_ratio,
    )


def build_snapshot_manifest(
    *,
    latest_run: Path,
    price_cache: Path,
    watermarks: list[dict[str, Any]],
    readiness: dict[str, Any],
    operating: dict[str, Any],
    coverage: dict[str, Any],
    core_candidate_coverage: dict[str, Any],
    args: argparse.Namespace,
) -> dict[str, Any]:
    files = [
        latest_run / "scored_latest.csv",
        latest_run / "reports" / "candidate_replay_book.csv",
        latest_run / "sec_enriched_candidate_replay" / "candidate_replay_book_sec_enriched.csv",
        latest_run / "reports" / "operating_main_target_book.csv",
        latest_run / "reports" / "operating_concentrated_target_book.csv",
        price_cache / "replay_price_cache_manifest.json",
    ]
    entries = []
    for path in files:
        # These exact bytes can authorize a paper target proposal. Unlike
        # diagnostic source watermarks, mutation-bound snapshot members must
        # always receive a streaming SHA-256, even when a candidate CSV is
        # larger than the diagnostic 50 MB hashing budget.
        stats = path_stats(path, hash_max_bytes=None)
        entries.append(
            {
                "path": str(path),
                "exists": bool(stats.get("exists")),
                "bytes": stats.get("bytes", 0),
                "sha256": stats.get("sha256", ""),
                "modified_utc": stats.get("modified_utc", ""),
            }
        )
    return {
        "schema_version": "data-snapshot-manifest-v1",
        "generated_at_utc": now_utc().isoformat(),
        "source_run_id": str(args.source_run_id or os.environ.get("GITHUB_RUN_ID") or "local"),
        "source_commit_sha": str(args.source_commit_sha or os.environ.get("GITHUB_SHA") or ""),
        "source_branch": str(args.source_branch or os.environ.get("GITHUB_REF_NAME") or ""),
        "source_artifact_name": str(args.source_artifact_name or ""),
        "source_context": str(getattr(args, "source_context", "") or ""),
        "freshness_contract_non_fatal": bool(getattr(args, "freshness_contract_non_fatal", False)),
        "latest_run": str(latest_run),
        "price_cache": str(price_cache),
        "watermarks": watermarks,
        "readiness": readiness,
        "operating_target_books": operating,
        "evidence_coverage": coverage,
        "core_candidate_coverage": core_candidate_coverage,
        "files": entries,
        "production_mutation_allowed": False,
    }


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Data Freshness Contract",
        "",
        f"- status: `{payload.get('status')}`",
        f"- selection_allowed: `{str(payload.get('selection_allowed')).lower()}`",
        f"- promotion_allowed: `{str(payload.get('promotion_allowed')).lower()}`",
        f"- latest_observable_close_date: `{(payload.get('readiness') or {}).get('latest_observable_close_date') or ''}`",
        f"- effective_latest_target_date: `{(payload.get('readiness') or {}).get('effective_latest_target_date') or ''}`",
        f"- production_mutation_allowed: `{str(payload.get('production_mutation_allowed')).lower()}`",
        f"- core_candidate_coverage_ratio: `{(payload.get('core_candidate_coverage') or {}).get('coverage_ratio')}`",
        f"- core_candidate_coverage_floor: `{(payload.get('core_candidate_coverage') or {}).get('minimum_coverage_ratio')}`",
        f"- core_candidate_coverage_passed: `{str((payload.get('core_candidate_coverage') or {}).get('passed')).lower()}`",
        "",
        "## Blockers",
        "",
    ]
    blockers = payload.get("blockers") or []
    lines.extend([f"- {item}" for item in blockers] or ["- none"])
    lines.extend(["", "## Warnings", ""])
    warnings = payload.get("warnings") or []
    lines.extend([f"- {item}" for item in warnings] or ["- none"])
    lines.extend(
        [
            "",
            "## Watermarks",
            "",
            "| source | status | latest_asof | age_days | cadence_days | owner |",
            "| --- | --- | --- | ---: | ---: | --- |",
        ]
    )
    for item in payload.get("watermarks") or []:
        age = item.get("age_days")
        age_text = "" if age is None else f"{float(age):.1f}"
        lines.append(
            f"| {item.get('source_name')} | {item.get('status')} | {item.get('latest_asof') or ''} | {age_text} | {item.get('cadence_days')} | {item.get('owner_workflow')} |"
        )
    lines.extend(["", "## Evidence Coverage", ""])
    for item in ((payload.get("evidence_coverage") or {}).get("layers") or []):
        lines.append(
            f"- `{item.get('layer')}`: status `{item.get('status')}`, coverage `{item.get('coverage')}`, floor `{item.get('floor')}`"
        )
    lines.append("")
    return "\n".join(lines)


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    price_cache = repo_path(args.price_cache)
    output_dir = repo_path(args.output_dir)
    today = parse_date(args.asof_date) or now_utc().date()
    source_specs = [dict(item) for item in DATA_SOURCES]
    for item in source_specs:
        if item["name"] == "prices":
            item["path"] = str(price_cache / "replay_price_cache_manifest.json")
            item["alternate_paths"] = [
                str(latest_run / "manifests" / "replay_price_cache_manifest.json"),
                str(latest_run / "cache_prices" / "replay_price_cache_manifest.json"),
                str(REPO_ROOT / "data_raw" / "free" / "prices" / "replay_price_cache_manifest.json"),
            ]
        if item["name"] == "macro":
            item["alternate_paths"] = [
                str(latest_run / "data_pit" / "macro"),
                str(latest_run / "daily_crisis_monitor" / "daily_features.parquet"),
            ]
        item["cadence_days"] = int(getattr(args, f"max_{item['name']}_stale_days", item["cadence_days"]))

    watermarks = [source_watermark(spec, today=today) for spec in source_specs]
    blockers: list[str] = []
    warnings: list[str] = []
    for item in watermarks:
        if item.get("source_name") == "macro" and item.get("freshness_basis") == "directory_mtime_proxy":
            warnings.append("macro freshness uses directory_mtime_proxy; add a macro latest_manifest.json/asof watermark")
        if item["status"] in {"missing", "stale", "unknown"}:
            msg = f"{item['source_name']} is {item['status']} (latest_asof={item.get('latest_asof') or ''})"
            if item.get("hard_required_for_selection"):
                blockers.append(msg)
            else:
                warnings.append(msg)

    readiness, r_blockers, r_warnings = readiness_status(latest_run)
    blockers.extend(r_blockers)
    warnings.extend(r_warnings)

    operating, o_blockers, o_warnings = operating_book_status(
        latest_run,
        require_current=bool(args.require_current_operating_books),
    )
    blockers.extend(o_blockers)
    warnings.extend(o_warnings)

    required_layers = {item.strip() for item in str(args.require_coverage_layers or "").split(",") if item.strip()}
    warn_layers = {item.strip() for item in str(args.warn_only_coverage_layers or "").split(",") if item.strip()}
    coverage, c_blockers, c_warnings = coverage_status(latest_run, required_layers, warn_layers)
    blockers.extend(c_blockers)
    warnings.extend(c_warnings)

    minimum_core_candidate_coverage = float(
        getattr(args, "minimum_core_candidate_coverage", 0.0) or 0.0
    )
    core_candidate_coverage, core_blockers = core_candidate_coverage_status(
        latest_run,
        minimum_ratio=minimum_core_candidate_coverage,
    )
    blockers.extend(core_blockers)

    selection_allowed = not blockers
    promotion_blockers = list(blockers)
    if not coverage.get("exists"):
        promotion_blockers.append("evidence coverage manifest is missing")
    for layer in (coverage.get("layers") or []):
        if layer.get("status") != "ok":
            promotion_blockers.append(f"{layer.get('layer')} coverage is not promotion-ready")
    promotion_allowed = not promotion_blockers
    status = "pass" if selection_allowed else "blocked"

    snapshot = build_snapshot_manifest(
        latest_run=latest_run,
        price_cache=price_cache,
        watermarks=watermarks,
        readiness=readiness,
        operating=operating,
        coverage=coverage,
        core_candidate_coverage=core_candidate_coverage,
        args=args,
    )
    payload = {
        "schema_version": "data-freshness-contract-v1",
        "generated_at_utc": now_utc().isoformat(),
        "asof_date": today.isoformat(),
        "status": status,
        "selection_allowed": bool(selection_allowed),
        "recommendation_status": "READY_FOR_OPERATING_SELECTION" if selection_allowed else "DO_NOT_USE_REVIEW_REQUIRED",
        "promotion_allowed": bool(promotion_allowed),
        "production_mutation_allowed": False,
        "source_context": str(getattr(args, "source_context", "") or ""),
        "freshness_contract_non_fatal": bool(getattr(args, "freshness_contract_non_fatal", False)),
        "source_run_id": str(args.source_run_id or os.environ.get("GITHUB_RUN_ID") or "local"),
        "source_commit_sha": str(args.source_commit_sha or os.environ.get("GITHUB_SHA") or ""),
        "source_branch": str(args.source_branch or os.environ.get("GITHUB_REF_NAME") or ""),
        "source_artifact_name": str(args.source_artifact_name or ""),
        "latest_run": str(latest_run),
        "price_cache": str(price_cache),
        "readiness": readiness,
        "operating_target_books": operating,
        "evidence_coverage": coverage,
        "core_candidate_coverage": core_candidate_coverage,
        "watermarks": watermarks,
        "blockers": sorted(set(blockers)),
        "warnings": sorted(set(warnings)),
        "promotion_blockers": sorted(set(promotion_blockers)),
        "outputs": {
            "status_json": str(output_dir / "status.json"),
            "data_watermarks_json": str(output_dir / "data_watermarks.json"),
            "data_snapshot_manifest_json": str(output_dir / "data_snapshot_manifest.json"),
            "report_md": str(output_dir / "report.md"),
        },
    }
    payload["data_snapshot_manifest"] = snapshot
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default="outputs/data_freshness_contract")
    parser.add_argument("--asof-date", default="")
    parser.add_argument("--require-current-operating-books", action="store_true")
    parser.add_argument("--require-coverage-layers", default="")
    parser.add_argument("--warn-only-coverage-layers", default="etf,sec_v1_evidence,13f,smart_money,top_manager")
    parser.add_argument("--minimum-core-candidate-coverage", type=float, default=0.0)
    parser.add_argument("--strict-selection", action="store_true")
    parser.add_argument("--strict-promotion", action="store_true")
    parser.add_argument("--source-run-id", default="")
    parser.add_argument("--source-commit-sha", default="")
    parser.add_argument("--source-branch", default="")
    parser.add_argument("--source-artifact-name", default="")
    parser.add_argument("--source-context", default="")
    parser.add_argument("--freshness-contract-non-fatal", action="store_true")
    parser.add_argument("--max-prices-stale-days", type=int, default=3)
    parser.add_argument("--max-macro-stale-days", type=int, default=3)
    parser.add_argument("--max-sec-companyfacts-stale-days", type=int, default=7)
    parser.add_argument("--max-form4-transactions-stale-days", type=int, default=5)
    parser.add_argument("--max-institutional-13f-holdings-stale-days", type=int, default=100)
    parser.add_argument("--max-etf-holdings-stale-days", type=int, default=40)
    parser.add_argument("--max-free-data-manifest-stale-days", type=int, default=3)
    parser.add_argument("--max-daily-market-snapshot-stale-days", type=int, default=3)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 0.0 <= float(args.minimum_core_candidate_coverage) <= 1.0:
        raise SystemExit("--minimum-core-candidate-coverage must be between 0 and 1")
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    status_path = output_dir / "status.json"
    status_path.unlink(missing_ok=True)
    payload = build_payload(args)
    write_json(output_dir / "data_watermarks.json", {"schema_version": "data-watermarks-v1", "watermarks": payload["watermarks"]})
    write_json(output_dir / "data_snapshot_manifest.json", payload["data_snapshot_manifest"])
    (output_dir / "report.md").write_text(render_report(payload), encoding="utf-8")
    write_json(status_path, {k: v for k, v in payload.items() if k != "data_snapshot_manifest"})
    print(
        json.dumps(
            {
                "status": payload["status"],
                "selection_allowed": payload["selection_allowed"],
                "promotion_allowed": payload["promotion_allowed"],
                "blockers": payload["blockers"],
                "warnings": payload["warnings"][:10],
                "output_dir": str(output_dir),
            },
            indent=2,
            sort_keys=True,
        )
    )
    if args.strict_selection and not payload["selection_allowed"]:
        return 2
    if args.strict_promotion and not payload["promotion_allowed"]:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
