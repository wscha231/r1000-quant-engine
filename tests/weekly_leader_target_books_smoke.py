#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from argparse import Namespace
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.build_weekly_leader_target_books import build  # noqa: E402
from tools.run_broker_ledger_replay import replay  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def write_px(cache_dir: Path, ticker: str, closes: list[float], start: str = "2026-01-02") -> None:
    idx = pd.bdate_range(start=start, periods=len(closes))
    frame = pd.DataFrame(
        {
            "Open": closes,
            "Close": closes,
            "Adj Close": closes,
            "Volume": [2_000_000] * len(closes),
        },
        index=idx,
    )
    frame.to_parquet(cache_dir / px_cache_name(ticker))


def test_weekly_leader_book_adds_new_entry_and_replays() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "outputs"
        reports = latest / "reports"
        cache = root / "cache_prices"
        out = root / "weekly_leaders"
        reports_out = root / "event_reports"
        broker = root / "broker"
        reports.mkdir(parents=True)
        cache.mkdir(parents=True)

        # AAA becomes the weekly leader after the base monthly target bought BBB.
        write_px(cache, "AAA", [20, 21, 22, 24, 27, 30, 32, 34, 35, 36, 38, 40, 42, 44, 45, 46])
        write_px(cache, "BBB", [50, 50, 50, 51, 51, 51, 52, 52, 52, 52, 53, 53, 53, 53, 54, 54])
        write_px(cache, "SPY", [400, 400, 401, 401, 402, 402, 403, 403, 404, 404, 405, 405, 406, 406, 407, 407])

        candidate_rows = [
            {
                "rebalance_date": "2026-01-02",
                "ticker": "AAA",
                "score": 9.0,
                "portfolio_monster_early_score": 1.0,
                "h6_dynamic_leader_score": 1.0,
                "breakout_setup_quality_score": 1.0,
                "industry_group_strength_score": 1.0,
                "future_winner_scout_score": 1.0,
                "market_cap_live": 12_000_000_000,
                "current_price_live": 20.0,
                "dollar_vol_20d": 40_000_000,
                "regime_state": "bull",
            },
            {
                "rebalance_date": "2026-01-02",
                "ticker": "BBB",
                "score": 3.0,
                "portfolio_monster_early_score": 0.0,
                "h6_dynamic_leader_score": 0.0,
                "breakout_setup_quality_score": 0.0,
                "industry_group_strength_score": 0.0,
                "future_winner_scout_score": 0.0,
                "market_cap_live": 20_000_000_000,
                "current_price_live": 50.0,
                "dollar_vol_20d": 100_000_000,
                "regime_state": "bull",
            },
            {
                "rebalance_date": "2026-01-30",
                "ticker": "BBB",
                "score": 4.0,
                "market_cap_live": 20_000_000_000,
                "current_price_live": 54.0,
                "dollar_vol_20d": 100_000_000,
                "regime_state": "bull",
            },
        ]
        pd.DataFrame(candidate_rows).to_csv(reports / "candidate_replay_book.csv", index=False)
        base_rows = [
            {"rebalance_date": "2026-01-02", "ticker": "BBB", "weight": 1.0},
            {"rebalance_date": "2026-01-30", "ticker": "BBB", "weight": 1.0},
        ]
        pd.DataFrame(base_rows).to_csv(reports / "operating_main_target_book.csv", index=False)
        pd.DataFrame(base_rows).to_csv(reports / "operating_concentrated_target_book.csv", index=False)

        payload = build(
            Namespace(
                latest_run=str(latest),
                candidate_book="",
                price_cache=str(cache),
                output_dir=str(out),
                reports_dir=str(reports_out),
                main_target_book="",
                concentrated_target_book="",
                benchmark_ticker="SPY",
                min_mcap=1_000_000_000,
                min_dollar_vol=1_000_000,
                min_price=5.0,
                snapshot_top_k=5,
                main_top_n=1,
                concentrated_top_n=1,
                main_single_cap=0.33,
                concentrated_single_cap=0.50,
                min_score_quantile=0.0,
            )
        )
        assert payload["status"] == "completed"
        target = pd.read_csv(reports_out / "weekly_leader_main_target_book.csv")
        weekly = target[target["event_kind"].astype(str).eq("weekly_leader_entry")]
        assert not weekly.empty
        assert "weekly_ret_2w" in weekly.columns
        assert "weekly_rs_2w" in weekly.columns
        assert "AAA" in set(weekly["ticker"].astype(str))
        aaa_weight = float(weekly.loc[weekly["ticker"].astype(str).eq("AAA"), "weight"].max())
        assert aaa_weight > 0.20

        metrics = replay(
            target_book=reports_out / "weekly_leader_main_target_book.csv",
            price_cache=cache,
            output_dir=broker,
            portfolio_kind="main",
            starting_capital=10_000.0,
            fill_mode="next_close",
            cost_bps=25.0,
        )
        assert metrics["status"] == "completed"
        trades = pd.read_csv(broker / "trades.csv")
        assert "AAA" in set(trades["ticker"].astype(str))
        assert "BUY" in set(trades.loc[trades["ticker"].astype(str).eq("AAA"), "side"].astype(str))


