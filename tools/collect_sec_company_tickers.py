#!/usr/bin/env python3
"""Materialize the authoritative SEC ticker/CIK reference with provenance.

The SEC reference is an identity snapshot, not point-in-time index membership.
Raw response bytes are preserved so the source hash can be reproduced.  The
normalized table is safe only from ``available_from`` onward.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "sec-company-tickers-reference-v1"
SOURCE_URL = "https://www.sec.gov/files/company_tickers.json"
PIT_USAGE_LABEL = "reference_identity_snapshot_not_index_membership"


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def file_timestamp(path: Path) -> str:
    return (
        datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def http_timestamp(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = parsedate_to_datetime(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError, OverflowError):
        return ""


def normalize_ticker(value: Any) -> str:
    text = str(value or "").upper().strip().replace(".", "-")
    return re.sub(r"[^A-Z0-9-]", "", text)


def normalize_cik(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    integer_like = re.fullmatch(r"(\d+)(?:\.0+)?", text)
    digits = integer_like.group(1) if integer_like else re.sub(r"\D", "", text)
    return digits.zfill(10) if digits else ""


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def parse_company_tickers(
    payload: bytes,
    *,
    source_url: str,
    source_sha256: str,
    available_from: str,
    ingested_at_utc: str,
) -> pd.DataFrame:
    data = json.loads(payload.decode("utf-8-sig"))
    items = data.values() if isinstance(data, dict) else data if isinstance(data, list) else []
    rows: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        ticker_raw = str(item.get("ticker") or "").upper().strip()
        ticker = normalize_ticker(ticker_raw)
        cik10 = normalize_cik(item.get("cik_str"))
        if not ticker or not cik10:
            continue
        rows.append(
            {
                "ticker": ticker,
                "ticker_raw": ticker_raw,
                "cik10": cik10,
                "company_name": str(item.get("title") or "").strip(),
                "source": "sec_company_tickers",
                "source_url": source_url,
                "source_sha256": source_sha256,
                "available_from": available_from,
                "ingested_at_utc": ingested_at_utc,
                "pit_usage_label": PIT_USAGE_LABEL,
            }
        )
    if not rows:
        return pd.DataFrame(
            columns=[
                "ticker",
                "ticker_raw",
                "cik10",
                "company_name",
                "source",
                "source_url",
                "source_sha256",
                "available_from",
                "ingested_at_utc",
                "pit_usage_label",
            ]
        )
    return (
        pd.DataFrame(rows)
        .drop_duplicates(["ticker", "cik10"], keep="first")
        .sort_values(["ticker", "cik10"])
        .reset_index(drop=True)
    )


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def staging_path(path: Path) -> Path:
    """Create a same-directory staging file suitable for atomic replacement."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(fd)
    return Path(name)


