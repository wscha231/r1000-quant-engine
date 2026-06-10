#!/usr/bin/env python3
"""Audit data readiness before relying on a full rebuild or broker replay.

This tool is intentionally diagnostic. It does not mutate data and it does not
make strategy decisions. It answers the operational questions that caused the
recent stale replay problem:

* Is the free price cache populated and fresh enough?
* Is the SEC companyfacts archive present in the canonical free-data path?
* Do the latest target books and operating books reach the latest target date?
* Did the run leave a dated target snapshot that future replays can use?
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent


DATE_COLUMNS = [
    "rebalance_date",
    "feature_date",
    "as_of_date",
    "last_trade_date",
    "date",
    "Date",
]


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def json_default(value: Any) -> Any:
    if isinstance(value, (datetime, pd.Timestamp)):
        if pd.isna(value):
            return None
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=json_default) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def file_stats(path: Path) -> dict[str, Any]:
    exists = path.exists()
    if not exists:
        return {"exists": False, "path": str(path)}
    stat = path.stat()
    return {
        "exists": True,
        "path": str(path),
        "size_bytes": int(stat.st_size),
        "modified_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    }


def count_csv_rows(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        with path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.reader(fh)
            rows = sum(1 for _ in reader)
    except Exception:
        return 0
    return max(rows - 1, 0)


def read_csv_light(path: Path, columns: list[str] | None = None) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, usecols=columns, low_memory=False) if columns else pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def latest_date_from_columns(frame: pd.DataFrame, columns: list[str] = DATE_COLUMNS) -> str:
    dates: list[pd.Timestamp] = []
    if frame.empty:
        return ""
    for col in columns:
        if col not in frame.columns:
            continue
        parsed = pd.to_datetime(frame[col], errors="coerce").dropna()
        if not parsed.empty:
            dates.append(pd.Timestamp(parsed.max()).normalize())
    if not dates:
        return ""
    return max(dates).date().isoformat()


def min_date_from_columns(frame: pd.DataFrame, columns: list[str] = DATE_COLUMNS) -> str:
    dates: list[pd.Timestamp] = []
    if frame.empty:
        return ""
    for col in columns:
        if col not in frame.columns:
            continue
        parsed = pd.to_datetime(frame[col], errors="coerce").dropna()
        if not parsed.empty:
            dates.append(pd.Timestamp(parsed.min()).normalize())
    if not dates:
        return ""
    return min(dates).date().isoformat()


def csv_summary(path: Path) -> dict[str, Any]:
    frame = read_csv_light(path)
    weight_sum = None
    ticker_count = None
    if not frame.empty and "weight" in frame.columns:
        weight_sum = float(pd.to_numeric(frame["weight"], errors="coerce").fillna(0.0).sum())
    if not frame.empty and "ticker" in frame.columns:
        ticker_count = int(frame["ticker"].astype(str).str.upper().nunique())
    return {
        "path": str(path),
        "exists": path.exists(),
        "row_count": int(len(frame)) if not frame.empty else count_csv_rows(path),
        "min_date": min_date_from_columns(frame),
        "max_date": latest_date_from_columns(frame),
        "ticker_count": ticker_count,
        "weight_sum": weight_sum,
    }


def parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).date()


def days_old(value: Any, today: date | None = None) -> int | None:
    dt = parse_date(value)
    if dt is None:
        return None
    base = today or datetime.now(timezone.utc).date()
    return int((base - dt).days)


def price_cache_summary(price_cache: Path, free_data_root: Path) -> dict[str, Any]:
    files = sorted(path for path in price_cache.glob("*.parquet") if path.is_file()) if price_cache.exists() else []
    root_manifest = read_json(price_cache / "replay_price_cache_manifest.json")
    free_manifest = read_json(free_data_root / "prices" / "replay_price_cache_manifest.json")
    manifest = free_manifest or root_manifest
    latest_mtime = ""
    if files:
        latest = max(path.stat().st_mtime for path in files)
        latest_mtime = datetime.fromtimestamp(latest, timezone.utc).isoformat()
    return {
        "cache_path": str(price_cache),
        "file_count": int(len(files)),
        "latest_file_modified_utc": latest_mtime,
        "root_manifest": {
            "path": str(price_cache / "replay_price_cache_manifest.json"),
            "exists": bool(root_manifest),
            "start": root_manifest.get("start"),
            "end": root_manifest.get("end"),
            "ticker_count": root_manifest.get("ticker_count"),
            "failed_count": root_manifest.get("failed_count"),
            "status": root_manifest.get("status"),
        },
        "free_data_manifest": {
            "path": str(free_data_root / "prices" / "replay_price_cache_manifest.json"),
            "exists": bool(free_manifest),
            "start": free_manifest.get("start"),
            "end": free_manifest.get("end"),
            "ticker_count": free_manifest.get("ticker_count"),
            "failed_count": free_manifest.get("failed_count"),
            "status": free_manifest.get("status"),
        },
        "selected_manifest_end": manifest.get("end"),
        "selected_manifest_ticker_count": manifest.get("ticker_count"),
        "selected_manifest_failed_count": manifest.get("failed_count"),
        "selected_manifest_status": manifest.get("status"),
    }


def fundamentals_summary(free_data_root: Path, latest_run: Path) -> dict[str, Any]:
    candidates = [
        free_data_root / "sec" / "companyfacts.zip",
        REPO_ROOT / "companyfacts.zip",
        latest_run / "companyfacts.zip",
        latest_run / "outputs" / "companyfacts.zip",
    ]
    return {
        "canonical_path": str(free_data_root / "sec" / "companyfacts.zip"),
        "candidates": [file_stats(path) for path in candidates],
        "canonical_available": (free_data_root / "sec" / "companyfacts.zip").exists(),
        "any_available": any(path.exists() for path in candidates),
    }


def macro_summary(free_data_root: Path, latest_run: Path) -> dict[str, Any]:
    candidates = [
        free_data_root / "macro",
        REPO_ROOT / "cache_macro",
        latest_run / "macro",
        latest_run / "macro_policy_engine",
    ]
    rows: list[dict[str, Any]] = []
    for path in candidates:
        if path.exists() and path.is_dir():
            file_count = sum(1 for item in path.rglob("*") if item.is_file())
            rows.append({"path": str(path), "exists": True, "file_count": int(file_count)})
        else:
            rows.append({"path": str(path), "exists": path.exists(), "file_count": 0})
    return {"candidates": rows, "any_available": any(row["file_count"] > 0 for row in rows)}


def target_snapshot_summary(latest_run: Path) -> dict[str, Any]:
    root = latest_run / "target_snapshots"
    latest_manifest = read_json(root / "latest_manifest.json")
    dated_dirs = sorted([path for path in root.iterdir() if path.is_dir()]) if root.exists() else []
    return {
        "path": str(root),
        "exists": root.exists(),
        "dated_snapshot_count": int(len(dated_dirs)),
        "latest_manifest_exists": bool(latest_manifest),
        "latest_snapshot_date": latest_manifest.get("snapshot_date", ""),
        "latest_manifest_path": str(root / "latest_manifest.json"),
    }


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    price_cache = repo_path(args.price_cache)
    free_data_root = repo_path(args.free_data_root)
    coverage_path = repo_path(args.coverage)
    manifest_path = repo_path(args.manifest)

    prices = price_cache_summary(price_cache, free_data_root)
    fundamentals = fundamentals_summary(free_data_root, latest_run)
    macro = macro_summary(free_data_root, latest_run)
    coverage = read_json(coverage_path)
    manifest = read_json(manifest_path)

    scored = csv_summary(latest_run / "scored_latest.csv")
    main_latest = csv_summary(latest_run / "portfolio_latest.csv")
    concentrated_latest = csv_summary(latest_run / "concentrated_portfolio_latest.csv")
    main_history = csv_summary(latest_run / "reports" / "main_monthly_weights.csv")
    concentrated_history = csv_summary(latest_run / "reports" / "concentrated_strategy_holdings.csv")
    operating_main = csv_summary(latest_run / "reports" / "operating_main_target_book.csv")
    operating_concentrated = csv_summary(latest_run / "reports" / "operating_concentrated_target_book.csv")
    operating_summary = read_json(latest_run / "reports" / "operating_target_books_summary.json")
    snapshots = target_snapshot_summary(latest_run)

    blockers: list[str] = []
    warnings: list[str] = []
    next_actions: list[str] = []

    price_file_count = int(prices.get("file_count") or 0)
    if price_file_count < int(args.min_price_files):
        warnings.append(f"price cache has only {price_file_count} parquet files; collector or Drive restore is required before skip_collector runs")
        next_actions.append("Restore/cache price parquet files from Google Drive or run tools/build_replay_price_cache.py before replay.")
    manifest_age = days_old(prices.get("selected_manifest_end"))
    if manifest_age is None:
        warnings.append("price cache manifest end date is missing")
    elif manifest_age > int(args.max_stale_days):
        warnings.append(f"price cache manifest is stale by {manifest_age} calendar days")
        next_actions.append("Run free_data_daily_update or a collector refresh after the latest market close.")

    if not fundamentals["canonical_available"]:
        warnings.append("canonical data_raw/free/sec/companyfacts.zip is missing")
        next_actions.append("Restore root companyfacts.zip into data_raw/free/sec or run the SEC companyfacts bootstrap.")
    if not fundamentals["any_available"]:
        blockers.append("no SEC companyfacts archive was found in canonical, root, or latest-run paths")

    if int(scored.get("row_count") or 0) < int(args.min_scored_rows):
        blockers.append(f"scored_latest.csv row count is below threshold: {scored.get('row_count')}")
    if not main_latest.get("exists"):
        blockers.append("portfolio_latest.csv is missing")
    if not concentrated_latest.get("exists"):
        blockers.append("concentrated_portfolio_latest.csv is missing")

    latest_target_dates = [
        parse_date(main_latest.get("max_date")),
        parse_date(concentrated_latest.get("max_date")),
    ]
    latest_target_dates = [dt for dt in latest_target_dates if dt is not None]
    latest_target_date = max(latest_target_dates).isoformat() if latest_target_dates else ""
    for portfolio, book in [("main", operating_main), ("concentrated", operating_concentrated)]:
        if not book.get("exists"):
            warnings.append(f"{portfolio} operating target book is missing")
            continue
        book_dt = parse_date(book.get("max_date"))
        target_dt = parse_date(latest_target_date)
        if book_dt and target_dt and book_dt < target_dt:
            blockers.append(f"{portfolio} operating target book max date {book_dt} is older than latest target date {target_dt}")

    if not snapshots["latest_manifest_exists"]:
        warnings.append("dated target snapshot archive is missing for this run")
        next_actions.append("Run tools/archive_target_snapshots.py after operating target books are built.")

    known_gaps = coverage.get("known_gaps") or []
    if known_gaps:
        warnings.extend(f"free-data gap: {gap}" for gap in known_gaps)

    ready_for_fullrun = not blockers
    status = "ready" if ready_for_fullrun and not warnings else ("blocked" if blockers else "warn")
    payload = {
        "schema_version": "data-readiness-v1",
        "generated_at_utc": now_utc(),
        "status": status,
        "ready_for_fullrun": bool(ready_for_fullrun),
        "ready_for_skip_collector_replay": bool(ready_for_fullrun and price_file_count >= int(args.min_price_files)),
        "latest_target_date": latest_target_date,
        "latest_run": str(latest_run),
        "price_cache": prices,
        "fundamentals": fundamentals,
        "macro": macro,
        "free_data_coverage": {
            "path": str(coverage_path),
            "exists": bool(coverage),
            "readiness": coverage.get("readiness"),
            "pit_label": coverage.get("pit_label"),
            "known_gaps": known_gaps,
        },
        "free_data_manifest": {
            "path": str(manifest_path),
            "exists": bool(manifest),
            "generated_at_utc": manifest.get("generated_at_utc"),
            "status": manifest.get("status"),
        },
        "latest_outputs": {
            "scored_latest": scored,
            "portfolio_latest": main_latest,
            "concentrated_portfolio_latest": concentrated_latest,
        },
        "target_books": {
            "main_history": main_history,
            "concentrated_history": concentrated_history,
            "operating_main": operating_main,
            "operating_concentrated": operating_concentrated,
            "operating_summary": operating_summary,
        },
        "target_snapshots": snapshots,
        "blockers": blockers,
        "warnings": warnings,
        "next_actions": sorted(set(next_actions)),
    }
    return payload


def render_report(payload: dict[str, Any]) -> str:
    prices = payload.get("price_cache", {})
    latest = payload.get("latest_outputs", {})
    books = payload.get("target_books", {})
    lines = [
        "# Data Readiness Audit",
        "",
        f"- status: `{payload.get('status')}`",
        f"- ready_for_fullrun: `{str(payload.get('ready_for_fullrun')).lower()}`",
        f"- ready_for_skip_collector_replay: `{str(payload.get('ready_for_skip_collector_replay')).lower()}`",
        f"- latest_target_date: `{payload.get('latest_target_date') or ''}`",
        "",
        "## Prices",
        "",
        f"- cache files: `{prices.get('file_count')}`",
        f"- manifest end: `{prices.get('selected_manifest_end') or ''}`",
        f"- manifest tickers: `{prices.get('selected_manifest_ticker_count') or ''}`",
        "",
        "## Latest Outputs",
        "",
        "| File | Rows | Max date | Weight sum |",
        "| --- | ---: | --- | ---: |",
    ]
    for name in ["scored_latest", "portfolio_latest", "concentrated_portfolio_latest"]:
        row = latest.get(name, {})
        lines.append(
            f"| {name} | {row.get('row_count', 0)} | {row.get('max_date') or ''} | {row.get('weight_sum') if row.get('weight_sum') is not None else ''} |"
        )
    lines.extend(["", "## Target Books", "", "| Book | Rows | Min date | Max date | Weight sum |", "| --- | ---: | --- | --- | ---: |"])
    for name in ["main_history", "concentrated_history", "operating_main", "operating_concentrated"]:
        row = books.get(name, {})
        lines.append(
            f"| {name} | {row.get('row_count', 0)} | {row.get('min_date') or ''} | {row.get('max_date') or ''} | {row.get('weight_sum') if row.get('weight_sum') is not None else ''} |"
        )
    lines.extend(["", "## Blockers", ""])
    blockers = payload.get("blockers") or []
    lines.extend([f"- {item}" for item in blockers] if blockers else ["- none"])
    lines.extend(["", "## Warnings", ""])
    warnings = payload.get("warnings") or []
    lines.extend([f"- {item}" for item in warnings] if warnings else ["- none"])
    lines.extend(["", "## Next Actions", ""])
    actions = payload.get("next_actions") or []
    lines.extend([f"- {item}" for item in actions] if actions else ["- none"])
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--free-data-root", default="data_raw/free")
    parser.add_argument("--coverage", default="data_pit/free/coverage_audit.json")
    parser.add_argument("--manifest", default="manifests/free_data/latest_manifest.json")
    parser.add_argument("--output-dir", default="outputs/data_readiness")
    parser.add_argument("--max-stale-days", type=int, default=3)
    parser.add_argument("--min-price-files", type=int, default=500)
    parser.add_argument("--min-scored-rows", type=int, default=500)
    parser.add_argument("--strict", action="store_true", help="Exit nonzero when blockers are present.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_payload(args)
    output_dir = repo_path(args.output_dir)
    write_json(output_dir / "summary.json", payload)
    write_text(output_dir / "report.md", render_report(payload))
    print(json.dumps(payload, indent=2, sort_keys=True, default=json_default))
    if args.strict and payload.get("blockers"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
