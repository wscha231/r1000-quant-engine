#!/usr/bin/env python3
"""Build incremental ticker add-ons for the forward estimate archive.

The archive should not re-create historical estimate data. It should keep
collecting new snapshots for names that have usable coverage, immediately test
new universe entrants, and let the rotating shard continue slow retries for
currently uncovered names.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
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

SCHEMA_VERSION = "forward-estimate-incremental-universe-v1"


def parse_inline_tickers(value: str, excludes: set[str]) -> list[str]:
    out = []
    for raw in (value or "").split(","):
        ticker = normalize_ticker(raw)
        if is_valid_equity_ticker(ticker, excludes):
            out.append(ticker)
    return out


def read_ticker_file(path: Path, excludes: set[str]) -> list[str]:
    if not path.exists() or not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        field = "ticker" if "ticker" in (reader.fieldnames or []) else (reader.fieldnames or [""])[0]
        return [
            ticker
            for ticker in (normalize_ticker(row.get(field)) for row in reader)
            if is_valid_equity_ticker(ticker, excludes)
        ]


def read_all_shard_tickers(shard_dir: Path, excludes: set[str]) -> tuple[list[str], list[dict[str, Any]]]:
    ordered: list[str] = []
    rows: list[dict[str, Any]] = []
    for path in sorted(shard_dir.glob("shard_*.csv")) if shard_dir.exists() else []:
        tickers = read_ticker_file(path, excludes)
        ordered.extend(tickers)
        rows.append({"shard_id": path.stem, "path": display_path(path), "ticker_count": len(tickers)})
    return list(dict.fromkeys(ordered)), rows


def load_snapshot_history(snapshot_dir: Path) -> pd.DataFrame:
    frames = []
    for path in sorted(snapshot_dir.glob("estimates_*.parquet")) if snapshot_dir.exists() else []:
        try:
            frame = pd.read_parquet(path)
        except Exception:
            continue
        if not frame.empty:
            frame["_snapshot_path"] = display_path(path)
            frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def latest_by_ticker(history: pd.DataFrame) -> pd.DataFrame:
    if history.empty or "ticker" not in history.columns:
        return pd.DataFrame()
    d = history.copy()
    d["ticker"] = d["ticker"].astype(str).map(normalize_ticker)
    if "available_from" in d.columns:
        d["_available_from_ts"] = pd.to_datetime(d["available_from"], errors="coerce")
    elif "as_of_date" in d.columns:
        d["_available_from_ts"] = pd.to_datetime(d["as_of_date"], errors="coerce")
    else:
        d["_available_from_ts"] = pd.NaT
    d = d[d["ticker"].ne("")].sort_values(["ticker", "_available_from_ts"], kind="stable")
    return d.groupby("ticker", as_index=False).tail(1)


def write_csv(path: Path, tickers: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["ticker"])
        writer.writeheader()
        for ticker in tickers:
            writer.writerow({"ticker": ticker})


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def build_incremental_universe(
    *,
    shard_dir: str,
    snapshot_dir: str,
    output: str,
    summary: str,
    include_tickers: str = "",
    include_file: str = "",
    max_new_tickers: int = 100,
    max_covered_tickers: int = 300,
) -> dict[str, Any]:
    excludes = set(DEFAULT_EXCLUDE_TICKERS)
    shard_dir_path = repo_path(shard_dir)
    snapshot_dir_path = repo_path(snapshot_dir)
    output_path = repo_path(output)
    summary_path = repo_path(summary)
    include_file_path = repo_path(include_file) if include_file else Path("")

    current_universe, shard_rows = read_all_shard_tickers(shard_dir_path, excludes)
    history = load_snapshot_history(snapshot_dir_path)
    latest = latest_by_ticker(history)
    history_tickers = set(latest["ticker"].astype(str)) if not latest.empty else set()

    covered: list[str] = []
    if not latest.empty and "has_forward_estimate" in latest.columns:
        latest = latest.copy()
        latest["_has_forward_estimate_num"] = pd.to_numeric(latest["has_forward_estimate"], errors="coerce").fillna(0)
        covered = latest.loc[latest["_has_forward_estimate_num"].gt(0), "ticker"].astype(str).tolist()
    covered = covered[: max_covered_tickers if max_covered_tickers > 0 else None]

    new_universe: list[str] = []
    if history_tickers:
        new_universe = [ticker for ticker in current_universe if ticker not in history_tickers]
    new_universe = new_universe[: max_new_tickers if max_new_tickers > 0 else None]

    include_inline = parse_inline_tickers(include_tickers, excludes)
    include_file_tickers = read_ticker_file(include_file_path, excludes) if include_file else []

    combined = list(dict.fromkeys([*include_inline, *include_file_tickers, *covered, *new_universe]))
    write_csv(output_path, combined)

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "status": "ready_for_forward_archive_incremental" if combined else "blocked_no_tickers",
        "research_only": True,
        "forward_only": True,
        "backtest_acceptance_allowed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "fullrun_dispatched": False,
        "collection_mode": "incremental_covered_new_plus_retry",
        "missing_vendor_coverage_policy": "neutral",
        "historical_backfill_allowed": False,
        "current_universe_ticker_count": len(current_universe),
        "history_snapshot_file_count": int(len(list(snapshot_dir_path.glob("estimates_*.parquet"))) if snapshot_dir_path.exists() else 0),
        "history_ticker_count": len(history_tickers),
        "include_inline_ticker_count": len(include_inline),
        "include_file": display_path(include_file_path) if include_file else "",
        "include_file_ticker_count": len(include_file_tickers),
        "known_covered_ticker_count": len(covered),
        "new_universe_ticker_count": len(new_universe),
        "max_new_tickers": max_new_tickers,
        "max_covered_tickers": max_covered_tickers,
        "output_ticker_count": len(combined),
        "output_csv": display_path(output_path),
        "shard_dir": display_path(shard_dir_path),
        "source_shard_count": len(shard_rows),
        "source_shards": shard_rows,
        "known_covered_tickers": covered,
        "new_universe_tickers": new_universe,
        "acceptance_label": "forward_archive_incremental_only",
    }
    write_json(summary_path, payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shard-dir", default="outputs/forward_estimate_universe_plan_20260709/shards")
    parser.add_argument("--snapshot-dir", default="data_pit/events/earnings_estimates")
    parser.add_argument("--output", default="outputs/earnings_estimates_daily/incremental_universe.csv")
    parser.add_argument("--summary", default="outputs/earnings_estimates_daily/incremental_universe_summary.json")
    parser.add_argument("--include-tickers", default="")
    parser.add_argument("--include-file", default="")
    parser.add_argument("--max-new-tickers", type=int, default=100)
    parser.add_argument("--max-covered-tickers", type=int, default=300)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_incremental_universe(
        shard_dir=args.shard_dir,
        snapshot_dir=args.snapshot_dir,
        output=args.output,
        summary=args.summary,
        include_tickers=args.include_tickers,
        include_file=args.include_file,
        max_new_tickers=args.max_new_tickers,
        max_covered_tickers=args.max_covered_tickers,
    )
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if payload["status"] == "ready_for_forward_archive_incremental" else 2


if __name__ == "__main__":
    raise SystemExit(main())
