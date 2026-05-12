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

from tools.build_event_target_books import build  # noqa: E402
from tools.run_broker_ledger_replay import replay  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def write_px(cache_dir: Path, ticker: str, closes: list[float], start: str = "2026-01-02") -> None:
    idx = pd.bdate_range(start=start, periods=len(closes))
    frame = pd.DataFrame(
        {
            "Open": closes,
            "Close": closes,
            "Adj Close": closes,
            "Volume": [1_000_000] * len(closes),
        },
        index=idx,
    )
    frame.to_parquet(cache_dir / px_cache_name(ticker))


def test_event_target_book_injects_daily_exit_and_replays() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "outputs"
        reports = latest / "reports"
        cache = root / "cache_prices"
        out = root / "event_target_books"
        reports_out = root / "event_reports"
        broker = root / "event_broker"
        reports.mkdir(parents=True)
        cache.mkdir(parents=True)
        write_px(cache, "AAA", [100, 100, 91, 90, 89, 88, 87, 86, 85, 84, 83, 82])
        write_px(cache, "BBB", [50, 50, 50, 51, 51, 52, 52, 53, 53, 54, 54, 55])
        write_px(cache, "SPY", [400, 400, 400, 401, 401, 402, 402, 403, 403, 404, 404, 405])
        rows = [
            {"rebalance_date": "2026-01-02", "ticker": "AAA", "weight": 0.50},
            {"rebalance_date": "2026-01-02", "ticker": "BBB", "weight": 0.50},
            {"rebalance_date": "2026-01-19", "ticker": "BBB", "weight": 1.00},
        ]
        pd.DataFrame(rows).to_csv(reports / "operating_main_target_book.csv", index=False)
        pd.DataFrame(rows).to_csv(reports / "operating_concentrated_target_book.csv", index=False)

        payload = build(
            Namespace(
                latest_run=str(latest),
                price_cache=str(cache),
                output_dir=str(out),
                reports_dir=str(reports_out),
                main_target_book="",
                concentrated_target_book="",
                benchmark_ticker="SPY",
                hard_stop=-0.08,
                trailing_stop=-0.15,
                trailing_activation=0.15,
                relative_trim_threshold=-0.99,
                relative_exit_threshold=-0.99,
                trim_weight=0.50,
            )
        )
        assert payload["status"] == "completed"
        event_book = pd.read_csv(reports_out / "event_main_target_book.csv")
        assert "2026-01-06" in set(event_book["rebalance_date"].astype(str))
        event_date = event_book[event_book["rebalance_date"].astype(str).eq("2026-01-06")]
        assert "AAA" not in set(event_date["ticker"].astype(str))
        assert "CASH" in set(event_date["ticker"].astype(str))
        events = pd.read_csv(out / "main_events.csv")
        assert "daily_hard_stop_exit" in set(events["action"].astype(str))

        metrics = replay(
            target_book=reports_out / "event_main_target_book.csv",
            price_cache=cache,
            output_dir=broker,
            portfolio_kind="main",
            starting_capital=10_000.0,
            fill_mode="next_close",
            cost_bps=25.0,
        )
        assert metrics["status"] == "completed"
        trades = pd.read_csv(broker / "trades.csv")
        assert "SELL" in set(trades["side"].astype(str))


if __name__ == "__main__":
    test_event_target_book_injects_daily_exit_and_replays()
    print("event_target_books_smoke: PASS")
