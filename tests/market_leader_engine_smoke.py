#!/usr/bin/env python3
"""Smoke checks for the research-only Market Leader engine."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from r1000_market_leader_engine import (  # noqa: E402
    MarketLeaderVariant,
    load_prices,
    score_market_leaders,
    select_market_leader_targets,
)
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def write_price(cache: Path, ticker: str, start: float, daily_ret: float) -> None:
    dates = pd.date_range("2024-01-02", "2025-08-29", freq="B")
    values = [start * ((1.0 + daily_ret) ** i) for i in range(len(dates))]
    pd.DataFrame({"date": dates, "Adj Close": values, "Close": values, "Open": values}, index=dates).to_parquet(cache / px_cache_name(ticker))


def base_rows() -> list[dict[str, object]]:
    return [
        {
            "rebalance_date": "2025-08-29",
            "ticker": "DUAL",
            "Name": "Dual Leader",
            "sector": "Technology",
            "industry_group_strength_score": 2.0,
            "industry_within_leader_rank": 1.0,
            "oneil_leadership_score": 1.0,
            "sub_industry_rs_score": 1.0,
            "industry_leader_gap": 1.0,
            "future_winner_confirmation_score": 1.0,
            "quality_growth_score": 0.8,
            "entry_quality_score": 0.7,
            "dollar_vol_20d": 500_000_000,
            "market_cap_live": 50_000_000_000,
            "price_above_ma50": 1,
            "price_above_ma200": 1,
            "sec_form4_cluster_buy_score": 0.8,
        },
        {
            "rebalance_date": "2025-08-29",
            "ticker": "SPYONLY",
            "Name": "SPY Only Leader",
            "sector": "Industrials",
            "industry_group_strength_score": 1.8,
            "industry_within_leader_rank": 1.0,
            "oneil_leadership_score": 0.8,
            "sub_industry_rs_score": 0.8,
            "industry_leader_gap": 0.7,
            "future_winner_confirmation_score": 0.9,
            "quality_growth_score": 0.8,
            "entry_quality_score": 0.6,
            "dollar_vol_20d": 500_000_000,
            "market_cap_live": 40_000_000_000,
            "price_above_ma50": 1,
            "price_above_ma200": 1,
        },
        {
            "rebalance_date": "2025-08-29",
            "ticker": "LAGG",
            "Name": "Lagging Stock",
            "sector": "Technology",
            "industry_group_strength_score": -1.0,
            "dollar_vol_20d": 500_000_000,
            "market_cap_live": 40_000_000_000,
            "price_above_ma50": 0,
            "price_above_ma200": 1,
        },
    ]


def test_dual_benchmark_tier_and_concentrated_gate() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cache = Path(tmp)
        write_price(cache, "SPY", 100, 0.0005)
        write_price(cache, "QQQ", 100, 0.0010)
        write_price(cache, "DUAL", 100, 0.0018)
        write_price(cache, "SPYONLY", 100, 0.0007)
        write_price(cache, "LAGG", 100, -0.0005)
        frame = pd.DataFrame(base_rows())
        prices = load_prices(cache, {"SPY", "QQQ", "DUAL", "SPYONLY", "LAGG"})
        scored = score_market_leaders(frame, prices, "2025-08-29")
        tiers = dict(zip(scored["ticker"], scored["leader_tier"]))
        assert tiers["DUAL"] == "DUAL_LEADER"
        assert tiers["SPYONLY"] != "DUAL_LEADER"
        assert tiers["LAGG"] == "LAGGING"
        selected = select_market_leader_targets(
            scored,
            MarketLeaderVariant("concentrated", "test", 3, 0.45, 0.80, 1.0),
        )
        assert set(selected["ticker"]) == {"DUAL"}


def test_missing_evidence_is_confidence_not_quality_zero() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cache = Path(tmp)
        for ticker, ret in {"SPY": 0.0005, "QQQ": 0.0010, "DUAL": 0.0018}.items():
            write_price(cache, ticker, 100, ret)
        rows = [base_rows()[0], base_rows()[2]]
        for row in rows:
            for key in list(row):
                if key.startswith("sec_") or key.startswith("etf_"):
                    row.pop(key)
        frame = pd.DataFrame(rows)
        prices = load_prices(cache, {"SPY", "QQQ", "DUAL", "LAGG"})
        scored = score_market_leaders(frame, prices, "2025-08-29")
        dual = scored[scored["ticker"].eq("DUAL")].iloc[0]
        lagg = scored[scored["ticker"].eq("LAGG")].iloc[0]
        assert float(dual["smart_money_evidence_confidence"]) == 0.0
        assert float(dual["concentrated_leader_score"]) > float(lagg["concentrated_leader_score"])


def test_shakeout_guard_blocks_exit_on_one_month_wobble() -> None:
    row = pd.Series(
        {
            "rs_qqq_1m": -0.02,
            "rs_qqq_3m": 0.05,
            "rs_qqq_6m": 0.20,
            "sector_leadership_score": 1.0,
            "price_above_ma50": 1,
            "price_above_ma200": 1,
            "smart_money_evidence_confidence": 0.5,
            "systemic_crisis_score": 0.1,
        }
    )
    from r1000_market_leader_engine import classify_leader_state

    state, reason = classify_leader_state(row)
    assert state == "SHAKEOUT_GUARD"
    assert "leadership_intact" in reason


def test_warning_is_no_add_but_previous_holding_can_persist() -> None:
    scored = pd.DataFrame(
        [
            {
                "ticker": "WARN",
                "leader_tier": "DUAL_LEADER",
                "leader_state": "WARNING",
                "warning_streak": 1,
                "liquidity_capacity_weight_cap": 1.0,
                "main_leader_score": 10.0,
                "concentrated_leader_score": 10.0,
                "leader_subindustry": "chips",
                "leader_broad_theme": "semis",
            },
            {
                "ticker": "HOLD",
                "leader_tier": "DUAL_LEADER",
                "leader_state": "HOLD",
                "warning_streak": 0,
                "liquidity_capacity_weight_cap": 1.0,
                "main_leader_score": 1.0,
                "concentrated_leader_score": 1.0,
                "leader_subindustry": "software",
                "leader_broad_theme": "software",
            },
        ]
    )
    variant = MarketLeaderVariant("main", "test", 2, 0.50, 1.0, 1.0)
    fresh = select_market_leader_targets(scored, variant)
    assert "WARN" not in set(fresh["ticker"])
    persisted = select_market_leader_targets(scored, variant, prev_holdings={"WARN": 0.25})
    assert "WARN" in set(persisted["ticker"])
    warn = persisted[persisted["ticker"].eq("WARN")].iloc[0]
    assert "warning_hold_no_add" in str(warn["selection_reason"])


def main() -> int:
    test_dual_benchmark_tier_and_concentrated_gate()
    test_missing_evidence_is_confidence_not_quality_zero()
    test_shakeout_guard_blocks_exit_on_one_month_wobble()
    test_warning_is_no_add_but_previous_holding_can_persist()
    print("market_leader_engine_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
