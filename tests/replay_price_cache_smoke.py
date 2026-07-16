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

from tools.build_replay_price_cache import run, tickers_missing_session_date, yfinance_symbol  # noqa: E402
import tools.build_replay_price_cache as cache_builder  # noqa: E402
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
                required_tickers=[],
                refresh_stale_days=2,
                required_session_date="",
                dry_run=True,
            )
        )
        assert payload["status"] == "dry_run"
        assert payload["missing_before"] == 1
        assert payload["stale_before"] == 1
        assert payload["download_target_count"] == 2
        assert payload["requested_end"] > payload["end"]
        assert payload["end"] == pd.Timestamp.utcnow().date().isoformat()
        assert payload["actual_cached_ticker_count"] == 2
        assert payload["manifest_end_source"] == "actual_cached_bars"


def test_replay_price_cache_always_includes_required_tickers() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        book = root / "book.csv"
        pd.DataFrame([{"rebalance_date": "2026-01-31", "ticker": "AAA", "weight": 1.0}]).to_csv(book, index=False)
        cache = root / "cache_prices"
        payload = run(
            Namespace(
                books=[str(book)],
                scored="",
                max_scored=0,
                output_dir=str(cache),
                start="",
                end="",
                batch_size=40,
                max_tickers=1,
                required_tickers=["SPY", "QQQ"],
                refresh_stale_days=-1,
                required_session_date="",
                dry_run=True,
            )
        )
        assert payload["required_tickers"] == ["QQQ", "SPY"]
        assert payload["ticker_count"] == 3
        assert payload["download_target_count"] == 3


def test_replay_price_cache_requires_exact_session_bar() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        book = root / "book.csv"
        pd.DataFrame([{"rebalance_date": "2026-07-14", "ticker": "AAA", "weight": 1.0}]).to_csv(
            book, index=False
        )
        cache = root / "cache_prices"
        write_price(cache, "AAA", "2026-07-13")
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
                required_tickers=[],
                refresh_stale_days=2,
                required_session_date="2026-07-14",
                dry_run=True,
            )
        )
        assert payload["required_session_missing_before"] == ["AAA"]
        assert payload["download_target_count"] == 1
        assert tickers_missing_session_date(cache, {"AAA"}, pd.Timestamp("2026-07-14")) == ["AAA"]
        write_price(cache, "AAA", "2026-07-14")
        assert tickers_missing_session_date(cache, {"AAA"}, pd.Timestamp("2026-07-14")) == []


def test_replay_price_cache_retries_missing_exact_bar_individually() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        book = root / "book.csv"
        pd.DataFrame([{"rebalance_date": "2026-07-14", "ticker": "AAA", "weight": 1.0}]).to_csv(
            book, index=False
        )
        cache = root / "cache_prices"
        write_price(cache, "AAA", "2026-07-13")
        calls: list[tuple[list[str], int]] = []

        def fake_download(tickers: list[str], start: str, end: str, output_dir: Path, batch_size: int) -> dict:
            calls.append((list(tickers), batch_size))
            if batch_size == 1:
                write_price(output_dir, "AAA", "2026-07-14")
            return {"written": len(tickers), "failed": [], "failed_count": 0}

        original = cache_builder.download_prices
        cache_builder.download_prices = fake_download
        try:
            payload = run(
                Namespace(
                    books=[str(book)],
                    scored="",
                    max_scored=0,
                    output_dir=str(cache),
                    start="2026-07-01",
                    end="2026-07-17",
                    batch_size=40,
                    max_tickers=0,
                    required_tickers=[],
                    refresh_stale_days=-1,
                    required_session_date="2026-07-14",
                    dry_run=False,
                )
            )
        finally:
            cache_builder.download_prices = original
        assert calls == [(["AAA"], 40), (["AAA"], 1)]
        assert payload["required_session_retry_count"] == 1
        assert payload["required_session_missing_after_count"] == 0
        assert payload["status"] == "completed"


def test_yfinance_symbol_preserves_foreign_exchange_suffixes() -> None:
    assert yfinance_symbol("BRK.B") == "BRK-B"
    assert yfinance_symbol("000660.KS") == "000660.KS"
    assert yfinance_symbol("7203.T") == "7203.T"


if __name__ == "__main__":
    test_replay_price_cache_marks_stale_existing_tickers()
    test_replay_price_cache_always_includes_required_tickers()
    test_replay_price_cache_requires_exact_session_bar()
    test_replay_price_cache_retries_missing_exact_bar_individually()
    test_yfinance_symbol_preserves_foreign_exchange_suffixes()
    print("replay_price_cache_smoke: PASS")
