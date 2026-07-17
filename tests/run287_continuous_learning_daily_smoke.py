#!/usr/bin/env python3
"""Smoke checks for daily causal-ledger orchestration and bounded queueing."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import run_run287_continuous_learning_daily as daily  # noqa: E402


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="run287-continuous-daily-") as tmp_raw:
        tmp = Path(tmp_raw)
        output = tmp / "ledger"
        output.mkdir()
        pd.DataFrame(
            {
                "decision_date": ["2026-07-13"] * 4,
                "ticker": ["AAA", "BBB", "CCC", "DDD"],
                "selector_selected": [True, False, False, False],
                "operating_target_weight": [0.0, 0.5, 0.0, 0.0],
                "simulated_fill_weight": [0.0, 0.49, 0.0, 0.0],
                "published_ranking_eligible": [True, True, True, False],
                "published_rank": [1, 2, 3, 4],
            }
        ).to_parquet(output / "current_status.parquet", index=False)
        contract = tmp / "contract.json"
        contract.write_text(
            json.dumps(
                {
                    "benchmark_tickers": ["SPY", "QQQ"],
                    "sector_etf_map": {"Technology": "XLK"},
                }
            ),
            encoding="utf-8",
        )
        universe_count, queue_count, start = daily.write_price_collection_queue(
            output, tmp / "empty_cache", "2026-07-15", contract, 2
        )
        assert universe_count == 7
        assert queue_count == 2
        assert start == "2026-07-13"
        queue = pd.read_csv(output / "price_collection_queue.csv")
        assert queue["ticker"].tolist() == ["AAA", "BBB"], queue

        args = argparse.Namespace(
            producer_status=str(tmp / "missing_status.json"),
            output_dir=str(tmp / "skipped"),
            recorded_at_utc="2026-07-16T04:15:00Z",
            as_of_date="2026-07-15",
        )
        skipped = daily.run(args)
        assert skipped["status"].startswith("SKIPPED")
        assert not skipped["orders_generated"]
        assert not skipped["target_books_mutated"]
        assert not skipped["live_trading_enabled"]
    print("run287_continuous_learning_daily_smoke: PASS")


if __name__ == "__main__":
    main()
