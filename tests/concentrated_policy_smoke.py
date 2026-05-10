#!/usr/bin/env python3
"""Smoke checks for concentrated sleeve policy audit helpers."""
from __future__ import annotations

import sys
from tempfile import TemporaryDirectory
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from r1000_concentrated_policy import (
    audit_concentrated_portfolio,
    entry_gate_flags,
    entry_quality_proxy,
    risk_gate_flags,
)
from r1000_config import EngineConfig
from r1000_pipeline import build_latest_concentrated_holdings, select_concentrated_champion_comparison

import pandas as pd


def test_entry_quality_fallback_from_gate_pass() -> None:
    row = {
        "ticker": "WIN",
        "concentrated_entry_quality_gate_pass": True,
        "price_above_ma50": 1,
        "price_above_ma200": 1,
        "theme_phase_primary": "maturing",
    }
    score, source = entry_quality_proxy(row)
    flags = entry_gate_flags(row)
    assert score >= 0.70
    assert source == "concentrated_entry_quality_gate_pass"
    assert all(flags.values()), flags


def test_entry_quality_fallback_blocks_weak_rows() -> None:
    row = {
        "ticker": "WEAK",
        "price_above_ma50": 1,
        "price_above_ma200": 1,
        "theme_phase_primary": "maturing",
    }
    score, source = entry_quality_proxy(row)
    flags = entry_gate_flags(row)
    assert source == "fallback_proxy"
    assert score < 0.70
    assert flags["price_above_ma50_ok"]
    assert flags["price_above_ma200_ok"]
    assert not flags["entry_quality_ok"]


def test_audit_surfaces_entry_quality_source() -> None:
    holdings = [
        {
            "ticker": "WIN",
            "weight": 0.20,
            "sector": "Technology",
            "price_above_ma50": 1,
            "price_above_ma200": 1,
            "concentrated_entry_quality_gate_pass": True,
            "fundamental_reliability_score": 0.8,
            "rs_acceleration_score": 0.1,
        }
    ]
    audit = audit_concentrated_portfolio(holdings, regime_state="neutral")
    row = audit["rows"][0]
    assert row["entry_gate_pass"] is True
    assert row["entry_quality_proxy"] >= 0.70
    assert row["entry_quality_source"] == "concentrated_entry_quality_gate_pass"


def test_monster_early_override_allows_low_entry_quality() -> None:
    row = {
        "ticker": "MONSTER",
        "entry_quality_score": 0.20,
        "portfolio_monster_early_score": 0.80,
        "portfolio_risk_entry_block_score": 0.20,
        "price_above_ma50": 1,
        "price_above_ma200": 1,
        "theme_phase_primary": "early",
        "fundamental_reliability_score": 0.20,
        "rs_acceleration_score": -0.75,
    }
    entry_flags = entry_gate_flags(row)
    risk_flags = risk_gate_flags(row)
    assert entry_flags["entry_quality_ok"]
    assert all(entry_flags.values()), entry_flags
    assert risk_flags["rs_not_decaying"]
    assert risk_flags["fundamental_reliability_ok"]
    assert all(risk_flags.values()), risk_flags


def test_concentrated_champion_rejects_nan_n1_fallback() -> None:
    cfg = EngineConfig()
    compare = pd.DataFrame(
        [
            {
                "portfolio_mode": "concentrated_alpha",
                "target_stock_names": 1,
                "weighting_mode": "conviction_curve",
                "strategy_cagr": float("nan"),
                "sharpe": float("nan"),
                "max_dd": float("nan"),
                "comparison_objective": float("nan"),
            },
            {
                "portfolio_mode": "concentrated_alpha",
                "target_stock_names": 3,
                "weighting_mode": "score_power",
                "rebalance_interval_months": 1,
                "strategy_cagr": 0.457,
                "sharpe": 1.64,
                "max_dd": -0.206,
                "comparison_objective": 0.56,
            },
        ]
    )
    champion = select_concentrated_champion_comparison(cfg, compare)
    assert int(champion.iloc[0]["target_stock_names"]) == 3
    assert champion.iloc[0]["weighting_mode"] == "score_power"
    assert bool(champion.iloc[0]["concentrated_goal_pass"])


