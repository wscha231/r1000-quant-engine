#!/usr/bin/env python3
"""Build one combined ticker file from all forward-estimate shard CSVs.

This prepares a manual catch-up input for the forward-only earnings estimate
archive. It does not fetch vendor data and must not be treated as historical
backtest evidence.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

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

SCHEMA_VERSION = "forward-estimate-catchup-universe-v1"


def read_tickers(path: Path, excludes: set[str]) -> list[str]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        field = "ticker" if "ticker" in (reader.fieldnames or []) else (reader.fieldnames or [""])[0]
        out = []
        for row in reader:
            ticker = normalize_ticker(row.get(field))
            if is_valid_equity_ticker(ticker, excludes):
                out.append(ticker)
        return out


def parse_inline_tickers(value: str, excludes: set[str]) -> list[str]:
    out = []
    for raw in (value or "").split(","):
        ticker = normalize_ticker(raw)
        if is_valid_equity_ticker(ticker, excludes):
            out.append(ticker)
    return out


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_catchup_universe(
    *,
    shard_dir: str,
    output: str,
    summary: str,
    include_tickers: str = "",
    max_tickers: int = 0,
) -> dict[str, Any]:
    excludes = set(DEFAULT_EXCLUDE_TICKERS)
    shard_dir_path = repo_path(shard_dir)
    output_path = repo_path(output)
    summary_path = repo_path(summary)
    shard_paths = sorted(shard_dir_path.glob("shard_*.csv")) if shard_dir_path.exists() else []

    ordered: list[str] = []
    ordered.extend(parse_inline_tickers(include_tickers, excludes))
    shard_rows: list[dict[str, Any]] = []
    for path in shard_paths:
        tickers = read_tickers(path, excludes)
        ordered.extend(tickers)
        shard_rows.append(
            {
                "shard_id": path.stem,
                "path": display_path(path),
                "ticker_count": len(tickers),
            }
        )

    tickers = list(dict.fromkeys(ordered))
    if max_tickers > 0:
        tickers = tickers[:max_tickers]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["ticker"])
        writer.writeheader()
        for ticker in tickers:
            writer.writerow({"ticker": ticker})

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "status": "ready_for_forward_archive_catchup" if tickers else "blocked_no_tickers",
        "research_only": True,
        "forward_only": True,
        "backtest_acceptance_allowed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "fullrun_dispatched": False,
        "coverage_scope": "all_checked_in_forward_estimate_shards",
        "collection_mode": "manual_all_shards_catchup",
        "missing_vendor_coverage_policy": "neutral",
        "shard_dir": display_path(shard_dir_path),
        "source_shard_count": len(shard_paths),
        "source_shards": shard_rows,
        "include_ticker_count": len(parse_inline_tickers(include_tickers, excludes)),
        "ticker_count": len(tickers),
        "max_tickers": max_tickers,
        "output_csv": display_path(output_path),
        "acceptance_label": "forward_archive_catchup_only",
    }
    write_json(summary_path, payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shard-dir", default="outputs/forward_estimate_universe_plan_20260709/shards")
    parser.add_argument("--output", default="outputs/earnings_estimates_daily/catchup_all_shards_universe.csv")
    parser.add_argument("--summary", default="outputs/earnings_estimates_daily/catchup_universe_summary.json")
    parser.add_argument("--include-tickers", default="")
    parser.add_argument("--max-tickers", type=int, default=0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_catchup_universe(
        shard_dir=args.shard_dir,
        output=args.output,
        summary=args.summary,
        include_tickers=args.include_tickers,
        max_tickers=args.max_tickers,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["status"] == "ready_for_forward_archive_catchup" else 2


if __name__ == "__main__":
    raise SystemExit(main())
