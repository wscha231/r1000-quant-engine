#!/usr/bin/env python3
"""Materialize SEC actuals snapshots as a separate PIT event layer.

This tool intentionally does not parse analyst revisions or company guidance.
Rows produced here are backward-looking actuals and are never eligible for R1
earnings/guidance coverage.
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

SCHEMA_VERSION = "sec-actuals-snapshot-v1"
DEFAULT_INPUT = "data_raw/events/sec_actuals_snapshot.csv"
DEFAULT_OUTPUT = "data_pit/events/sec_actuals_snapshot.parquet"
REQUIRED_COLUMNS = ["ticker", "metric", "reported_value", "available_from"]
OPTIONAL_COLUMNS = ["cik", "form_type", "filing_date", "accepted_ts", "period_end", "fact_name", "unit", "fiscal_period", "source_file", "source_hash"]


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def read_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if path.suffix.lower() in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def materialize(raw: pd.DataFrame, *, as_of: pd.Timestamp | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
    missing = sorted(set(REQUIRED_COLUMNS) - set(raw.columns))
    if missing:
        return pd.DataFrame(), {"status": "blocked", "reason": "missing_required_columns", "missing_required_columns": missing}
    d = raw.copy()
    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    d["metric"] = d["metric"].astype(str).str.strip()
    d["reported_value"] = pd.to_numeric(d["reported_value"], errors="coerce")
    d["available_from"] = pd.to_datetime(d["available_from"], errors="coerce").dt.normalize()
    for col in ["filing_date", "accepted_ts", "period_end"]:
        if col in d.columns:
            d[col] = pd.to_datetime(d[col], errors="coerce")
    invalid_available_from = int(d["available_from"].isna().sum())
    invalid_value_rows = int(d["reported_value"].isna().sum())
    future_available_from = int((d["available_from"] > as_of).sum()) if as_of is not None else 0
    d = d[d["ticker"].ne("") & d["metric"].ne("") & d["reported_value"].notna() & d["available_from"].notna()].copy()
    if as_of is not None:
        d = d[d["available_from"] <= as_of].copy()
    for col in OPTIONAL_COLUMNS:
        if col not in d.columns:
            d[col] = ""
    d["source_type"] = "sec_actual_snapshot"
    d["source_name"] = d.get("source_name", pd.Series(["sec_companyfacts_or_filing_snapshot"] * len(d), index=d.index)).astype(str)
    d["is_actual"] = True
    d["is_proxy"] = False
    d["is_coverage_eligible"] = False
    d["pit_validated"] = True
    d["schema_version"] = SCHEMA_VERSION
    d["event_id"] = (
        d["ticker"].astype(str)
        + "|"
        + d["metric"].astype(str)
        + "|"
        + d["fiscal_period"].astype(str)
        + "|"
        + d["available_from"].dt.strftime("%Y-%m-%d")
    )
    duplicate_event_rows = int(d["event_id"].duplicated().sum())
    if duplicate_event_rows:
        return pd.DataFrame(), {
            "status": "blocked",
            "reason": "duplicate_event_id",
            "duplicate_event_rows": duplicate_event_rows,
            "invalid_available_from_rows": invalid_available_from,
            "invalid_reported_value_rows": invalid_value_rows,
            "future_available_from_rows_filtered": future_available_from,
        }
    cols = [
        "event_id",
        "ticker",
        "cik",
        "form_type",
        "filing_date",
        "accepted_ts",
        "period_end",
        "fact_name",
        "metric",
        "reported_value",
        "unit",
        "fiscal_period",
        "available_from",
        "source_type",
        "source_name",
        "source_file",
        "source_hash",
        "is_actual",
        "is_proxy",
        "is_coverage_eligible",
        "pit_validated",
        "schema_version",
    ]
    out = d[cols].sort_values(["available_from", "ticker", "metric"]).reset_index(drop=True)
    summary = {
        "status": "completed" if not out.empty else "blocked",
        "reason": "" if not out.empty else "no_output_rows",
        "input_rows": int(len(raw)),
        "output_rows": int(len(out)),
        "ticker_count": int(out["ticker"].nunique()) if not out.empty else 0,
        "invalid_available_from_rows": invalid_available_from,
        "invalid_reported_value_rows": invalid_value_rows,
        "future_available_from_rows_filtered": future_available_from,
        "duplicate_event_rows": 0,
        "source_type": "sec_actual_snapshot",
        "is_coverage_eligible": False,
        "regime_nowcast_coverage_ready": False,
    }
    return out, summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=DEFAULT_INPUT)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", default="outputs/sec_actuals_snapshot/summary.json")
    parser.add_argument("--as-of", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = repo_path(args.input)
    output_path = repo_path(args.output)
    summary_path = repo_path(args.summary)
    if not input_path.exists():
        payload = {
            "schema_version": SCHEMA_VERSION,
            "generated_at_utc": utc_now(),
            "status": "blocked",
            "reason": "missing_input",
            "input": str(input_path),
            "required_columns": REQUIRED_COLUMNS,
            "research_only": True,
            "production_activation_allowed": False,
        }
        write_json(summary_path, payload)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 2
    raw = read_table(input_path)
    as_of = pd.Timestamp(args.as_of).normalize() if args.as_of else None
    out, summary = materialize(raw, as_of=as_of)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "input": str(input_path),
        "output": str(output_path),
        "research_only": True,
        "production_activation_allowed": False,
        "live_trading_allowed": False,
        **summary,
    }
    if out.empty:
        write_json(summary_path, payload)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 2
    output_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(output_path, index=False)
    write_json(summary_path, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
