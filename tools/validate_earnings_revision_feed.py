#!/usr/bin/env python3
"""Validate the raw PIT earnings revision / guidance feed contract.

This tool does not build signals, select stocks, or change policy. It only
checks whether a vendor/manual export is safe enough to pass into
build_earnings_revision_signals.py.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_INPUT = "data_raw/events/earnings_revisions.csv"
DEFAULT_SUMMARY = "outputs/earnings_revision_feed_contract/summary.json"
SCHEMA_VERSION = "earnings-revision-feed-contract-v1"

REQUIRED_COLUMNS = ["ticker", "available_from"]
RECOMMENDED_COLUMNS = [
    "fiscal_period",
    "estimate_date",
    "eps_estimate",
    "revenue_estimate",
    "guidance_direction",
    "source",
]
EVIDENCE_COLUMNS = [
    "eps_estimate",
    "revenue_estimate",
    "margin_estimate",
    "guidance_direction",
    "forward_pe",
]


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _has_nonempty_evidence(frame: pd.DataFrame, column: str) -> bool:
    if column not in frame.columns:
        return False
    values = frame[column].astype("string").fillna("").str.strip()
    return bool(values.ne("").any())


def validate_feed(frame: pd.DataFrame, *, as_of: pd.Timestamp | None = None) -> dict[str, Any]:
    columns = [str(col).strip() for col in frame.columns]
    frame = frame.copy()
    frame.columns = columns
    missing_required = sorted(set(REQUIRED_COLUMNS) - set(columns))
    missing_recommended = sorted(set(RECOMMENDED_COLUMNS) - set(columns))
    evidence_columns_present = [col for col in EVIDENCE_COLUMNS if _has_nonempty_evidence(frame, col)]
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "completed",
        "row_count": int(len(frame)),
        "column_count": int(len(columns)),
        "columns": columns,
        "required_columns": REQUIRED_COLUMNS,
        "recommended_columns": RECOMMENDED_COLUMNS,
        "missing_required_columns": missing_required,
        "missing_recommended_columns": missing_recommended,
        "evidence_columns_present": evidence_columns_present,
        "available_from_required": True,
        "forward_return_columns_allowed": False,
        "research_only": True,
        "production_activation_allowed": False,
        "live_trading_allowed": False,
    }
    if missing_required:
        payload.update({"status": "blocked", "reason": "missing_required_columns"})
        return payload
    tickers = frame["ticker"].astype("string").fillna("").str.upper().str.strip()
    available_from = pd.to_datetime(frame["available_from"], errors="coerce").dt.normalize()
    invalid_available_from = int(available_from.isna().sum())
    empty_ticker_rows = int(tickers.eq("").sum())
    future_available_from = int((available_from > as_of).sum()) if as_of is not None else 0
    duplicate_key_count = 0
    if "estimate_date" in frame.columns:
        estimate_date = pd.to_datetime(frame["estimate_date"], errors="coerce").dt.normalize().astype("string")
    else:
        estimate_date = available_from.astype("string")
    key = pd.DataFrame(
        {
            "ticker": tickers,
            "available_from": available_from.astype("string"),
            "estimate_date": estimate_date,
            "fiscal_period": frame.get("fiscal_period", pd.Series([""] * len(frame))).astype("string").fillna(""),
        }
    )
    duplicate_key_count = int(key.duplicated().sum())
    guidance_values = []
    if "guidance_direction" in frame.columns:
        guidance_values = sorted(set(frame["guidance_direction"].astype("string").fillna("").str.lower().str.strip()) - {""})
    payload.update(
        {
            "ticker_count": int(tickers[tickers.ne("")].nunique()),
            "empty_ticker_rows": empty_ticker_rows,
            "invalid_available_from_rows": invalid_available_from,
            "future_available_from_rows": future_available_from,
            "duplicate_key_rows": duplicate_key_count,
            "min_available_from": available_from.min().date().isoformat() if available_from.notna().any() else None,
            "max_available_from": available_from.max().date().isoformat() if available_from.notna().any() else None,
            "guidance_values": guidance_values,
        }
    )
    blockers: list[str] = []
    warnings: list[str] = []
    if empty_ticker_rows:
        blockers.append("empty_ticker_rows")
    if invalid_available_from:
        blockers.append("invalid_available_from_rows")
    if not evidence_columns_present:
        blockers.append("no_nonempty_evidence_columns")
    if duplicate_key_count:
        warnings.append("duplicate_feed_keys")
    if future_available_from:
        warnings.append("future_available_from_rows_will_be_filtered_by_builder")
    if missing_recommended:
        warnings.append("missing_recommended_columns")
    if blockers:
        payload.update({"status": "blocked", "reason": ",".join(blockers)})
    elif warnings:
        payload.update({"status": "warning", "reason": ",".join(warnings)})
    else:
        payload.update({"status": "completed", "reason": ""})
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=DEFAULT_INPUT)
    parser.add_argument("--summary", default=DEFAULT_SUMMARY)
    parser.add_argument("--as-of", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = repo_path(args.input)
    summary_path = repo_path(args.summary)
    as_of = pd.Timestamp(args.as_of).normalize() if args.as_of else None
    if not input_path.exists():
        payload = {
            "schema_version": SCHEMA_VERSION,
            "generated_at_utc": utc_now(),
            "status": "blocked",
            "reason": "missing_input",
            "input": str(input_path),
            "required_columns": REQUIRED_COLUMNS,
            "recommended_columns": RECOMMENDED_COLUMNS,
            "available_from_required": True,
            "forward_return_columns_allowed": False,
            "research_only": True,
            "production_activation_allowed": False,
            "live_trading_allowed": False,
        }
        write_json(summary_path, payload)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 2
    try:
        frame = pd.read_csv(input_path, low_memory=False)
    except Exception as exc:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "generated_at_utc": utc_now(),
            "status": "blocked",
            "reason": "read_failed",
            "error": str(exc),
            "input": str(input_path),
            "research_only": True,
            "production_activation_allowed": False,
            "live_trading_allowed": False,
        }
        write_json(summary_path, payload)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 2
    payload = {
        "generated_at_utc": utc_now(),
        "input": str(input_path),
        **validate_feed(frame, as_of=as_of),
    }
    write_json(summary_path, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload.get("status") in {"completed", "warning"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
