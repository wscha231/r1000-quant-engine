#!/usr/bin/env python3
"""Smoke checks for theme concentration challenger."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_theme_concentration_challenger import replay  # noqa: E402


def test_theme_concentration_selects_top3_without_future_leak() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        book = root / "candidate_replay_book.csv"
        out = root / "theme_concentration"
        rows = []
        for date in ("2026-01-31", "2026-02-28", "2026-03-31"):
            rows.extend(
                [
                    {
                        "rebalance_date": date,
                        "ticker": "MU",
                        "Name": "Micron Technology",
                        "sector": "Technology",
                        "industry_group": "Semiconductors",
                        "score": 5.0,
                        "mom_1m": 0.20,
                        "mom_3m": 0.35,
                        "mom_6m": 0.55,
                        "r_1m": 0.03,
                        "rs_acceleration_score": 1.0,
                        "industry_group_strength_score": 1.0,
                        "breakout_setup_quality_score": 0.8,
                        "dollar_vol_20d": 500_000_000,
                        "market_cap_live": 100_000_000_000,
                        "current_price_live": 120,
                        "period_forward_return": 0.10,
                    },
                    {
                        "rebalance_date": date,
                        "ticker": "WDC",
                        "Name": "Western Digital",
                        "sector": "Technology",
                        "industry_group": "Storage",
                        "score": 4.8,
                        "mom_1m": 0.18,
                        "mom_3m": 0.30,
                        "mom_6m": 0.45,
                        "r_1m": 0.03,
                        "rs_acceleration_score": 0.9,
                        "industry_group_strength_score": 0.9,
                        "breakout_setup_quality_score": 0.7,
                        "dollar_vol_20d": 300_000_000,
                        "market_cap_live": 30_000_000_000,
                        "current_price_live": 90,
                        "period_forward_return": 0.08,
                    },
                    {
                        "rebalance_date": date,
                        "ticker": "SNDK",
                        "Name": "Sandisk",
                        "sector": "Technology",
                        "industry_group": "Flash Memory",
                        "score": 4.6,
                        "mom_1m": 0.16,
                        "mom_3m": 0.28,
                        "mom_6m": 0.40,
                        "r_1m": 0.03,
                        "rs_acceleration_score": 0.8,
                        "industry_group_strength_score": 0.9,
                        "breakout_setup_quality_score": 0.6,
                        "dollar_vol_20d": 250_000_000,
                        "market_cap_live": 20_000_000_000,
                        "current_price_live": 80,
                        "period_forward_return": 0.06,
                    },
                    {
                        "rebalance_date": date,
                        "ticker": "AAPL",
                        "Name": "Apple",
                        "sector": "Technology",
                        "industry_group": "Consumer Electronics",
                        "score": 4.0,
                        "mom_1m": 0.02,
                        "mom_3m": 0.03,
                        "mom_6m": 0.05,
                        "r_1m": 0.90,
                        "rs_acceleration_score": 0.1,
                        "industry_group_strength_score": 0.1,
                        "breakout_setup_quality_score": 0.1,
                        "dollar_vol_20d": 2_000_000_000,
                        "market_cap_live": 3_000_000_000_000,
                        "current_price_live": 200,
                        "period_forward_return": 0.90,
                    },
                ]
            )
        pd.DataFrame(rows).to_csv(book, index=False)

        metrics = replay(book, out, top_n=3, min_mcap=1_000_000_000, min_dollar_vol=1_000_000)

        assert metrics["status"] == "completed"
        holdings = pd.read_csv(out / "holdings.csv")
        monthly = pd.read_csv(out / "monthly.csv")
        assert holdings.groupby("rebalance_date")["ticker"].nunique().max() <= 3
        assert set(monthly["selected_theme"]) == {"memory_semiconductors"}
        assert set(holdings["ticker"]) == {"MU", "WDC", "SNDK"}
        assert "AAPL" not in set(holdings["ticker"])
        assert metrics["cagr"] > 0


def main() -> int:
    test_theme_concentration_selects_top3_without_future_leak()
    print("theme_concentration_challenger_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
