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

import tools.build_operating_target_books as operating_books  # noqa: E402
from tools.build_operating_target_books import (  # noqa: E402
    build,
    build_book,
    clean_filter_value,
)


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


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
            latest / "reports" / "concentrated_strategy_comparison.csv",
            [
                {
                    "portfolio_mode": "concentrated_alpha",
                    "target_stock_names": 4,
                    "weighting_mode": "score_power",
                    "rebalance_interval_months": 1,
                    "strategy_cagr": 0.30,
                    "sharpe": 1.0,
                    "max_dd": -0.30,
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
        write_csv(
            latest / "sec_enriched_candidate_replay" / "candidate_replay_book_sec_enriched.csv",
            [
                {
                    "rebalance_date": "2026-05-08",
                    "ticker": "ON",
                    "smart_money_score": 0.25,
                    "sec_13f_smart_money_score": 0.5,
                    "sec_combined_evidence_score": 0.7,
                    "latest_available_from": "2026-05-07",
                    "sec_evidence_research_only": True,
                    "sec_evidence_production_activation_allowed": False,
                    "sec_evidence_source": "form4_13f_etf_shadow",
                },
                {
                    "rebalance_date": "2026-06-01",
                    "ticker": "ON",
                    "smart_money_score": 0.99,
                    "sec_13f_smart_money_score": 0.99,
                    "sec_combined_evidence_score": 0.99,
                    "latest_available_from": "2026-06-01",
                    "sec_evidence_research_only": True,
                    "sec_evidence_production_activation_allowed": False,
                    "sec_evidence_source": "form4_13f_etf_shadow",
                },
                {
                    "rebalance_date": "2026-05-08",
                    "ticker": "WDC",
                    "smart_money_score": 0.35,
                    "sec_13f_smart_money_score": 0.6,
                    "sec_combined_evidence_score": 0.8,
                    "latest_available_from": "2026-05-07",
                    "sec_evidence_research_only": True,
                    "sec_evidence_production_activation_allowed": False,
                    "sec_evidence_source": "form4_13f_etf_shadow",
                },
            ],
        )
        original_latest_price_close_date = operating_books.latest_price_close_date
        operating_books.latest_price_close_date = lambda price_cache, tickers: pd.Timestamp("2026-05-08")
        try:
            payload = build(Namespace(latest_run=str(latest), price_cache=str(price_cache), output_dir=str(out_dir)))
        finally:
            operating_books.latest_price_close_date = original_latest_price_close_date
        assert payload["status"] == "completed"

        main = pd.read_csv(out_dir / "operating_main_target_book.csv")
        concentrated = pd.read_csv(out_dir / "operating_concentrated_target_book.csv")
        assert set(main.loc[main["rebalance_date"].eq("2026-05-08"), "ticker"]) == {"ON", "MU"}
        concentrated_latest = concentrated[concentrated["rebalance_date"].eq("2026-05-08")].copy()
        assert set(concentrated_latest["ticker"]) == {"WDC", "SNDK"}
        assert "smart_money_score" in main.columns
        assert "sec_13f_smart_money_score" in main.columns
        assert float(main.loc[main["ticker"].eq("ON"), "smart_money_score"].iloc[-1]) == 0.25
        assert float(concentrated_latest.loc[concentrated_latest["ticker"].eq("WDC"), "sec_13f_smart_money_score"].iloc[-1]) == 0.6
        assert set(concentrated_latest["target_stock_names"].map(clean_filter_value)) == {"4"}
        assert set(concentrated_latest["target_n"].map(clean_filter_value)) == {"4"}
        assert set(concentrated_latest["weighting_mode"].astype(str)) == {"score_power"}
        assert set(concentrated_latest["active_rebalance_interval_months"].map(clean_filter_value)) == {"1"}
        assert main["decision_frequency"].iloc[-1] == "event_driven_latest_close"
        assert concentrated["decision_frequency"].iloc[-1] == "event_driven_latest_close"

        books = {row["portfolio"]: row for row in payload["books"]}
        assert books["main"]["history_max_rebalance_date"] == "2026-02-27"
        assert books["main"]["operating_signal_date"] == "2026-05-08"
        assert books["main"]["latest_target_appended"] is True
        assert books["main"]["sec_evidence_feature_rows_matched"] == 1
        assert books["main"]["sec_evidence_feature_future_rows_excluded"] == 1
        assert "smart_money_score" in books["main"]["sec_evidence_feature_columns_added"]
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


def test_existing_latest_close_row_is_marked_evidence_end_eligible() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        history_path = root / "reports" / "main_monthly_weights.csv"
        latest_target_path = root / "portfolio_latest.csv"
        write_csv(
            history_path,
            [
                {
                    "rebalance_date": "2026-05-08",
                    "ticker": "AAA",
                    "weight": 1.0,
                }
            ],
        )
        write_csv(
            latest_target_path,
            [
                {
                    "rebalance_date": "2026-05-08",
                    "ticker": "AAA",
                    "weight": 1.0,
                }
            ],
        )
        original_latest_price_close_date = (
            operating_books.latest_price_close_date
        )
        operating_books.latest_price_close_date = (
            lambda price_cache, tickers: pd.Timestamp("2026-05-08")
        )
        try:
            book, summary = build_book(
                portfolio="main",
                history_path=history_path,
                latest_target_path=latest_target_path,
                price_cache=root / "cache_prices",
            )
        finally:
            operating_books.latest_price_close_date = (
                original_latest_price_close_date
            )

        assert summary["latest_target_appended"] is False
        latest = book.loc[book["rebalance_date"].eq("2026-05-08")]
        assert latest["operating_appended"].astype(bool).eq(False).all()
        assert (
            latest["operating_evidence_end_eligible"].astype(bool).eq(True).all()
        )
        assert set(latest["operating_latest_price_date"].astype(str)) == {
            "2026-05-08"
        }


if __name__ == "__main__":
    test_operating_books_append_latest_close_targets()
    test_operating_books_do_not_use_future_recommended_next_run_date()
    test_existing_latest_close_row_is_marked_evidence_end_eligible()
    print("operating_target_books_smoke: ok")
