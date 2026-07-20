#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.build_crisis_governed_target_books import build_governed_book  # noqa: E402
from tools.run_broker_ledger_replay import replay  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def _write_px(cache_dir: Path, ticker: str, closes: list[float], start: str = "2026-01-02") -> None:
    idx = pd.bdate_range(start=start, periods=len(closes))
    pd.DataFrame(
        {
            "Open": closes,
            "Close": closes,
            "Adj Close": closes,
            "Volume": [1_000_000] * len(closes),
        },
        index=idx,
    ).to_parquet(cache_dir / px_cache_name(ticker))


def test_crisis_governed_target_book_materializes_broker_replay_rows() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        cache.mkdir()
        _write_px(cache, "AAA", [100, 99, 92, 90, 88, 87, 86, 85, 84, 83, 82, 81])
        _write_px(cache, "BBB", [50, 50, 50, 50, 50, 50, 51, 51, 52, 52, 53, 53])

        target = root / "target.csv"
        pd.DataFrame(
            [
                {"rebalance_date": "2026-01-02", "ticker": "AAA", "weight": 0.60},
                {"rebalance_date": "2026-01-02", "ticker": "BBB", "weight": 0.35},
                {"rebalance_date": "2026-01-02", "ticker": "CASH", "weight": 0.05},
            ]
        ).to_csv(target, index=False)

        features = root / "daily_features.parquet"
        fidx = pd.bdate_range("2026-01-02", periods=12)
        feat = pd.DataFrame(index=fidx)
        feat["crisis_score"] = 0.05
        feat.loc[fidx[2:8], "crisis_score"] = 0.85
        feat["market_trend_damage_score"] = 0.05
        feat.loc[fidx[2:8], "market_trend_damage_score"] = 0.75
        feat["qqq_below_ma200"] = 0.0
        feat.loc[fidx[2:8], "qqq_below_ma200"] = 1.0
        feat["credit_stress_score"] = 0.05
        feat.loc[fidx[2:8], "credit_stress_score"] = 0.65
        feat["volatility_stress_score"] = 0.10
        feat.loc[fidx[2:8], "volatility_stress_score"] = 0.80
        feat.to_parquet(features)

        book, audit, summary = build_governed_book(
            target_book=target,
            crisis_features=features,
            portfolio_kind="main",
            mode="conservative",
        )
        assert summary["status"] == "completed"
        assert summary["research_only"] is True
        assert summary["valid_for_production"] is False
        assert audit["cash_weight"].max() >= 0.25
        crisis_dates = set(audit[audit["crisis_zone"].eq("crisis")]["snapshot_date"])
        assert crisis_dates

        governed = root / "governed.csv"
        book.to_csv(governed, index=False)
        metrics = replay(
            target_book=governed,
            price_cache=cache,
            output_dir=root / "broker",
            portfolio_kind="main",
            starting_capital=10_000.0,
            fill_mode="next_close",
            cost_bps=25.0,
            integer_shares=True,
        )
        assert metrics["status"] == "completed"
        assert metrics["metric_mode"] == "broker_ledger_next_close"
        trades = pd.read_csv(root / "broker" / "trades.csv")
        assert "SELL" in set(trades["side"].astype(str))


if __name__ == "__main__":
    test_crisis_governed_target_book_materializes_broker_replay_rows()
    print("crisis_governed_target_books_smoke: PASS")
