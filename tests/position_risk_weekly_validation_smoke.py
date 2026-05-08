#!/usr/bin/env python3
"""Smoke checks for daily/weekly position-risk validation."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_position_risk_weekly_validation import replay  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def _write_px(cache_dir: Path, ticker: str, closes: list[float], start: str = "2026-02-02") -> None:
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


def test_weekly_validation_uses_daily_path_for_hard_stop() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        latest = root / "outputs"
        reports = latest / "reports"
        out = root / "weekly_validation"
        cache.mkdir(parents=True)
        reports.mkdir(parents=True)

        _write_px(cache, "AAA", [100, 101, 102, 90, 92, 94, 96, 98, 100, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112])
        _write_px(cache, "SPY", [100 + i * 0.2 for i in range(20)])

        pd.DataFrame(
            [
                {
                    "rebalance_date": "2026-01-30",
                    "ticker": "AAA",
                    "weight": 1.0,
                    "sector": "Technology",
                    "portfolio_monster_early_score": 0.1,
                    "portfolio_stale_mega_leader_score": 0.0,
                    "portfolio_risk_entry_block_score": 0.0,
                    "rs_acceleration_score": -1.0,
                }
            ]
        ).to_csv(reports / "main_monthly_weights.csv", index=False)
        pd.DataFrame(
            [{"rebalance_date": "2026-01-30", "next_rebalance_date": "2026-02-27"}]
        ).to_csv(reports / "regime_by_month.csv", index=False)

        payload = replay(
            holdings_path=reports / "main_monthly_weights.csv",
            period_map_path=reports / "regime_by_month.csv",
            price_cache=cache,
            output_dir=out,
            portfolio_kind="main",
            hard_stop=-0.08,
        )
        assert payload["status"] == "completed"
        assert payload["data_mode"] == "daily_price_path_validation_from_monthly_holdings"
        assert payload["exit_count"] == 1
        actions = pd.read_csv(out / "actions.csv")
        assert "daily_hard_stop_exit" in set(actions["action"])
        monthly = pd.read_csv(out / "monthly.csv")
        assert monthly["net_return"].iloc[0] < -0.08
        trades = pd.read_csv(out / "trade_log.csv")
        assert {"BUY", "SELL"}.issubset(set(trades["side"]))
        assert "trade_date" in trades.columns
        assert trades.loc[trades["side"].eq("SELL"), "trade_weight"].iloc[0] == 1.0
        assert (out / "validation_report.md").exists()


def test_concentrated_validation_filters_champion_grid() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        reports = root / "outputs" / "reports"
        out = root / "weekly_validation_concentrated"
        cache.mkdir(parents=True)
        reports.mkdir(parents=True)

        for ticker in ["AAA", "BBB", "CCC", "DDD", "SPY"]:
            _write_px(cache, ticker, [100 + i for i in range(30)])

        rows = [
            {
                "rebalance_date": "2026-01-30",
                "ticker": "AAA",
                "weight": 0.40,
                "target_stock_names": 3,
                "weighting_mode": "score_power",
                "active_rebalance_interval_months": 1,
            },
            {
                "rebalance_date": "2026-01-30",
                "ticker": "BBB",
                "weight": 0.35,
                "target_stock_names": 3,
                "weighting_mode": "score_power",
                "active_rebalance_interval_months": 1,
            },
            {
                "rebalance_date": "2026-01-30",
                "ticker": "CCC",
                "weight": 0.25,
                "target_stock_names": 3,
                "weighting_mode": "score_power",
                "active_rebalance_interval_months": 1,
            },
            {
                "rebalance_date": "2026-01-30",
                "ticker": "DDD",
                "weight": 25.0,
                "target_stock_names": 10,
                "weighting_mode": "winner_take_all",
                "active_rebalance_interval_months": 1,
            },
        ]
        pd.DataFrame(rows).to_csv(reports / "concentrated_strategy_holdings.csv", index=False)
        pd.DataFrame(
            [{"rebalance_date": "2026-01-30", "next_rebalance_date": "2026-02-27"}]
        ).to_csv(reports / "concentrated_strategy_monthly.csv", index=False)

        payload = replay(
            holdings_path=reports / "concentrated_strategy_holdings.csv",
            period_map_path=reports / "concentrated_strategy_monthly.csv",
            price_cache=cache,
            output_dir=out,
            portfolio_kind="concentrated",
        )
        assert payload["status"] == "completed"
        assert payload["max_total_weight"] <= 1.05
        monthly = pd.read_csv(out / "monthly.csv")
        assert monthly["stock_weight_start"].iloc[0] <= 1.05
        positions = pd.read_csv(out / "positions.csv")
        assert "DDD" not in set(positions["ticker"])


def main() -> int:
    test_weekly_validation_uses_daily_path_for_hard_stop()
    test_concentrated_validation_filters_champion_grid()
    print("position_risk_weekly_validation_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
