#!/usr/bin/env python3
"""Materialize a PIT cash-rate series for broker cash-carry replay.

The broker replay intentionally reads local cached FRED-style files. Registering
`DGS3MO` in config is not enough; the cache file must exist before
`broker_ledger_next_close_cash_carry` can be measured.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import urlopen

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from r1000_config import MACRO_FRED_SERIES  # noqa: E402


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def read_rate_csv(path: Path, series_id: str) -> pd.DataFrame:
    raw = pd.read_csv(path)
    return normalize_rate_frame(raw, series_id)


def fetch_fred_graph_csv(series_id: str) -> pd.DataFrame:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    with urlopen(url, timeout=30) as response:  # nosec B310 - fixed FRED URL from series id
        raw = pd.read_csv(response)
    return normalize_rate_frame(raw, series_id)


def normalize_rate_frame(raw: pd.DataFrame, series_id: str) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame(columns=["date", "value"])
    cols = {str(c).strip().lower(): c for c in raw.columns}
    date_col = cols.get("date") or raw.columns[0]
    value_col = cols.get(series_id.lower()) or cols.get("value") or cols.get("rate_pct")
    if value_col is None and len(raw.columns) > 1:
        value_col = raw.columns[1]
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(raw[date_col], errors="coerce").dt.date.astype("string"),
            "value": pd.to_numeric(raw[value_col].replace(".", pd.NA), errors="coerce"),
        }
    ).dropna(subset=["date", "value"])
    frame = frame.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)
    return frame


def output_paths(output_cache: Path, rate_source: str, series_id: str) -> tuple[Path, Path]:
    key = str(rate_source).strip().lower()
    sid = str(series_id).strip().upper()
    return output_cache / f"fred_{key}_{sid}.parquet", output_cache / f"fred_{key}_{sid}.csv"


def run(args: argparse.Namespace) -> dict[str, Any]:
    rate_key = str(args.rate_source or "dgs3mo").strip()
    series_id = str(MACRO_FRED_SERIES.get(rate_key.lower()) or rate_key).upper()
    output_cache = repo_path(args.output_cache)
    output_cache.mkdir(parents=True, exist_ok=True)
    parquet_path, csv_path = output_paths(output_cache, rate_key, series_id)
    summary_path = repo_path(args.summary)
    if parquet_path.exists() and not args.force:
        frame = pd.read_parquet(parquet_path)
        source = "existing_parquet_cache"
        cache_written = False
    else:
        try:
            if args.fallback_csv:
                frame = read_rate_csv(repo_path(args.fallback_csv), series_id)
                source = "fallback_csv"
            else:
                frame = fetch_fred_graph_csv(series_id)
                source = "fred_graph_csv"
        except Exception as exc:
            payload = {
                "status": "blocked",
                "reason": "cash_rate_materialization_failed",
                "error": str(exc),
                "rate_source": rate_key,
                "series_id": series_id,
                "output_path": str(parquet_path),
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "cache_written": False,
                "next_action": "provide --fallback-csv or restore FRED/network access",
            }
            write_json(summary_path, payload)
            return payload
        if frame.empty:
            payload = {
                "status": "blocked",
                "reason": "cash_rate_series_empty",
                "rate_source": rate_key,
                "series_id": series_id,
                "output_path": str(parquet_path),
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "cache_written": False,
                "next_action": "check FRED source or fallback CSV",
            }
            write_json(summary_path, payload)
            return payload
        try:
            frame.to_parquet(parquet_path, index=False)
            cache_written = True
        except Exception:
            frame.to_csv(csv_path, index=False)
            cache_written = True
    dates = pd.to_datetime(frame["date"], errors="coerce")
    values = pd.to_numeric(frame["value"], errors="coerce")
    payload = {
        "status": "completed",
        "schema_version": "cash-rate-materialization-v1",
        "rate_source": rate_key,
        "series_id": series_id,
        "output_path": str(parquet_path if parquet_path.exists() else csv_path),
        "parquet_path": str(parquet_path),
        "csv_path": str(csv_path),
        "row_count": int(len(frame)),
        "min_date": dates.min().date().isoformat() if dates.notna().any() else None,
        "max_date": dates.max().date().isoformat() if dates.notna().any() else None,
        "latest_rate_pct": float(values.dropna().iloc[-1]) if values.notna().any() else None,
        "data_source": source,
        "cache_written": bool(cache_written),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "next_action": "run cash-carry broker replay measurement",
    }
    write_json(summary_path, payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rate-source", default="dgs3mo")
    parser.add_argument("--output-cache", default="cache_macro")
    parser.add_argument("--summary", default="outputs/cash_rate_materialization/summary.json")
    parser.add_argument("--fallback-csv", default="")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
