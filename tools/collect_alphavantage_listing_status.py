#!/usr/bin/env python3
"""Collect Alpha Vantage LISTING_STATUS into the durable free data lake.

The listing lifecycle feed is reference data, not an alpha signal. It is used
to narrow survivorship-bias audits by recording active and delisted symbols,
listing dates, and delisting dates. It does not make Russell 1000 membership
PIT-clean by itself.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests


REPO_ROOT = Path(__file__).resolve().parents[1]
AV_BASE = "https://www.alphavantage.co/query"
SCHEMA_VERSION = "alphavantage-listing-status-v1"


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


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def read_csv_payload(payload: bytes, *, source_state: str, collected_at: str) -> pd.DataFrame:
    text = payload.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    rows = [dict(row) for row in reader]
    if not rows:
        return pd.DataFrame(
            columns=[
                "symbol",
                "name",
                "exchange",
                "asset_type",
                "ipo_date",
                "delisting_date",
                "status",
                "source_state",
                "source",
                "collected_at_utc",
            ]
        )
    frame = pd.DataFrame(rows)
    rename = {
        "symbol": "symbol",
        "name": "name",
        "exchange": "exchange",
        "assetType": "asset_type",
        "asset_type": "asset_type",
        "ipoDate": "ipo_date",
        "ipo_date": "ipo_date",
        "delistingDate": "delisting_date",
        "delisting_date": "delisting_date",
        "status": "status",
    }
    frame = frame.rename(columns={col: rename.get(col, col) for col in frame.columns})
    for col in ["symbol", "name", "exchange", "asset_type", "ipo_date", "delisting_date", "status"]:
        if col not in frame.columns:
            frame[col] = ""
    frame["symbol"] = frame["symbol"].astype(str).str.upper().str.strip()
    frame["source_state"] = source_state
    frame["source"] = "alphavantage_listing_status"
    frame["collected_at_utc"] = collected_at
    frame["ipo_date"] = pd.to_datetime(frame["ipo_date"], errors="coerce").dt.date.astype("string")
    frame["delisting_date"] = pd.to_datetime(frame["delisting_date"], errors="coerce").dt.date.astype("string")
    return frame[
        [
            "symbol",
            "name",
            "exchange",
            "asset_type",
            "ipo_date",
            "delisting_date",
            "status",
            "source_state",
            "source",
            "collected_at_utc",
        ]
    ].drop_duplicates(["symbol", "source_state"], keep="last")


def fetch_listing_status(api_key: str, *, state: str, timeout: int) -> bytes:
    params = {"function": "LISTING_STATUS", "state": state, "apikey": api_key}
    response = requests.get(AV_BASE, params=params, timeout=timeout)
    response.raise_for_status()
    content = response.content or b""
    text_head = content[:400].decode("utf-8", errors="replace")
    if "Error Message" in text_head or "Invalid API call" in text_head:
        raise RuntimeError(sanitize_text(text_head))
    if "Thank you for using Alpha Vantage" in text_head and "frequency" in text_head.lower():
        raise RuntimeError(sanitize_text(text_head))
    return content


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def collect(args: argparse.Namespace) -> dict[str, Any]:
    api_key = os.environ.get("ALPHAVANTAGE_API_KEY", "").strip()
    if not api_key and not args.allow_missing_key:
        raise SystemExit("ALPHAVANTAGE_API_KEY is required unless --allow-missing-key is set")

    collected_at = utc_now()
    stamp = args.asof_date or collected_at[:10]
    raw_dir = repo_path(args.raw_dir)
    output = repo_path(args.output)
    summary_path = repo_path(args.summary)
    raw_dir.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)

    frames: list[pd.DataFrame] = []
    raw_records: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []
    for state in ["active", "delisted"]:
        raw_path = raw_dir / f"listing_status_{state}_{stamp}.csv"
        try:
            if api_key:
                payload = fetch_listing_status(api_key, state=state, timeout=args.timeout_seconds)
                raw_path.write_bytes(payload)
            elif raw_path.exists():
                payload = raw_path.read_bytes()
            else:
                raise RuntimeError("missing_api_key_and_no_existing_raw")
            frame = read_csv_payload(payload, source_state=state, collected_at=collected_at)
            frames.append(frame)
            if state == "delisted" and len(frame) == 0:
                warnings.append("delisted_state_returned_zero_rows")
            if len(payload) <= 2:
                warnings.append(f"{state}_payload_too_small:{len(payload)}_bytes")
            raw_records.append(
                {
                    "state": state,
                    "raw_path": raw_path.as_posix(),
                    "bytes": len(payload),
                    "sha256": sha256_bytes(payload),
                    "rows": int(len(frame)),
                }
            )
        except Exception as exc:
            errors.append(f"{state}: {sanitize_text(exc)}")

    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not combined.empty:
        combined = combined.sort_values(["symbol", "source_state"]).drop_duplicates(["symbol", "source_state"], keep="last")
        combined.to_parquet(output, index=False)

    summary = {
        "schema_version": SCHEMA_VERSION,
        "collected_at_utc": collected_at,
        "asof_date": stamp,
        "source": "alphavantage_LISTING_STATUS",
        "pit_usage_label": "reference_lifecycle_proxy_not_index_membership",
        "production_membership_clean": False,
        "output": output.as_posix(),
        "raw_records": raw_records,
        "row_count": int(len(combined)),
        "active_rows": int((combined["source_state"] == "active").sum()) if not combined.empty else 0,
        "delisted_rows": int((combined["source_state"] == "delisted").sum()) if not combined.empty else 0,
        "errors": errors,
        "warnings": warnings,
        "status": (
            "ok"
            if combined is not None and not combined.empty and not errors and not warnings
            else ("partial" if combined is not None and not combined.empty else "blocked")
        ),
    }
    write_json(summary_path, summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", default="data_raw/free/alpha_vantage/listing_status")
    parser.add_argument("--output", default="data_pit/free/av_listing_status.parquet")
    parser.add_argument("--summary", default="outputs/free_historical_data_backfill/listing_status_summary.json")
    parser.add_argument("--asof-date", default="")
    parser.add_argument("--timeout-seconds", type=int, default=60)
    parser.add_argument("--allow-missing-key", action="store_true")
    return parser.parse_args()


def main() -> int:
    summary = collect(parse_args())
    return 0 if summary.get("status") in {"ok", "partial"} else 1


if __name__ == "__main__":
    sys.exit(main())
