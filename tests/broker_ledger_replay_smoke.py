#!/usr/bin/env python3
"""Smoke checks for broker-ledger replay."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_broker_ledger_replay import replay  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def _write_px(cache_dir: Path, ticker: str, closes: list[float], start: str = "2026-01-02") -> None:
    idx = pd.bdate_range(start=start, periods=len(closes))
    df = pd.DataFrame(
        {
            "Open": closes,
            "Close": closes,
            "Adj Close": closes,
            "Volume": [1_000_000] * len(closes),
        },
        index=idx,
    )
    df.to_parquet(cache_dir / px_cache_name(ticker))


def test_broker_replay_tracks_integer_shares_and_cash() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        out = root / "broker"
        cache.mkdir()
        _write_px(cache, "AAA", [100.0, 101.0, 110.0, 120.0, 130.0, 140.0, 150.0])
        _write_px(cache, "BBB", [50.0, 50.0, 50.0, 50.0, 50.0, 50.0, 50.0])
        target = root / "targets.csv"
        pd.DataFrame(
            [
                {"rebalance_date": "2026-01-02", "ticker": "AAA", "weight": 0.60},
                {"rebalance_date": "2026-01-02", "ticker": "BBB", "weight": 0.30},
                {"rebalance_date": "2026-01-09", "ticker": "AAA", "weight": 1.00},
            ]
        ).to_csv(target, index=False)

        metrics = replay(
            target_book=target,
            price_cache=cache,
            output_dir=out,
            portfolio_kind="main",
            starting_capital=10_000.0,
            fill_mode="next_close",
            cost_bps=25.0,
            integer_shares=True,
        )

        assert metrics["status"] == "completed"
        assert metrics["metric_mode"] == "broker_ledger_next_close"
        assert metrics["valid_for_production"] is True
        assert metrics["ending_capital_usd"] > 10_000.0
        trades = pd.read_csv(out / "trades.csv")
        assert {"BUY", "SELL"}.intersection(set(trades["side"]))
        assert (trades["quantity"] % 1 == 0).all()
        cash = pd.read_csv(out / "cash_ledger.csv")
        assert cash["cash_usd"].min() >= -1e-6
        curve = pd.read_csv(out / "equity_curve.csv")
        assert curve["date"].min() >= "2026-01-02"
        assert (out / "holdings_daily.csv").exists()
        assert (out / "target_vs_actual_weights.csv").exists()


def test_broker_replay_blocks_contaminated_weight_book() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        out = root / "broker"
        cache.mkdir()
        _write_px(cache, "AAA", [100.0, 101.0, 102.0])
        target = root / "targets.csv"
        pd.DataFrame(
            [
                {"rebalance_date": "2026-01-02", "ticker": "AAA", "weight": 0.80},
                {"rebalance_date": "2026-01-02", "ticker": "BBB", "weight": 0.80},
            ]
        ).to_csv(target, index=False)
        metrics = replay(
            target_book=target,
            price_cache=cache,
            output_dir=out,
            portfolio_kind="main",
            starting_capital=10_000.0,
        )
        assert metrics["status"] == "blocked"
        assert metrics["invalid_weight_date_count"] == 1


def test_broker_replay_does_not_backdate_sparse_history_fill() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        out = root / "broker"
        cache.mkdir()
        _write_px(cache, "AAA", [100.0, 105.0, 110.0, 115.0], start="2026-01-02")
        _write_px(cache, "LATE", [10.0, 11.0, 12.0], start="2026-03-02")
        target = root / "targets.csv"
        pd.DataFrame(
            [
                {"rebalance_date": "2026-01-02", "ticker": "AAA", "weight": 0.50},
                {"rebalance_date": "2026-01-02", "ticker": "LATE", "weight": 0.40},
            ]
        ).to_csv(target, index=False)

        metrics = replay(
            target_book=target,
            price_cache=cache,
            output_dir=out,
            portfolio_kind="main",
            starting_capital=10_000.0,
            max_fill_lag_days=7,
        )

        assert metrics["status"] == "completed"
        trades = pd.read_csv(out / "trades.csv")
        assert "LATE" not in set(trades["ticker"])


def main() -> int:
    test_broker_replay_tracks_integer_shares_and_cash()
    test_broker_replay_blocks_contaminated_weight_book()
    test_broker_replay_does_not_backdate_sparse_history_fill()
    print("broker_ledger_replay_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
