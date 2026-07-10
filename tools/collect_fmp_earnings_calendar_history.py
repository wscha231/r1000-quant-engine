#!/usr/bin/env python3
"""Collect FMP earnings calendar history into the durable free data lake.

This is a vendor historical snapshot of earnings dates, estimated EPS, and
actual EPS. It is useful for coverage audits and future event studies, but it
is not a point-in-time analyst-estimate revision history. Do not use it as a
historical selection feature unless an event-time normalization gate is added.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests


REPO_ROOT = Path(__file__).resolve().parents[1]
FMP_BASE = "https://financialmodelingprep.com/stable/earnings-calendar"
SCHEMA_VERSION = "fmp-earnings-calendar-history-v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def sanitize_text(value: Any) -> str:
    text = str(value)
    text = re.sub(r"([?&]apikey=)[^&\s]+", r"\1***", text, flags=re.IGNORECASE)
    text = re.sub(r"(?i)(api key[:=]\s*)[A-Za-z0-9._-]+", r"\1***", text)
    return text[:400]


def sha256_text(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def chunk_ranges(start: date, end: date, chunk_days: int) -> list[tuple[date, date]]:
    if chunk_days < 1:
        raise ValueError("chunk_days must be positive")
    ranges: list[tuple[date, date]] = []
    cur = start
    while cur <= end:
        chunk_end = min(end, cur + timedelta(days=chunk_days - 1))
        ranges.append((cur, chunk_end))
        cur = chunk_end + timedelta(days=1)
    return ranges


def first_present(row: dict[str, Any], names: list[str]) -> Any:
    lowered = {str(k).lower(): v for k, v in row.items()}
    for name in names:
        if name in row and row[name] not in [None, ""]:
            return row[name]
        key = name.lower()
        if key in lowered and lowered[key] not in [None, ""]:
            return lowered[key]
    return None


def normalize_rows(rows: list[dict[str, Any]], *, collected_at: str) -> pd.DataFrame:
    out_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(first_present(row, ["symbol", "ticker"]) or "").upper().strip()
        event_date = first_present(row, ["date", "epsDate", "fiscalDateEnding", "period"])
        if not symbol or not event_date:
            continue
        out_rows.append(
            {
                "ticker": symbol,
                "event_date": str(event_date)[:10],
                "time": first_present(row, ["time", "epsTime"]),
                "estimated_eps": first_present(row, ["epsEstimated", "estimatedEPS", "epsEstimate", "estimatedEps"]),
                "actual_eps": first_present(row, ["eps", "actualEPS", "reportedEPS", "actualEps"]),
                "revenue_estimated": first_present(row, ["revenueEstimated", "estimatedRevenue"]),
                "revenue_actual": first_present(row, ["revenue", "actualRevenue"]),
                "fiscal_date_ending": first_present(row, ["fiscalDateEnding"]),
                "updated_from_date": first_present(row, ["updatedFromDate"]),
                "source": "fmp_earnings_calendar",
                "vendor_snapshot_collected_at_utc": collected_at,
                "pit_backtest_allowed": False,
                "pit_usage_label": "vendor_historical_snapshot_not_revision_history",
            }
        )
    frame = pd.DataFrame(out_rows)
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "ticker",
                "event_date",
                "time",
                "estimated_eps",
                "actual_eps",
                "revenue_estimated",
                "revenue_actual",
                "fiscal_date_ending",
                "updated_from_date",
                "source",
                "vendor_snapshot_collected_at_utc",
                "pit_backtest_allowed",
                "pit_usage_label",
            ]
        )
    for col in ["estimated_eps", "actual_eps", "revenue_estimated", "revenue_actual"]:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame["event_date"] = pd.to_datetime(frame["event_date"], errors="coerce").dt.date.astype("string")
    frame = frame.dropna(subset=["event_date"])
    return frame.sort_values(["event_date", "ticker"]).drop_duplicates(["ticker", "event_date"], keep="last")


def fetch_chunk(api_key: str, start: date, end: date, timeout: int) -> str:
    params = {"from": start.isoformat(), "to": end.isoformat(), "apikey": api_key}
    response = requests.get(FMP_BASE, params=params, timeout=timeout)
    response.raise_for_status()
    text = response.text or ""
    head = text[:400]
    if "Error Message" in head or "Invalid API" in head or "Limit Reach" in head:
        raise RuntimeError(sanitize_text(head))
    return text


def load_universe_tickers(path_value: str | None) -> set[str]:
    if not path_value:
        return set()
    path = repo_path(path_value)
    if not path.exists():
        return set()
    frame = pd.read_csv(path, low_memory=False)
    column = "ticker" if "ticker" in frame.columns else frame.columns[0]
    return {str(x).upper().strip() for x in frame[column].dropna().tolist() if str(x).strip()}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def collect(args: argparse.Namespace) -> dict[str, Any]:
    api_key = os.environ.get("FMP_API_KEY", "").strip()
    if not api_key and not args.allow_missing_key:
        raise SystemExit("FMP_API_KEY is required unless --allow-missing-key is set")

    start = parse_date(args.start)
    end = parse_date(args.end) if args.end else datetime.now(timezone.utc).date()
    collected_at = utc_now()
    raw_dir = repo_path(args.raw_dir)
    output = repo_path(args.output)
    summary_path = repo_path(args.summary)
    raw_dir.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    universe = load_universe_tickers(args.universe_file)

    frames: list[pd.DataFrame] = []
    chunk_records: list[dict[str, Any]] = []
    errors: list[str] = []
    ranges = chunk_ranges(start, end, args.chunk_days)
    if args.max_chunks > 0:
        ranges = ranges[: args.max_chunks]

    for idx, (chunk_start, chunk_end) in enumerate(ranges, start=1):
        raw_path = raw_dir / f"earnings_calendar_{chunk_start.isoformat()}_{chunk_end.isoformat()}.json"
        try:
            if api_key:
                text = fetch_chunk(api_key, chunk_start, chunk_end, args.timeout_seconds)
                raw_path.write_text(text, encoding="utf-8")
                if args.sleep_seconds > 0 and idx < len(ranges):
                    time.sleep(args.sleep_seconds)
            elif raw_path.exists():
                text = raw_path.read_text(encoding="utf-8")
            else:
                raise RuntimeError("missing_api_key_and_no_existing_raw")
            payload = json.loads(text)
            rows = payload if isinstance(payload, list) else payload.get("data", []) if isinstance(payload, dict) else []
            frame = normalize_rows([x for x in rows if isinstance(x, dict)], collected_at=collected_at)
            if universe and not frame.empty:
                frame = frame[frame["ticker"].isin(universe)].copy()
            frames.append(frame)
            chunk_records.append(
                {
                    "from": chunk_start.isoformat(),
                    "to": chunk_end.isoformat(),
                    "raw_path": raw_path.as_posix(),
                    "sha256": sha256_text(text),
                    "rows": int(len(frame)),
                }
            )
        except Exception as exc:
            errors.append(f"{chunk_start.isoformat()}_{chunk_end.isoformat()}: {sanitize_text(exc)}")
            if args.max_errors >= 0 and len(errors) > args.max_errors:
                break

    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not combined.empty:
        combined = combined.sort_values(["event_date", "ticker"]).drop_duplicates(["ticker", "event_date"], keep="last")
        combined.to_parquet(output, index=False)

    covered_tickers = int(combined["ticker"].nunique()) if not combined.empty else 0
    summary = {
        "schema_version": SCHEMA_VERSION,
        "collected_at_utc": collected_at,
        "source": "fmp_earnings_calendar",
        "requested_start": start.isoformat(),
        "requested_end": end.isoformat(),
        "chunk_days": int(args.chunk_days),
        "chunks_attempted": len(chunk_records) + len(errors),
        "chunks_succeeded": len(chunk_records),
        "errors": errors,
        "output": output.as_posix(),
        "row_count": int(len(combined)),
        "covered_ticker_count": covered_tickers,
        "universe_filter_count": len(universe),
        "pit_backtest_allowed": False,
        "pit_usage_label": "vendor_historical_snapshot_not_revision_history",
        "note": "Safe for coverage/event audits. Do not use as historical analyst revision feature.",
        "chunks": chunk_records,
        "status": "ok" if not combined.empty and not errors else ("partial" if not combined.empty else "blocked"),
    }
    write_json(summary_path, summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2016-01-01")
    parser.add_argument("--end", default="")
    parser.add_argument("--chunk-days", type=int, default=31)
    parser.add_argument("--max-chunks", type=int, default=0)
    parser.add_argument("--max-errors", type=int, default=20)
    parser.add_argument("--sleep-seconds", type=float, default=1.1)
    parser.add_argument("--timeout-seconds", type=int, default=60)
    parser.add_argument("--universe-file", default="")
    parser.add_argument("--raw-dir", default="data_raw/free/fmp/earnings_calendar")
    parser.add_argument("--output", default="data_pit/events/earnings_calendar_history.parquet")
    parser.add_argument("--summary", default="outputs/free_historical_data_backfill/fmp_earnings_calendar_summary.json")
    parser.add_argument("--allow-missing-key", action="store_true")
    return parser.parse_args()


def main() -> int:
    summary = collect(parse_args())
    return 0 if summary.get("status") in {"ok", "partial"} else 1


if __name__ == "__main__":
    sys.exit(main())
