#!/usr/bin/env python3
"""Smoke checks for replay price-cache freshness detection."""
from __future__ import annotations

import sys
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.build_replay_price_cache import run  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def write_price(cache: Path, ticker: str, date: str) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    idx = pd.DatetimeIndex([pd.Timestamp(date)])
    pd.DataFrame(
        {
            "Open": [10.0],
            "Close": [10.0],
            "Adj Close": [10.0],
            "Volume": [1_000_000],
        },
        index=idx,
    ).to_parquet(cache / px_cache_name(ticker))


def test_replay_price_cache_marks_stale_existing_tickers() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        book = root / "book.csv"
        pd.DataFrame(
            [
                {"rebalance_date": "2026-01-31", "ticker": "AAA", "weight": 0.5},
                {"rebalance_date": "2026-01-31", "ticker": "BBB", "weight": 0.5},
                {"rebalance_date": "2026-01-31", "ticker": "CCC", "weight": 0.5},
            ]
        ).to_csv(book, index=False)
        cache = root / "cache_prices"
        write_price(cache, "AAA", "2000-01-03")
        write_price(cache, "BBB", pd.Timestamp.utcnow().date().isoformat())

        payload = run(
            Namespace(
                books=[str(book)],
                scored="",
                max_scored=0,
                output_dir=str(cache),
                start="",
                end="",
                batch_size=40,
                max_tickers=0,
                refresh_stale_days=2,
                dry_run=True,
            )
        )
        assert payload["status"] == "dry_run"
        assert payload["missing_before"] == 1
        assert payload["stale_before"] == 1
        assert payload["download_target_count"] == 2


if __name__ == "__main__":
    test_replay_price_cache_marks_stale_existing_tickers()
    print("replay_price_cache_smoke: PASS")
