#!/usr/bin/env python3
"""Build a durable, resumable queue for forward estimate collection.

The queue is seeded from an exact current-universe coverage CSV.  It persists a
canonical ticker snapshot and per-ticker checkpoint beside the forward-only
estimate archive so later runs do not depend on an ``outputs/`` file still
being present.  Successful fresh snapshots are reused; only missing, stale,
new-universe, or bounded rotating-retry names are selected.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.build_forward_estimate_universe_plan import (  # noqa: E402
    DEFAULT_EXCLUDE_TICKERS,
    display_path,
    is_valid_equity_ticker,
    normalize_ticker,
    repo_path,
    utc_now,
)

SCHEMA_VERSION = "forward-estimate-collection-queue-v2"
CHECKPOINT_SCHEMA_VERSION = "forward-estimate-collection-checkpoint-v1"
DEFAULT_EXPECTED_UNIVERSE_COUNT = 993
NON_EQUITY_PLACEHOLDERS = {"CASH", "__CASH__"}
LATEST_RUN_UNIVERSE_FILES = (
    "scored_latest.csv",
    "reports/main_monthly_weights.csv",
    "reports/concentrated_strategy_holdings.csv",
    "reports/candidate_replay_book.csv",
)
QUEUE_COLUMNS = [
    "ticker",
    "queue_state",
    "queue_action",
    "selected",
    "selection_reason",
    "eligible_for_vendor_request",
    "non_equity_placeholder",
    "current_universe_new",
    "priority_hint",
    "observed_in_snapshot",
    "has_successful_snapshot",
    "latest_observed_date",
    "latest_success_date",
    "successful_snapshot_age_days",
    "last_selected_at_utc",
    "selection_count",
    "canonical_universe_sha256",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    record: dict[str, Any] = {"path": display_path(path), "exists": path.exists() and path.is_file()}
    if record["exists"]:
        stat = path.stat()
        record.update(
            {
                "size_bytes": stat.st_size,
                "sha256": sha256_file(path),
                "modified_at_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z"),
            }
        )
    return record


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def parse_inline_tickers(value: str, excludes: set[str]) -> list[str]:
    out = []
    for raw in (value or "").split(","):
        ticker = normalize_ticker(raw)
        if is_valid_equity_ticker(ticker, excludes):
            out.append(ticker)
    return list(dict.fromkeys(out))


def read_ticker_file(path: Path, excludes: set[str]) -> tuple[list[str], dict[str, Any]]:
    record = file_record(path)
    record.update(
        {
            "ticker_column": "",
            "raw_row_count": 0,
            "valid_ticker_count": 0,
            "duplicate_ticker_count": 0,
            "invalid_ticker_count": 0,
        }
    )
    if not record["exists"]:
        return [], record
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            fieldnames = reader.fieldnames or []
            field = "ticker" if "ticker" in fieldnames else (fieldnames[0] if fieldnames else "")
            raw_values = [normalize_ticker(row.get(field)) for row in reader] if field else []
    except (OSError, csv.Error, UnicodeError) as exc:
        record["read_error"] = str(exc)
        return [], record
    valid = [ticker for ticker in raw_values if is_valid_equity_ticker(ticker, excludes)]
    tickers = list(dict.fromkeys(valid))
    record.update(
        {
            "ticker_column": field,
            "raw_row_count": len(raw_values),
            "valid_ticker_count": len(tickers),
            "duplicate_ticker_count": len(valid) - len(tickers),
            "invalid_ticker_count": len(raw_values) - len(valid),
        }
    )
    return tickers, record


def read_universe_file(path: Path, excludes: set[str]) -> tuple[list[str], dict[str, Any]]:
    """Read an exact universe while retaining explicit cash placeholders."""
    record = file_record(path)
    record.update(
        {
            "ticker_column": "",
            "raw_row_count": 0,
            "valid_ticker_count": 0,
            "eligible_ticker_count": 0,
            "non_equity_placeholder_ticker_count": 0,
            "duplicate_ticker_count": 0,
            "invalid_ticker_count": 0,
        }
    )
    if not record["exists"]:
        return [], record
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            fieldnames = reader.fieldnames or []
            field = "ticker" if "ticker" in fieldnames else (fieldnames[0] if fieldnames else "")
            raw_values = [normalize_ticker(row.get(field)) for row in reader] if field else []
    except (OSError, csv.Error, UnicodeError) as exc:
        record["read_error"] = str(exc)
        return [], record
    accepted = [
        ticker
        for ticker in raw_values
        if ticker in NON_EQUITY_PLACEHOLDERS or is_valid_equity_ticker(ticker, excludes)
    ]
    tickers = list(dict.fromkeys(accepted))
    placeholder_count = sum(ticker in NON_EQUITY_PLACEHOLDERS for ticker in tickers)
    record.update(
        {
            "ticker_column": field,
            "raw_row_count": len(raw_values),
            "valid_ticker_count": len(tickers),
            "eligible_ticker_count": len(tickers) - placeholder_count,
            "non_equity_placeholder_ticker_count": placeholder_count,
            "duplicate_ticker_count": len(accepted) - len(tickers),
            "invalid_ticker_count": len(raw_values) - len(accepted),
        }
    )
    return tickers, record


def read_latest_run_universe(path: Path, excludes: set[str]) -> tuple[list[str], dict[str, Any]]:
    ordered: list[str] = []
    source_files: list[dict[str, Any]] = []
    for relative in LATEST_RUN_UNIVERSE_FILES:
        source_path = path / relative
        tickers, record = read_universe_file(source_path, excludes)
        ordered.extend(tickers)
        source_files.append(record)
    tickers = sorted(dict.fromkeys(ordered))
    placeholder_count = sum(ticker in NON_EQUITY_PLACEHOLDERS for ticker in tickers)
    hash_lines = [
        f"{record.get('path', '')}|{record.get('sha256', '')}|{record.get('modified_at_utc', '')}"
        for record in source_files
    ]
    modified = sorted(
        [str(record.get("modified_at_utc")) for record in source_files if record.get("modified_at_utc")]
    )
    record = {
        "path": display_path(path),
        "exists": any(bool(item.get("exists")) for item in source_files),
        "source_kind": "latest_run_exact_universe_union",
        "sha256": hashlib.sha256("\n".join(hash_lines).encode("utf-8")).hexdigest(),
        "modified_at_utc": modified[-1] if modified else "",
        "raw_row_count": sum(int(item.get("raw_row_count") or 0) for item in source_files),
        "valid_ticker_count": len(tickers),
        "eligible_ticker_count": len(tickers) - placeholder_count,
        "non_equity_placeholder_ticker_count": placeholder_count,
        "source_files": source_files,
        "pit_universe_label_clean": False,
        "forward_only_current_universe_proxy": True,
    }
    return tickers, record


def ticker_csv_text(tickers: list[str]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=["ticker"], lineterminator="\n")
    writer.writeheader()
    for ticker in tickers:
        writer.writerow({"ticker": ticker})
    return buffer.getvalue()


def write_text_if_changed(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return
    path.write_text(text, encoding="utf-8")


def write_ticker_csv(path: Path, tickers: list[str]) -> None:
    write_text_if_changed(path, ticker_csv_text(tickers))


def write_queue_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=QUEUE_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def snapshot_date_column(frame: pd.DataFrame) -> pd.Series:
    if "available_from" in frame.columns:
        return pd.to_datetime(frame["available_from"], errors="coerce", utc=True)
    if "as_of_date" in frame.columns:
        return pd.to_datetime(frame["as_of_date"], errors="coerce", utc=True)
    return pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns, UTC]")


def load_snapshot_history(snapshot_dir: Path) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    frames: list[pd.DataFrame] = []
    records: list[dict[str, Any]] = []
    for path in sorted(snapshot_dir.glob("estimates_*.parquet")) if snapshot_dir.exists() else []:
        record = file_record(path)
        try:
            frame = pd.read_parquet(path)
        except Exception as exc:  # corrupt/partial archives are evidence, not a queue crash
            record.update({"row_count": 0, "read_status": "error", "read_error": str(exc)})
            records.append(record)
            continue
        record.update({"row_count": int(len(frame)), "read_status": "ok"})
        records.append(record)
        if frame.empty or "ticker" not in frame.columns:
            continue
        d = frame.copy()
        d["ticker"] = d["ticker"].astype(str).map(normalize_ticker)
        d["_snapshot_ts"] = snapshot_date_column(d)
        d["_snapshot_path"] = display_path(path)
        frames.append(d[d["ticker"].ne("")])
    return (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()), records


def latest_snapshot_maps(history: pd.DataFrame) -> tuple[dict[str, str], dict[str, str]]:
    if history.empty or "ticker" not in history.columns:
        return {}, {}
    d = history.copy().sort_values(["ticker", "_snapshot_ts"], kind="stable", na_position="first")
    observed_rows = d.groupby("ticker", as_index=False).tail(1)
    observed = {
        str(row["ticker"]): "" if pd.isna(row["_snapshot_ts"]) else row["_snapshot_ts"].date().isoformat()
        for _, row in observed_rows.iterrows()
    }
    if "has_forward_estimate" not in d.columns:
        return observed, {}
    success_mask = pd.to_numeric(d["has_forward_estimate"], errors="coerce").fillna(0).gt(0)
    success_rows = d.loc[success_mask].groupby("ticker", as_index=False).tail(1)
    successful = {
        str(row["ticker"]): "" if pd.isna(row["_snapshot_ts"]) else row["_snapshot_ts"].date().isoformat()
        for _, row in success_rows.iterrows()
    }
    return observed, successful


def parse_as_of_date(value: str) -> date:
    if not value:
        return datetime.now(timezone.utc).date()
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        raise ValueError(f"invalid as_of_date: {value}")
    return parsed.date()


def aggregate_source_hash(records: list[dict[str, Any]]) -> str:
    lines = [
        f"{record.get('path', '')}|{record.get('sha256', '')}|{record.get('modified_at_utc', '')}"
        for record in records
    ]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def exact_universe_is_valid(tickers: list[str], expected_count: int) -> bool:
    placeholders = [ticker for ticker in tickers if ticker in NON_EQUITY_PLACEHOLDERS]
    eligible = [ticker for ticker in tickers if ticker not in NON_EQUITY_PLACEHOLDERS]
    return bool(
        len(tickers) == expected_count
        and len(placeholders) == 1
        and len(eligible) == expected_count - 1
    )


def checkpoint_is_valid(
    checkpoint_payload: dict[str, Any],
    canonical_record: dict[str, Any],
    canonical_tickers: list[str],
    expected_count: int,
) -> bool:
    universe = checkpoint_payload.get("universe", {})
    expected_hash = universe.get("canonical_snapshot", {}).get("sha256", "")
    checkpoint_placeholder_values = universe.get("non_equity_placeholder_tickers", [])
    if not isinstance(checkpoint_placeholder_values, list):
        return False
    checkpoint_placeholders = [normalize_ticker(ticker) for ticker in checkpoint_placeholder_values]
    canonical_placeholders = [ticker for ticker in canonical_tickers if ticker in NON_EQUITY_PLACEHOLDERS]
    try:
        return bool(
            checkpoint_payload.get("schema_version") == CHECKPOINT_SCHEMA_VERSION
            and int(universe.get("expected_ticker_count", -1)) == expected_count
            and int(universe.get("ticker_count", -1)) == expected_count
            and int(universe.get("eligible_ticker_count", -1)) == expected_count - 1
            and int(universe.get("non_equity_placeholder_ticker_count", -1)) == 1
            and len(checkpoint_placeholders) == 1
            and checkpoint_placeholders[0] in NON_EQUITY_PLACEHOLDERS
            and checkpoint_placeholders == canonical_placeholders
            and exact_universe_is_valid(canonical_tickers, expected_count)
            and canonical_record.get("sha256")
            and canonical_record.get("sha256") == expected_hash
        )
    except (TypeError, ValueError):
        return False


def selection_sort_key(row: dict[str, Any], priority: set[str]) -> tuple[int, int, str, str]:
    last_selected = str(row.get("last_selected_at_utc") or "")
    return (
        0 if row["ticker"] in priority else 1,
        0 if not last_selected else 1,
        last_selected,
        row["ticker"],
    )


def select_bounded(
    rows: list[dict[str, Any]],
    *,
    limit: int,
    priority: set[str],
    reason: str,
    selected: dict[str, str],
) -> None:
    if limit <= 0:
        return
    candidates = sorted(rows, key=lambda row: selection_sort_key(row, priority))[:limit]
    for row in candidates:
        selected.setdefault(row["ticker"], reason)


def render_report(payload: dict[str, Any]) -> str:
    states = payload.get("queue_state_counts", {})
    reasons = payload.get("selection_reason_counts", {})
    source = payload.get("universe_source", {})
    canonical = payload.get("canonical_universe", {})
    selected = payload.get("selected_tickers", [])
    lines = [
        "# Forward Estimate Collection Queue",
        "",
        f"- Status: `{payload.get('status', '')}`",
        f"- Generated: `{payload.get('generated_at_utc', '')}`",
        f"- As-of date: `{payload.get('as_of_date', '')}`",
        f"- Universe: {payload.get('current_universe_ticker_count', 0)} / {payload.get('expected_universe_ticker_count', 0)} tickers",
        f"- Vendor-eligible: {payload.get('eligible_universe_ticker_count', 0)}; placeholders excluded: {payload.get('non_equity_placeholder_ticker_count', 0)}",
        f"- Universe source mode: `{payload.get('universe_source_mode', '')}`",
        f"- Source: `{source.get('path', '')}`",
        f"- Source SHA-256: `{source.get('sha256', '')}`",
        f"- Source modified UTC: `{source.get('modified_at_utc', '')}`",
        f"- Source ingested UTC: `{payload.get('universe_source_ingested_at_utc', '')}`",
        f"- Canonical SHA-256: `{canonical.get('sha256', '')}`",
        f"- Snapshot source aggregate SHA-256: `{payload.get('snapshot_source_aggregate_sha256', '')}`",
        f"- Selected: {payload.get('output_ticker_count', 0)}",
        f"- Fresh successful snapshots reused: {states.get('fresh_success_reused', 0)}",
        f"- Rotation checkpoint policy: `{payload.get('selection_checkpoint_policy', '')}`",
        "- Contract: research-only, forward-only, missing vendor coverage neutral, no historical backfill",
        "",
        "## Queue state counts",
        "",
    ]
    for key in sorted(states):
        lines.append(f"- `{key}`: {states[key]}")
    lines.extend(["", "## Selected reason counts", ""])
    if reasons:
        for key in sorted(reasons):
            lines.append(f"- `{key}`: {reasons[key]}")
    else:
        lines.append("- none; every current-universe ticker has a fresh successful snapshot")
    lines.extend(
        [
            "",
            "## Selected ticker preview",
            "",
            ", ".join(selected[:40]) if selected else "None.",
            "",
            "## Output schema",
            "",
            "- `incremental_universe.csv`: selected ticker-only collector input.",
            "- `collection_queue.csv`: one row per canonical-universe ticker with state, action, last success, and retry checkpoint fields.",
            "- `collection_checkpoint.json`: durable canonical-universe identity plus per-ticker selection state; restored with the snapshot archive.",
            "- `incremental_universe_summary.json`: source hashes/timestamps, queue counts, safety flags, and file identities.",
            "",
        ]
    )
    return "\n".join(lines)


def blocked_payload(
    *,
    generated_at: str,
    as_of: date,
    expected_count: int,
    coverage_record: dict[str, Any],
    canonical_record: dict[str, Any],
    checkpoint_input_record: dict[str, Any],
    output_path: Path,
    queue_path: Path,
    summary_path: Path,
    report_path: Path,
) -> dict[str, Any]:
    write_ticker_csv(output_path, [])
    write_queue_csv(queue_path, [])
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at,
        "as_of_date": as_of.isoformat(),
        "status": "blocked_incomplete_universe",
        "reason": "exact_universe_source_or_valid_checkpoint_not_available",
        "research_only": True,
        "forward_only": True,
        "backtest_acceptance_allowed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "fullrun_dispatched": False,
        "historical_backfill_allowed": False,
        "missing_vendor_coverage_policy": "neutral",
        "expected_universe_ticker_count": expected_count,
        "current_universe_ticker_count": 0,
        "eligible_universe_ticker_count": 0,
        "non_equity_placeholder_ticker_count": 0,
        "universe_source_mode": "blocked",
        "universe_source": coverage_record,
        "canonical_universe": canonical_record,
        "checkpoint_input": checkpoint_input_record,
        "queue_state_counts": {},
        "selection_reason_counts": {},
        "selected_tickers": [],
        "output_ticker_count": 0,
        "output_csv": display_path(output_path),
        "queue_csv": display_path(queue_path),
        "summary_json": display_path(summary_path),
        "report_md": display_path(report_path),
        "acceptance_label": "blocked_no_exact_993_universe",
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(payload), encoding="utf-8")
    payload["output_files"] = {
        "collector_input": file_record(output_path),
        "queue": file_record(queue_path),
        "report": file_record(report_path),
    }
    write_json(summary_path, payload)
    return payload


def build_incremental_universe(
    *,
    shard_dir: str,
    snapshot_dir: str,
    output: str,
    summary: str,
    coverage_file: str = "outputs/free_historical_data_coverage/universe_coverage.csv",
    latest_run: str = "cloud_results/full_rebuild/latest_global_alpha_universe",
    canonical_universe: str = "data_pit/events/earnings_estimates/collection_universe.csv",
    checkpoint: str = "data_pit/events/earnings_estimates/collection_checkpoint.json",
    queue_output: str = "outputs/earnings_estimates_daily/collection_queue.csv",
    report: str = "outputs/earnings_estimates_daily/collection_queue_report.md",
    include_tickers: str = "",
    include_file: str = "",
    expected_universe_count: int = DEFAULT_EXPECTED_UNIVERSE_COUNT,
    as_of_date: str = "",
    stale_after_days: int = 7,
    max_new_tickers: int = 100,
    max_missing_tickers: int = 100,
    max_covered_tickers: int = 300,
    max_retry_tickers: int = 50,
) -> dict[str, Any]:
    excludes = set(DEFAULT_EXCLUDE_TICKERS)
    snapshot_dir_path = repo_path(snapshot_dir)
    output_path = repo_path(output)
    summary_path = repo_path(summary)
    coverage_path = repo_path(coverage_file) if coverage_file else Path("")
    latest_run_path = repo_path(latest_run) if latest_run else Path("")
    canonical_path = repo_path(canonical_universe)
    checkpoint_path = repo_path(checkpoint)
    queue_path = repo_path(queue_output)
    report_path = repo_path(report)
    include_file_path = repo_path(include_file) if include_file else Path("")
    generated_at = utc_now()
    as_of = parse_as_of_date(as_of_date)
    if expected_universe_count <= 0:
        raise ValueError("expected_universe_count must be positive")
    if stale_after_days < 0:
        raise ValueError("stale_after_days must be non-negative")
    limits = {
        "max_new_tickers": max_new_tickers,
        "max_missing_tickers": max_missing_tickers,
        "max_covered_tickers": max_covered_tickers,
        "max_retry_tickers": max_retry_tickers,
    }
    negative_limits = [name for name, value in limits.items() if value < 0]
    if negative_limits:
        raise ValueError(f"selection limits must be non-negative: {', '.join(negative_limits)}")

    coverage_tickers, coverage_record = read_universe_file(coverage_path, excludes) if coverage_file else ([], {"path": "", "exists": False})
    latest_run_tickers, latest_run_record = (
        read_latest_run_universe(latest_run_path, excludes)
        if latest_run
        else ([], {"path": "", "exists": False})
    )
    canonical_tickers, canonical_record_before = read_universe_file(canonical_path, excludes)
    checkpoint_input_record = file_record(checkpoint_path)
    previous_checkpoint = load_json(checkpoint_path)
    prior_valid = checkpoint_is_valid(
        previous_checkpoint,
        canonical_record_before,
        canonical_tickers,
        expected_universe_count,
    )
    coverage_valid = exact_universe_is_valid(coverage_tickers, expected_universe_count)
    latest_run_valid = exact_universe_is_valid(latest_run_tickers, expected_universe_count)
    exact_source_mode = "coverage_file_seed"
    if not coverage_valid and latest_run_valid:
        coverage_tickers = latest_run_tickers
        coverage_record = latest_run_record
        coverage_valid = True
        exact_source_mode = "latest_run_seed"
    elif not coverage_valid:
        coverage_record = {**coverage_record, "latest_run_fallback": latest_run_record}

    if coverage_valid:
        current_universe = coverage_tickers
        universe_source_mode = exact_source_mode
        previous_provenance = previous_checkpoint.get("universe", {}).get("source", {}) if prior_valid else {}
        if previous_provenance.get("sha256") == coverage_record.get("sha256"):
            source_ingested_at = str(previous_provenance.get("ingested_at_utc") or generated_at)
        else:
            source_ingested_at = generated_at
        source_provenance = {**coverage_record, "ingested_at_utc": source_ingested_at}
        write_ticker_csv(canonical_path, current_universe)
    elif prior_valid:
        current_universe = canonical_tickers
        universe_source_mode = "checkpointed_canonical_reuse"
        source_provenance = dict(previous_checkpoint.get("universe", {}).get("source", {}))
        source_ingested_at = str(source_provenance.get("ingested_at_utc") or generated_at)
    else:
        return blocked_payload(
            generated_at=generated_at,
            as_of=as_of,
            expected_count=expected_universe_count,
            coverage_record=coverage_record,
            canonical_record=canonical_record_before,
            checkpoint_input_record=checkpoint_input_record,
            output_path=output_path,
            queue_path=queue_path,
            summary_path=summary_path,
            report_path=report_path,
        )

    canonical_record = file_record(canonical_path)
    canonical_record["ticker_count"] = len(current_universe)
    history, snapshot_records = load_snapshot_history(snapshot_dir_path)
    observed_dates, successful_dates = latest_snapshot_maps(history)
    history_tickers = set(observed_dates)

    previous_states: dict[str, dict[str, Any]] = {}
    previous_universe: set[str] = set()
    if prior_valid:
        for row in previous_checkpoint.get("ticker_states", []):
            ticker = normalize_ticker(row.get("ticker"))
            if ticker:
                previous_states[ticker] = row
                previous_universe.add(ticker)

    inline_priority = parse_inline_tickers(include_tickers, excludes)
    include_file_tickers, include_file_record = (
        read_ticker_file(include_file_path, excludes) if include_file else ([], {"path": "", "exists": False})
    )
    priority = set(inline_priority) | set(include_file_tickers)
    current_set = set(current_universe)
    placeholder_tickers = [ticker for ticker in current_universe if ticker in NON_EQUITY_PLACEHOLDERS]
    eligible_set = current_set - set(placeholder_tickers)

    rows: list[dict[str, Any]] = []
    for ticker in current_universe:
        prior = previous_states.get(ticker, {})
        observed_date = observed_dates.get(ticker, "")
        success_date = successful_dates.get(ticker, "")
        success_age: int | str = ""
        if success_date:
            success_age = (as_of - date.fromisoformat(success_date)).days
        current_new = bool(prior_valid and ticker not in previous_universe)
        is_placeholder = ticker in NON_EQUITY_PLACEHOLDERS
        if is_placeholder:
            state = "non_equity_placeholder"
        elif current_new:
            state = "new_universe"
        elif not observed_date:
            state = "missing"
        elif not success_date:
            state = "uncovered_retry_waiting"
        elif success_age == "" or int(success_age) >= stale_after_days:
            state = "stale_success_due"
        else:
            state = "fresh_success_reused"
        rows.append(
            {
                "ticker": ticker,
                "queue_state": state,
                "queue_action": (
                    "exclude" if state == "non_equity_placeholder" else "reuse" if state == "fresh_success_reused" else "wait"
                ),
                "selected": False,
                "selection_reason": "",
                "eligible_for_vendor_request": not is_placeholder,
                "non_equity_placeholder": is_placeholder,
                "current_universe_new": current_new,
                "priority_hint": ticker in priority,
                "observed_in_snapshot": bool(observed_date),
                "has_successful_snapshot": bool(success_date),
                "latest_observed_date": observed_date,
                "latest_success_date": success_date,
                "successful_snapshot_age_days": success_age,
                "last_selected_at_utc": str(prior.get("last_selected_at_utc") or ""),
                "selection_count": int(prior.get("selection_count") or 0),
                "canonical_universe_sha256": canonical_record.get("sha256", ""),
            }
        )

    selected: dict[str, str] = {}
    select_bounded(
        [row for row in rows if row["queue_state"] == "new_universe"],
        limit=max_new_tickers,
        priority=priority,
        reason="new_universe",
        selected=selected,
    )
    select_bounded(
        [row for row in rows if row["queue_state"] == "missing"],
        limit=max_missing_tickers,
        priority=priority,
        reason="missing_snapshot",
        selected=selected,
    )
    select_bounded(
        [row for row in rows if row["queue_state"] == "stale_success_due"],
        limit=max_covered_tickers,
        priority=priority,
        reason="stale_success_refresh",
        selected=selected,
    )
    select_bounded(
        [row for row in rows if row["queue_state"] == "uncovered_retry_waiting"],
        limit=max_retry_tickers,
        priority=priority,
        reason="slow_rotating_uncovered_retry",
        selected=selected,
    )

    selected_tickers: list[str] = []
    for row in rows:
        reason = selected.get(row["ticker"], "")
        if not reason:
            continue
        row["selected"] = True
        row["selection_reason"] = reason
        row["queue_action"] = "collect"
        selected_tickers.append(row["ticker"])

    write_ticker_csv(output_path, selected_tickers)
    write_queue_csv(queue_path, rows)
    state_counts = dict(sorted(Counter(str(row["queue_state"]) for row in rows).items()))
    reason_counts = dict(sorted(Counter(selected.values()).items()))
    snapshot_source_hash = aggregate_source_hash(snapshot_records)
    status = "ready_for_forward_archive_incremental" if selected_tickers else "complete_no_collection_due"

    checkpoint_payload: dict[str, Any] = {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "updated_at_utc": generated_at,
        "as_of_date": as_of.isoformat(),
        "status": status,
        "research_only": True,
        "forward_only": True,
        "backtest_acceptance_allowed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "fullrun_dispatched": False,
        "historical_backfill_allowed": False,
        "missing_vendor_coverage_policy": "neutral",
        "selection_checkpoint_policy": "advance_only_after_collector_attempt_acknowledgement",
        "last_collection_attempt_ack": previous_checkpoint.get("last_collection_attempt_ack", {}),
        "universe": {
            "expected_ticker_count": expected_universe_count,
            "ticker_count": len(current_universe),
            "eligible_ticker_count": len(eligible_set),
            "non_equity_placeholder_ticker_count": len(placeholder_tickers),
            "non_equity_placeholder_tickers": placeholder_tickers,
            "source_mode": universe_source_mode,
            "source": source_provenance,
            "canonical_snapshot": canonical_record,
        },
        "snapshot_sources": {
            "aggregate_sha256": snapshot_source_hash,
            "file_count": len(snapshot_records),
            "files": snapshot_records,
        },
        "queue_state_counts": state_counts,
        "selection_reason_counts": reason_counts,
        "selected_ticker_count": len(selected_tickers),
        "ticker_states": rows,
    }
    write_json(checkpoint_path, checkpoint_payload)
    checkpoint_output_record = file_record(checkpoint_path)

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "checkpoint_schema_version": CHECKPOINT_SCHEMA_VERSION,
        "generated_at_utc": generated_at,
        "as_of_date": as_of.isoformat(),
        "status": status,
        "research_only": True,
        "forward_only": True,
        "backtest_acceptance_allowed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "fullrun_dispatched": False,
        "collection_mode": "durable_missing_stale_new_plus_rotating_retry",
        "missing_vendor_coverage_policy": "neutral",
        "historical_backfill_allowed": False,
        "selection_checkpoint_policy": "advance_only_after_collector_attempt_acknowledgement",
        "expected_universe_ticker_count": expected_universe_count,
        "current_universe_ticker_count": len(current_universe),
        "eligible_universe_ticker_count": len(eligible_set),
        "non_equity_placeholder_ticker_count": len(placeholder_tickers),
        "non_equity_placeholder_tickers": placeholder_tickers,
        "universe_source_mode": universe_source_mode,
        "universe_source": source_provenance,
        "universe_source_ingested_at_utc": source_ingested_at,
        "canonical_universe": canonical_record,
        "checkpoint_input": checkpoint_input_record,
        "checkpoint_input_valid": prior_valid,
        "checkpoint_output": checkpoint_output_record,
        "snapshot_dir": display_path(snapshot_dir_path),
        "snapshot_source_file_count": len(snapshot_records),
        "snapshot_source_aggregate_sha256": snapshot_source_hash,
        "snapshot_sources": snapshot_records,
        "history_ticker_count": len(history_tickers),
        "successful_snapshot_ticker_count": len(set(successful_dates) & eligible_set),
        "stale_after_days": stale_after_days,
        "queue_state_counts": state_counts,
        "selection_reason_counts": reason_counts,
        "new_universe_ticker_count": state_counts.get("new_universe", 0),
        "retired_universe_ticker_count": len(previous_universe - current_set),
        "fresh_success_reused_ticker_count": state_counts.get("fresh_success_reused", 0),
        "include_inline_ticker_count": len(inline_priority),
        "include_file": include_file_record,
        "priority_ticker_count": len(priority & current_set),
        "priority_outside_universe_ticker_count": len(priority - current_set),
        "max_new_tickers": max_new_tickers,
        "max_missing_tickers": max_missing_tickers,
        "max_covered_tickers": max_covered_tickers,
        "max_retry_tickers": max_retry_tickers,
        "selected_tickers": selected_tickers,
        "output_ticker_count": len(selected_tickers),
        "output_csv": display_path(output_path),
        "queue_csv": display_path(queue_path),
        "checkpoint_json": display_path(checkpoint_path),
        "summary_json": display_path(summary_path),
        "report_md": display_path(report_path),
        "shard_dir": display_path(repo_path(shard_dir)),
        "acceptance_label": "forward_archive_incremental_queue_only",
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(payload), encoding="utf-8")
    payload["output_files"] = {
        "collector_input": file_record(output_path),
        "queue": file_record(queue_path),
        "checkpoint": checkpoint_output_record,
        "canonical_universe": canonical_record,
        "report": file_record(report_path),
    }
    write_json(summary_path, payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shard-dir", default="outputs/forward_estimate_universe_plan_20260709/shards")
    parser.add_argument("--snapshot-dir", default="data_pit/events/earnings_estimates")
    parser.add_argument("--coverage-file", default="outputs/free_historical_data_coverage/universe_coverage.csv")
    parser.add_argument("--latest-run", default="cloud_results/full_rebuild/latest_global_alpha_universe")
    parser.add_argument("--canonical-universe", default="data_pit/events/earnings_estimates/collection_universe.csv")
    parser.add_argument("--checkpoint", default="data_pit/events/earnings_estimates/collection_checkpoint.json")
    parser.add_argument("--output", default="outputs/earnings_estimates_daily/incremental_universe.csv")
    parser.add_argument("--queue-output", default="outputs/earnings_estimates_daily/collection_queue.csv")
    parser.add_argument("--summary", default="outputs/earnings_estimates_daily/incremental_universe_summary.json")
    parser.add_argument("--report", default="outputs/earnings_estimates_daily/collection_queue_report.md")
    parser.add_argument("--include-tickers", default="")
    parser.add_argument("--include-file", default="")
    parser.add_argument("--expected-universe-count", type=int, default=DEFAULT_EXPECTED_UNIVERSE_COUNT)
    parser.add_argument("--as-of-date", default="")
    parser.add_argument("--stale-after-days", type=int, default=7)
    parser.add_argument("--max-new-tickers", type=int, default=100)
    parser.add_argument("--max-missing-tickers", type=int, default=100)
    parser.add_argument("--max-covered-tickers", type=int, default=300)
    parser.add_argument("--max-retry-tickers", type=int, default=50)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_incremental_universe(
        shard_dir=args.shard_dir,
        snapshot_dir=args.snapshot_dir,
        coverage_file=args.coverage_file,
        latest_run=args.latest_run,
        canonical_universe=args.canonical_universe,
        checkpoint=args.checkpoint,
        output=args.output,
        queue_output=args.queue_output,
        summary=args.summary,
        report=args.report,
        include_tickers=args.include_tickers,
        include_file=args.include_file,
        expected_universe_count=args.expected_universe_count,
        as_of_date=args.as_of_date,
        stale_after_days=args.stale_after_days,
        max_new_tickers=args.max_new_tickers,
        max_missing_tickers=args.max_missing_tickers,
        max_covered_tickers=args.max_covered_tickers,
        max_retry_tickers=args.max_retry_tickers,
    )
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 2 if payload["status"] == "blocked_incomplete_universe" else 0


if __name__ == "__main__":
    raise SystemExit(main())