def test_weekly_signal_date_does_not_collide_with_monthly_rebalance() -> None:
    """When a weekly W-FRI signal falls on a non-trading day (e.g. holiday),
    price_on_or_before historically back-shifted the snapshot's
    ``weekly_signal_date`` to the last actual close. If that last close
    happened to BE the monthly rebalance boundary, the build process
    emitted both ``scheduled_rebalance`` and ``weekly_leader_entry``
    rows for the same date and the broker-ledger replay refused to
    accept the resulting 2.0 stock weight.

    This test exercises the collision condition with synthetic prices
    that have a gap precisely on the monthly boundary and verifies the
    target book reports total_weight <= 1.0 per rebalance_date plus a
    successful broker-replay execution.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "outputs"
        reports = latest / "reports"
        cache = root / "cache_prices"
        out = root / "weekly_leaders"
        reports_out = root / "event_reports"
        broker = root / "broker"
        reports.mkdir(parents=True)
        cache.mkdir(parents=True)

        # Build a price series that includes a non-trading boundary day
        # by writing two monthly periods 2024-02-29 -> 2024-03-28, with
        # the W-FRI on 2024-03-29 (Good Friday) MISSING from price data.
        # If the bug were live, the second period's weekly signals would
        # back-shift to 2024-03-28 and collide.
        bdates = pd.bdate_range(start="2024-01-02", end="2024-04-30")
        # Drop Good Friday explicitly (it would be 2024-03-29).
        bdates = bdates[bdates != pd.Timestamp("2024-03-29")]
        closes_aaa = [20.0 + 0.5 * i for i in range(len(bdates))]
        closes_bbb = [50.0 + 0.1 * i for i in range(len(bdates))]
        closes_spy = [400.0 + 0.2 * i for i in range(len(bdates))]
        for ticker, closes in [("AAA", closes_aaa), ("BBB", closes_bbb), ("SPY", closes_spy)]:
            frame = pd.DataFrame(
                {
                    "Open": closes,
                    "Close": closes,
                    "Adj Close": closes,
                    "Volume": [2_000_000] * len(closes),
                },
                index=bdates,
            )
            frame.to_parquet(cache / px_cache_name(ticker))

        # Candidate book with two adjacent monthly periods so the second
        # period's weekly signals will be generated for 2024-04 W-FRIs.
        candidate_rows = [
            {
                "rebalance_date": "2024-02-29",
                "ticker": "AAA",
                "score": 9.0,
                "portfolio_monster_early_score": 1.0,
                "h6_dynamic_leader_score": 1.0,
                "breakout_setup_quality_score": 1.0,
                "industry_group_strength_score": 1.0,
                "future_winner_scout_score": 1.0,
                "market_cap_live": 12_000_000_000,
                "current_price_live": 20.0,
                "dollar_vol_20d": 40_000_000,
                "regime_state": "bull",
            },
            {
                "rebalance_date": "2024-02-29",
                "ticker": "BBB",
                "score": 3.0,
                "portfolio_monster_early_score": 0.0,
                "h6_dynamic_leader_score": 0.0,
                "breakout_setup_quality_score": 0.0,
                "industry_group_strength_score": 0.0,
                "future_winner_scout_score": 0.0,
                "market_cap_live": 20_000_000_000,
                "current_price_live": 50.0,
                "dollar_vol_20d": 100_000_000,
                "regime_state": "bull",
            },
            {
                "rebalance_date": "2024-03-28",
                "ticker": "AAA",
                "score": 9.0,
                "market_cap_live": 12_000_000_000,
                "current_price_live": 50.0,
                "dollar_vol_20d": 40_000_000,
                "regime_state": "bull",
            },
            {
                "rebalance_date": "2024-03-28",
                "ticker": "BBB",
                "score": 3.0,
                "market_cap_live": 20_000_000_000,
                "current_price_live": 60.0,
                "dollar_vol_20d": 100_000_000,
                "regime_state": "bull",
            },
        ]
        pd.DataFrame(candidate_rows).to_csv(reports / "candidate_replay_book.csv", index=False)
        base_rows = [
            {"rebalance_date": "2024-02-29", "ticker": "BBB", "weight": 1.0},
            {"rebalance_date": "2024-03-28", "ticker": "BBB", "weight": 1.0},
        ]
        pd.DataFrame(base_rows).to_csv(reports / "operating_main_target_book.csv", index=False)
        pd.DataFrame(base_rows).to_csv(reports / "operating_concentrated_target_book.csv", index=False)

        payload = build(
            Namespace(
                latest_run=str(latest),
                candidate_book="",
                price_cache=str(cache),
                output_dir=str(out),
                reports_dir=str(reports_out),
                main_target_book="",
                concentrated_target_book="",
                benchmark_ticker="SPY",
                min_mcap=1_000_000_000,
                min_dollar_vol=1_000_000,
                min_price=5.0,
                snapshot_top_k=5,
                main_top_n=1,
                concentrated_top_n=1,
                main_single_cap=0.33,
                concentrated_single_cap=0.50,
                min_score_quantile=0.0,
            )
        )
        assert payload["status"] == "completed", payload
        target = pd.read_csv(reports_out / "weekly_leader_main_target_book.csv")
        # No date should have stock weight > 1.0 + epsilon now.
        per_date = target.groupby("rebalance_date")["weight"].sum()
        assert (per_date <= 1.0 + 1e-6).all(), per_date[per_date > 1.0 + 1e-6]
        # And the broker replay must accept the book (not blocked by weight sum).
        metrics = replay(
            target_book=reports_out / "weekly_leader_main_target_book.csv",
            price_cache=cache,
            output_dir=broker,
            portfolio_kind="main",
            starting_capital=10_000.0,
            fill_mode="next_close",
            cost_bps=25.0,
        )
        assert metrics["status"] == "completed", metrics
        assert float(metrics.get("max_total_weight") or 0) <= 1.0 + 1e-6


if __name__ == "__main__":
    test_weekly_leader_book_adds_new_entry_and_replays()
    test_weekly_signal_date_does_not_collide_with_monthly_rebalance()
    print("weekly_leader_target_books_smoke: PASS")
