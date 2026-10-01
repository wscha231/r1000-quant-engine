#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.build_historical_layer_b import build  # noqa: E402
from tools.replay_vnext_layer_b import run  # noqa: E402


def fixture(sign: float = 1.0) -> pd.DataFrame:
    rows = []
    for decision_date in ["2024-01-31", "2024-02-29"]:
        for index in range(30):
            rows.append(
                {
                    "rebalance_date": decision_date,
                    "ticker": f"T{index:02d}",
                    "sector": "Tech" if index < 15 else "Industrials",
                    "industry_group": "Synthetic",
                    "mom_1m": index,
                    "mom_3m": index * 1.1,
                    "mom_6m": index * 1.2,
                    "mom_12m": index * 1.3,
                    "industry_group_strength_score": 60 + index / 10,
                    "sales_growth_yoy": index / 100,
                    "eps_growth_yoy": index / 90,
                    "ocf_growth_yoy": index / 80,
                    "revenue_growth_final": index / 95,
                    "rev_growth_accel_4q": index / 110,
                    "operating_margins": 0.05 + index / 1000,
                    "roe_proxy": 0.08 + index / 1000,
                    "revenues_ttm": 1_000_000 + index * 10_000,
                    "net_income_ttm": 50_000 + index * 1000,
                    "ocf_ttm": 80_000 + index * 1200,
                    "capex_ttm": 20_000 + index * 100,
                    "mktcap": 2_000_000 + index * 20_000,
                    "atr14_pct": 0.05 - index / 2000,
                    "dollar_vol_20d": 1_000_000 + index * 100_000,
                    "regime_state": "neutral",
                    "r_1m": sign * (index - 15) / 100,
                    "y_blend": sign * index,
                    "period_forward_return": sign * (index - 15) / 100,
                }
            )
    return pd.DataFrame(rows)


def test_outcomes_do_not_change_features_or_selection() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        first_path = Path(temp_dir) / "first.csv"
        second_path = Path(temp_dir) / "second.csv"
        fixture(1).to_csv(first_path, index=False)
        fixture(-1).to_csv(second_path, index=False)
        first = build(first_path)
        second = build(second_path)
        feature_keys = ["rebalance_date", "ticker", "leadership_score_b1", "expected_return_confidence_adj_b1", "candidate_discovery_pass_b1"]
        pd.testing.assert_frame_equal(first[feature_keys].reset_index(drop=True), second[feature_keys].reset_index(drop=True), check_dtype=False)
        equity_first, selection_first = run(first, 15, 0.20)
        equity_second, selection_second = run(second, 15, 0.20)
        assert selection_first[["rebalance_date", "ticker", "weight"]].equals(selection_second[["rebalance_date", "ticker", "weight"]])
        assert not equity_first["portfolio_return"].equals(equity_second["portfolio_return"])


def test_missing_fundamentals_not_zero() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        frame = fixture(1)
        frame.loc[frame.ticker == "T29", ["revenues_ttm", "net_income_ttm", "ocf_ttm", "capex_ttm"]] = None
        source = Path(temp_dir) / "source.csv"
        frame.to_csv(source, index=False)
        output = build(source)
        row = output[output.ticker == "T29"].iloc[0]
        assert pd.isna(row["earnings_yield_b1"])
        assert pd.isna(row["fcf_yield_b1"])
        assert row["layer_b_coverage_b1"] < 1.0


if __name__ == "__main__":
    test_outcomes_do_not_change_features_or_selection()
    test_missing_fundamentals_not_zero()
    print("historical_layer_b_smoke: PASS (2 tests)")