def test_latest_concentrated_uses_grid_champion() -> None:
    cfg = EngineConfig(concentrated_min_entry_quality=0.0)
    latest = pd.DataFrame(
        [
            {
                "rebalance_date": "2026-05-06",
                "ticker": ticker,
                "Name": ticker,
                "sector": "Technology",
                "score": score,
                "portfolio_sleeve_label": "future_winner",
                "selection_confirmation_score": 1.0,
                "price_above_ma50": 1,
                "price_above_ma200": 1,
                "trend_template_full": 1,
                "entry_quality_score": 0.8,
                "portfolio_hold_policy_exit_risk": 0.1,
                "broken_momentum_penalty": 0.0,
                "portfolio_risk_entry_block_score": 0.1,
                "portfolio_monster_early_score": 0.7,
                "breakout_setup_quality_score": 0.8,
                "rs_acceleration_score": 0.2,
                "future_winner_engine_score": 0.8,
                "early_scout_engine_score": 0.6,
                "relative_strength_composite": 0.7,
            }
            for ticker, score in [("AAA", 3.0), ("BBB", 2.8), ("CCC", 2.6)]
        ]
    )
    compare = pd.DataFrame(
        [
            {
                "portfolio_mode": "concentrated_alpha",
                "target_stock_names": 3,
                "weighting_mode": "score_power",
                "rebalance_interval_months": 1,
                "strategy_cagr": 0.45,
                "sharpe": 1.6,
                "max_dd": -0.20,
                "comparison_objective": 0.55,
            }
        ]
    )
    selected, summary = build_latest_concentrated_holdings(cfg, latest, concentrated_compare=compare)
    assert summary["target_stock_names"] == 3
    assert summary["weighting_mode"] == "score_power"
    assert summary["metrics_valid"] is True
    assert summary["target_pass"] is True
    assert len(selected) >= 1
    assert int(selected["target_stock_names"].iloc[0]) == 3


def test_latest_concentrated_reloads_written_grid_artifact() -> None:
    with TemporaryDirectory() as tmp:
        cfg = EngineConfig(base_dir=Path(tmp), concentrated_min_entry_quality=0.0)
        latest = pd.DataFrame(
            [
                {
                    "rebalance_date": "2026-05-06",
                    "ticker": ticker,
                    "Name": ticker,
                    "sector": "Technology",
                    "score": score,
                    "portfolio_sleeve_label": "future_winner",
                    "selection_confirmation_score": 1.0,
                    "price_above_ma50": 1,
                    "price_above_ma200": 1,
                    "trend_template_full": 1,
                    "entry_quality_score": 0.8,
                    "portfolio_hold_policy_exit_risk": 0.1,
                    "broken_momentum_penalty": 0.0,
                    "portfolio_risk_entry_block_score": 0.1,
                    "portfolio_monster_early_score": 0.7,
                    "breakout_setup_quality_score": 0.8,
                    "rs_acceleration_score": 0.2,
                    "future_winner_engine_score": 0.8,
                    "early_scout_engine_score": 0.6,
                    "relative_strength_composite": 0.7,
                }
                for ticker, score in [("AAA", 3.0), ("BBB", 2.8), ("CCC", 2.6)]
            ]
        )
        compare = pd.DataFrame(
            [
                {
                    "portfolio_mode": "concentrated_alpha",
                    "target_stock_names": 3,
                    "weighting_mode": "score_power",
                    "rebalance_interval_months": 1,
                    "strategy_cagr": 0.45,
                    "sharpe": 1.6,
                    "max_dd": -0.20,
                    "comparison_objective": 0.55,
                }
            ]
        )
        reports = Path(tmp) / "outputs" / "reports"
        reports.mkdir(parents=True, exist_ok=True)
        compare.to_csv(reports / "concentrated_strategy_comparison.csv", index=False)

        selected, summary = build_latest_concentrated_holdings(
            cfg,
            latest,
            concentrated_compare=pd.DataFrame(),
        )
        assert summary["target_stock_names"] == 3
        assert summary["weighting_mode"] == "score_power"
        assert summary["metrics_valid"] is True
        assert str(summary["comparison_source"]).endswith("concentrated_strategy_comparison.csv")
        assert len(selected) >= 1


def main() -> int:
    test_entry_quality_fallback_from_gate_pass()
    test_entry_quality_fallback_blocks_weak_rows()
    test_audit_surfaces_entry_quality_source()
    test_monster_early_override_allows_low_entry_quality()
    test_concentrated_champion_rejects_nan_n1_fallback()
    test_latest_concentrated_uses_grid_champion()
    test_latest_concentrated_reloads_written_grid_artifact()
    print("concentrated policy smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
