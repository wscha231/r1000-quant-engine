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

from tools.build_replay_price_cache import collect_candidate_tickers, run  # noqa: E402
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
                candidate_books=[],
                candidate_max_per_date=0,
                candidate_max_total=0,
                extra_tickers=["SPY"],
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
        assert payload["extra_ticker_count"] == 1
        assert payload["extra_tickers"] == ["SPY"]
        assert payload["missing_before"] == 2
        assert payload["stale_before"] == 1
        assert payload["download_target_count"] == 3


def test_replay_price_cache_includes_bounded_historical_candidates() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        book = root / "book.csv"
        pd.DataFrame([{"rebalance_date": "2026-01-31", "ticker": "AAA", "weight": 1.0}]).to_csv(book, index=False)
        candidates = root / "candidate_replay_book.csv"
        pd.DataFrame(
            [
                {"rebalance_date": "2026-01-31", "ticker": "LOW1", "score": 0.1, "portfolio_monster_early_score": 0.1},
                {"rebalance_date": "2026-01-31", "ticker": "TOP1", "score": 0.9, "portfolio_monster_early_score": 0.9},
                {"rebalance_date": "2026-02-28", "ticker": "TOP2", "score": 0.8, "portfolio_monster_early_score": 0.8},
                {"rebalance_date": "2026-02-28", "ticker": "LOW2", "score": 0.2, "portfolio_monster_early_score": 0.2},
            ]
        ).to_csv(candidates, index=False)
        cache = root / "cache_prices"
        payload = run(
            Namespace(
                books=[str(book)],
                scored="",
                candidate_books=[str(candidates)],
                candidate_max_per_date=1,
                candidate_max_total=10,
                extra_tickers=[],
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
        assert payload["candidate_ticker_count"] == 2
        assert payload["ticker_count"] == 3
        assert payload["missing_before"] == 3


def test_candidate_cache_total_limit_balances_dates_with_recency_priority() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        candidates = root / "candidate_replay_book.csv"
        pd.DataFrame(
            [
                {"rebalance_date": "2020-01-31", "ticker": "OLD1", "score": 0.99},
                {"rebalance_date": "2020-01-31", "ticker": "OLD2", "score": 0.98},
                {"rebalance_date": "2026-05-14", "ticker": "NEW1", "score": 0.97},
                {"rebalance_date": "2026-05-14", "ticker": "NEW2", "score": 0.96},
            ]
        ).to_csv(candidates, index=False)

        tickers = collect_candidate_tickers([candidates], max_per_date=2, max_total=3)
        assert tickers == {"NEW1", "OLD1", "NEW2"}


if __name__ == "__main__":
    test_replay_price_cache_marks_stale_existing_tickers()
    test_replay_price_cache_includes_bounded_historical_candidates()
    test_candidate_cache_total_limit_balances_dates_with_recency_priority()
    print("replay_price_cache_smoke: PASS")
