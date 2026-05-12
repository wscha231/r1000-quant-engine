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


if __name__ == "__main__":
    test_weekly_leader_book_adds_new_entry_and_replays()
    print("weekly_leader_target_books_smoke: PASS")