def collect(args: argparse.Namespace) -> dict[str, Any]:
    raw_path = repo_path(args.raw_output)
    manifest_path = repo_path(args.manifest_output)
    reference_path = repo_path(args.reference_output)
    summary_path = repo_path(args.summary)
    raw_path.parent.mkdir(parents=True, exist_ok=True)

    fetched = bool(args.refresh or not raw_path.exists())
    ingested_at_utc = utc_now()
    http_last_modified = ""
    http_date = ""
    http_etag = ""
    available_from_basis = ""

    if fetched:
        user_agent = (args.user_agent or os.environ.get("SEC_USER_AGENT") or "").strip()
        if not user_agent:
            user_agent = "R1000QuantEngine research contact@example.com"
        response = requests.get(
            args.source_url,
            headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
            timeout=float(args.timeout_seconds),
        )
        response.raise_for_status()
        raw_bytes = response.content
        http_last_modified = str(response.headers.get("Last-Modified") or "")
        http_date = str(response.headers.get("Date") or "")
        http_etag = str(response.headers.get("ETag") or "")
        available_from = http_timestamp(http_last_modified)
        if available_from:
            available_from_basis = "http_last_modified"
        else:
            available_from = http_timestamp(http_date)
            available_from_basis = "http_date" if available_from else "ingested_at_utc"
        available_from = available_from or ingested_at_utc
    else:
        raw_bytes = raw_path.read_bytes()
        previous = load_json(manifest_path)
        ingested_at_utc = str(previous.get("ingested_at_utc") or file_timestamp(raw_path))
        available_from = str(previous.get("available_from") or file_timestamp(raw_path))
        available_from_basis = str(previous.get("available_from_basis") or "local_file_mtime")
        http_last_modified = str(previous.get("http_last_modified") or "")
        http_date = str(previous.get("http_date") or "")
        http_etag = str(previous.get("http_etag") or "")

    source_sha256 = sha256_bytes(raw_bytes)
    reference = parse_company_tickers(
        raw_bytes,
        source_url=args.source_url,
        source_sha256=source_sha256,
        available_from=available_from,
        ingested_at_utc=ingested_at_utc,
    )
    if reference.empty:
        raise ValueError("SEC company_tickers response contained no valid ticker/CIK rows")
    if len(reference) < int(args.minimum_row_count):
        raise ValueError(
            "SEC company_tickers response failed minimum-row sanity check: "
            f"{len(reference)} < {int(args.minimum_row_count)}"
        )

    candidate_counts = reference.groupby("ticker")["cik10"].nunique()
    ambiguous = sorted(candidate_counts[candidate_counts.gt(1)].index.tolist())
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "source": "sec_company_tickers",
        "source_url": args.source_url,
        "source_sha256": source_sha256,
        "source_bytes": len(raw_bytes),
        "http_last_modified": http_last_modified,
        "http_date": http_date,
        "http_etag": http_etag,
        "available_from": available_from,
        "available_from_basis": available_from_basis,
        "ingested_at_utc": ingested_at_utc,
        "raw_path": raw_path.as_posix(),
        "reference_path": reference_path.as_posix(),
        "row_count": int(len(reference)),
        "minimum_row_count": int(args.minimum_row_count),
        "unique_ticker_count": int(reference["ticker"].nunique()) if not reference.empty else 0,
        "ambiguous_ticker_count": len(ambiguous),
        "ambiguous_tickers": ambiguous,
        "pit_usage_label": PIT_USAGE_LABEL,
        "pit_universe_label_clean": False,
        "production_promotion_allowed": False,
    }

    staged: list[tuple[Path, Path]] = []
    try:
        if fetched:
            staged_raw = staging_path(raw_path)
            staged.append((staged_raw, raw_path))
            staged_raw.write_bytes(raw_bytes)
        staged_reference = staging_path(reference_path)
        staged.append((staged_reference, reference_path))
        if reference_path.suffix.lower() == ".csv":
            reference.to_csv(staged_reference, index=False)
        else:
            reference.to_parquet(staged_reference, index=False)
        staged_manifest = staging_path(manifest_path)
        staged.append((staged_manifest, manifest_path))
        write_json(staged_manifest, manifest)

        # The manifest is the commit marker and is replaced last, only after
        # every staged artifact has been parsed and serialized successfully.
        for staged_path, destination in staged:
            os.replace(staged_path, destination)
    finally:
        for staged_path, _ in staged:
            if staged_path.exists():
                staged_path.unlink()

    summary = {
        **manifest,
        "status": "completed",
        "fetched_this_run": fetched,
        "manifest_path": manifest_path.as_posix(),
    }
    write_json(summary_path, summary)
    print(json.dumps(summary, indent=2, sort_keys=True, default=str))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-url", default=SOURCE_URL)
    parser.add_argument("--raw-output", default="data_raw/free/sec/company_tickers.json")
    parser.add_argument("--manifest-output", default="data_raw/free/sec/company_tickers_manifest.json")
    parser.add_argument("--reference-output", default="data_pit/free/sec_company_tickers.parquet")
    parser.add_argument("--summary", default="outputs/free_historical_data_backfill/sec_company_tickers_summary.json")
    parser.add_argument("--user-agent", default="")
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--minimum-row-count", type=int, default=1000)
    parser.add_argument("--refresh", action="store_true")
    return parser.parse_args()


def main() -> int:
    summary = collect(parse_args())
    return 0 if summary.get("status") == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
