#!/usr/bin/env python3
"""Single data catalog — one source of truth for every data store.

Walks the engine's scattered data lakes (data_pit/, data_raw/, cache_prices/,
key outputs/) against a registry and emits ``data/catalog.json``: for each
dataset, its path, existence, size, last-modified, row/ticker counts,
available_from date range, column list, the workflow that OWNS it, and a
freshness verdict against an expected cadence. Missing or stale feeds are
visible at a glance instead of silently producing zero alpha.

The registry below is the authoritative inventory. Adding a new feed = one
DATASETS entry, so the catalog stays the single place that knows where data
lives, who refreshes it, and whether it's current.

Read-only. Loads parquet/csv metadata (and a small sample for date ranges); it
never mutates data, never hits the network.
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent


# layer: logical evidence group. cadence_days: expected max age before STALE.
DATASETS: list[dict[str, Any]] = [
    # --- SEC / smart money ---
    {"name": "sec_13f_holdings", "path": "data_pit/sec/institutional_13f_holdings.parquet",
     "kind": "parquet", "ticker_col": "ticker_mapped", "date_col": "available_from",
     "layer": "13f", "owner_workflow": "sec_13f_quarterly_refresh.yml", "cadence_days": 100},
    {"name": "form4_ownership_signals", "path": "data_pit/sec/sec_ownership_signals.parquet",
     "kind": "parquet", "ticker_col": "issuer_ticker", "date_col": "available_from",
     "layer": "form4", "owner_workflow": "sec_form4_daily_refresh.yml", "cadence_days": 5},
    {"name": "form4_transactions", "path": "data_pit/sec/form4_transactions.parquet",
     "kind": "parquet", "ticker_col": "issuer_ticker", "date_col": "available_from",
     "layer": "form4", "owner_workflow": "sec_form4_daily_refresh.yml", "cadence_days": 5},
    {"name": "top_manager_cohorts", "path": "data_pit/sec/pit_top_manager_cohorts.parquet",
     "kind": "parquet", "ticker_col": "manager_cik", "date_col": "cohort_date",
     "layer": "top7", "owner_workflow": "post_disclosure_alpha_pipeline.yml", "cadence_days": 100},
    {"name": "top_manager_follow_events", "path": "data_pit/sec/top_manager_13f_follow_events.parquet",
     "kind": "parquet", "ticker_col": "ticker", "date_col": "available_from",
     "layer": "top7", "owner_workflow": "post_disclosure_alpha_pipeline.yml", "cadence_days": 100},
    {"name": "post_disclosure_labels", "path": "data_pit/sec/post_disclosure_alpha_labels.parquet",
     "kind": "parquet", "ticker_col": "ticker", "date_col": "available_from",
     "layer": "post_disclosure", "owner_workflow": "post_disclosure_alpha_pipeline.yml", "cadence_days": 100},
    {"name": "companyfacts_zip", "path": "data_raw/free/sec/companyfacts.zip",
     "kind": "zip", "layer": "fundamentals", "owner_workflow": "free_data_daily_update.yml", "cadence_days": 7},
    # --- ETF ---
    {"name": "etf_holdings", "path": "data_pit/etf_holdings/etf_holdings.parquet",
     "kind": "parquet", "ticker_col": "holding_ticker", "date_col": "available_from",
     "layer": "etf", "owner_workflow": "etf_holdings_monthly_refresh.yml", "cadence_days": 40},
    # --- prices ---
    {"name": "price_cache_manifest", "path": "data_raw/free/prices/replay_price_cache_manifest.json",
     "kind": "json", "layer": "prices", "owner_workflow": "after_close_daily.yml", "cadence_days": 4},
    {"name": "price_cache_dir", "path": "cache_prices",
     "kind": "dir", "layer": "prices", "owner_workflow": "after_close_daily.yml", "cadence_days": 4},
    # --- materialised candidate / scored books ---
    {"name": "scored_latest", "path": "outputs/scored_latest.csv",
     "kind": "csv", "ticker_col": "ticker", "date_col": "", "layer": "scored",
     "owner_workflow": "full_rebuild_manual.yml", "cadence_days": 14},
    {"name": "candidate_replay_book", "path": "outputs/reports/candidate_replay_book.csv",
     "kind": "csv", "ticker_col": "ticker", "date_col": "rebalance_date", "layer": "candidate",
     "owner_workflow": "full_rebuild_manual.yml", "cadence_days": 14},
    {"name": "sec_enriched_candidate_book", "path": "outputs/sec_enriched_candidate_replay/candidate_replay_book_sec_enriched.csv",
     "kind": "csv", "ticker_col": "ticker", "date_col": "rebalance_date", "layer": "enriched_candidate",
     "owner_workflow": "full_rebuild_manual.yml", "cadence_days": 14},
]


def repo_path(value: str | Path) -> Path:
    p = Path(value)
    return p if p.is_absolute() else REPO_ROOT / p


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _age_days(modified_utc: Optional[datetime]) -> Optional[float]:
    if modified_utc is None:
        return None
    return round((now_utc() - modified_utc).total_seconds() / 86400.0, 3)


def _load_frame(path: Path, kind: str, max_rows: int = 0) -> Optional[pd.DataFrame]:
    try:
        if kind == "parquet":
            return pd.read_parquet(path)
        if kind == "csv":
            return pd.read_csv(path, low_memory=False, nrows=(max_rows or None))
    except Exception:
        return None
    return None


def inspect_dataset(spec: dict[str, Any]) -> dict[str, Any]:
    path = repo_path(spec["path"])
    entry: dict[str, Any] = {
        "name": spec["name"],
        "layer": spec["layer"],
        "path": spec["path"],
        "kind": spec["kind"],
        "owner_workflow": spec["owner_workflow"],
        "cadence_days": spec["cadence_days"],
        "exists": path.exists(),
        "status": "missing",
    }
    if not path.exists():
        entry["action"] = f"MISSING — expected to be written by {spec['owner_workflow']}"
        return entry

    stat = path.stat() if not path.is_dir() else None
    if path.is_dir():
        files = [p for p in path.rglob("*") if p.is_file()]
        entry["bytes"] = sum(p.stat().st_size for p in files)
        entry["file_count"] = len(files)
        mtime = max((p.stat().st_mtime for p in files), default=None)
    else:
        entry["bytes"] = stat.st_size
        mtime = stat.st_mtime
    modified = datetime.fromtimestamp(mtime, tz=timezone.utc) if mtime else None
    entry["modified_utc"] = modified.isoformat() if modified else None
    entry["age_days"] = _age_days(modified)

    # Freshness verdict
    age = entry.get("age_days")
    if age is None:
        entry["freshness"] = "unknown"
    elif age > float(spec["cadence_days"]):
        entry["freshness"] = "STALE"
    else:
        entry["freshness"] = "fresh"

    if spec["kind"] == "zip":
        try:
            with zipfile.ZipFile(path) as z:
                entry["zip_member_count"] = len(z.namelist())
        except Exception:
            entry["zip_member_count"] = None
    elif spec["kind"] == "json":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            entry["json_keys"] = sorted(payload)[:20] if isinstance(payload, dict) else None
            if isinstance(payload, dict) and "end" in payload:
                entry["manifest_end"] = payload.get("end")
        except Exception:
            entry["json_keys"] = None
    elif spec["kind"] in ("parquet", "csv"):
        frame = _load_frame(path, spec["kind"])
        if frame is None:
            entry["status"] = "unreadable"
            entry["action"] = "file present but could not be parsed"
            return entry
        entry["row_count"] = int(len(frame))
        entry["columns"] = list(map(str, frame.columns))[:60]
        entry["n_columns"] = int(frame.shape[1])
        tcol = spec.get("ticker_col")
        if tcol and tcol in frame.columns:
            entry["ticker_count"] = int(frame[tcol].astype(str).nunique())
        dcol = spec.get("date_col")
        if dcol and dcol in frame.columns:
            dts = pd.to_datetime(frame[dcol], errors="coerce")
            valid = dts.dropna()
            if not valid.empty:
                entry["available_from_min"] = str(valid.min())
                entry["available_from_max"] = str(valid.max())
                entry["available_from_nonnull_ratio"] = round(float(valid.shape[0]) / max(len(frame), 1), 4)
            else:
                entry["available_from_nonnull_ratio"] = 0.0
        if entry.get("row_count", 0) == 0:
            entry["status"] = "empty"
            entry["action"] = f"EMPTY — {spec['owner_workflow']} ran but produced no rows"
            return entry

    entry["status"] = "ok"
    return entry


def build_catalog() -> dict[str, Any]:
    datasets = [inspect_dataset(s) for s in DATASETS]
    missing = [d["name"] for d in datasets if d["status"] == "missing"]
    empty = [d["name"] for d in datasets if d["status"] == "empty"]
    unreadable = [d["name"] for d in datasets if d["status"] == "unreadable"]
    stale = [d["name"] for d in datasets if d.get("freshness") == "STALE"]
    by_layer: dict[str, list[str]] = {}
    for d in datasets:
        by_layer.setdefault(d["layer"], []).append(d["name"])
    health = "ok"
    if missing or empty or unreadable:
        health = "DEGRADED"
    return {
        "generated_utc": now_utc().isoformat(),
        "health": health,
        "n_datasets": len(datasets),
        "missing": missing,
        "empty": empty,
        "unreadable": unreadable,
        "stale": stale,
        "layers": by_layer,
        "datasets": datasets,
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", default="data/catalog.json")
    p.add_argument("--print-summary", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    catalog = build_catalog()
    out = repo_path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(catalog, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"[data-catalog] health={catalog['health']}  datasets={catalog['n_datasets']}  "
          f"missing={len(catalog['missing'])}  empty={len(catalog['empty'])}  stale={len(catalog['stale'])}")
    for d in catalog["datasets"]:
        flag = d["status"] if d["status"] != "ok" else d.get("freshness", "")
        if flag and flag not in ("ok", "fresh"):
            print(f"  {flag:10s} {d['layer']:18s} {d['name']:28s} <- {d['owner_workflow']}")
    print(f"[data-catalog] wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
