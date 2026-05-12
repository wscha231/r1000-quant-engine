#!/usr/bin/env python3
"""Smoke tests for operating target book generation."""
from __future__ import annotations

import csv
import sys
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.build_operating_target_books import build  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_price_cache(cache: Path, ticker: str, end_date: str) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    dates = pd.bdate_range("2026-05-01", end_date)
    frame = pd.DataFrame(
        {
            "Open": [100.0 + i for i in range(len(dates))],
            "Close": [101.0 + i for i in range(len(dates))],
            "Adj Close": [101.0 + i for i in range(len(dates))],
            "Volume": [1_000_000] * len(dates),
        },
        index=dates,
    )
    frame.to_parquet(cache / px_cache_name(ticker))


def test_operating_books_append_latest_close_targets() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "latest"
        price_cache = root / "cache_prices"
        out_dir = latest / "reports"

        write_csv(
            latest / "reports" / "main_monthly_weights.csv",
            [{"rebalance_date": "2026-02-27", "ticker": "AAA", "weight": 1.0}],
        )
        write_csv(
            latest / "portfolio_latest.csv",
            [
                {"rebalance_date": "2026-05-11", "ticker": "ON", "weight": 0.5},
                {"rebalance_date": "2026-05-11", "ticker": "MU", "weight": 0.5},
            ],
        )
        write_csv(
            latest / "reports" / "concentrated_strategy_holdings.csv",
            [
                {
                    "rebalance_date": "2026-02-27",
                    "ticker": "AAA",
                    "weight": 1.0,
                    "target_stock_names": 4,
                    "weighting_mode": "score_power",
                }
            ],
        )
        write_csv(
            latest / "concentrated_portfolio_latest.csv",
            [
                {
                    "rebalance_date": "2026-05-11",
                    "ticker": "WDC",
                    "weight": 0.5,
                    "target_stock_names": 4,
                    "weighting_mode": "score_power",
                },
                {
                    "rebalance_date": "2026-05-11",
                    "ticker": "SNDK",
                    "weight": 0.5,
                    "target_stock_names": 4,
                    "weighting_mode": "score_power",
                },
            ],
        )
        for ticker in ["ON", "MU", "WDC", "SNDK"]:
            write_price_cache(price_cache, ticker, "2026-05-08")

        payload = build(Namespace(latest_run=str(latest), price_cache=str(price_cache), output_dir=str(out_dir)))
        assert payload["status"] == "completed"

        main = pd.read_csv(out_dir / "operating_main_target_book.csv")
        concentrated = pd.read_csv(out_dir / "operating_concentrated_target_book.csv")
        assert set(main.loc[main["rebalance_date"].eq("2026-05-08"), "ticker"]) == {"ON", "MU"}
        assert set(concentrated.loc[concentrated["rebalance_date"].eq("2026-05-08"), "ticker"]) == {"WDC", "SNDK"}
        assert main["decision_frequency"].iloc[-1] == "event_driven_latest_close"
        assert concentrated["decision_frequency"].iloc[-1] == "event_driven_latest_close"

        books = {row["portfolio"]: row for row in payload["books"]}
        assert books["main"]["history_max_rebalance_date"] == "2026-02-27"
        assert books["main"]["operating_signal_date"] == "2026-05-08"
        assert books["main"]["latest_target_appended"] is True
        assert books["concentrated"]["operating_signal_date"] == "2026-05-08"
        assert (out_dir / "operating_target_books_summary.json").exists()
        assert (out_dir / "operating_target_books_report.md").exists()


def test_operating_books_do_not_use_future_recommended_next_run_date() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "latest"
        out_dir = latest / "reports"
        price_cache = root / "empty_cache"

        write_csv(
            latest / "reports" / "main_monthly_weights.csv",
            [{"rebalance_date": "2026-02-27", "ticker": "AAA", "weight": 1.0}],
        )
        write_csv(
            latest / "portfolio_latest.csv",
            [{"recommended_next_run_date": "2026-06-30", "ticker": "ON", "weight": 1.0}],
        )
        write_csv(
            latest / "reports" / "concentrated_strategy_holdings.csv",
            [{"rebalance_date": "2026-02-27", "ticker": "AAA", "weight": 1.0}],
        )
        write_csv(
            latest / "concentrated_portfolio_latest.csv",
            [{"recommended_next_run_date": "2026-06-30", "ticker": "MU", "weight": 1.0}],
        )

        payload = build(Namespace(latest_run=str(latest), price_cache=str(price_cache), output_dir=str(out_dir)))
        books = {row["portfolio"]: row for row in payload["books"]}
        assert books["main"]["latest_target_appended"] is False
        assert books["main"]["operating_signal_date"] == ""
        assert books["concentrated"]["latest_target_appended"] is False
        assert books["concentrated"]["operating_signal_date"] == ""

        required_payload = build(
            Namespace(
                latest_run=str(latest),
                price_cache=str(price_cache),
                output_dir=str(out_dir),
                require_current_latest_target=True,
            )
        )
        assert required_payload["status"] == "blocked"
        assert len(required_payload["blocked_books"]) == 2


if __name__ == "__main__":
    test_operating_books_append_latest_close_targets()
    test_operating_books_do_not_use_future_recommended_next_run_date()
    print("operating_target_books_smoke: ok")
