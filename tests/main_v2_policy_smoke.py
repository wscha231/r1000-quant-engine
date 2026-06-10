#!/usr/bin/env python3
"""Smoke tests for research-only Main v2, concentrated policy, and sprint sidecars."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from r1000_alpha_sprint import build_alpha_sprint_snapshot  # noqa: E402
from r1000_concentrated_policy import audit_concentrated_portfolio  # noqa: E402
from r1000_main_v2 import compose_main_sleeve_portfolio  # noqa: E402
from r1000_orchestrator import audit_unified_portfolio, compose_unified_portfolio  # noqa: E402


def base_row(ticker: str, score: float) -> dict:
    return {
        "ticker": ticker,
        "Name": ticker,
        "sector": "Information Technology",
        "score": score,
        "regime_state": "neutral",
        "fundamental_reliability_score": 0.85,
        "price_above_ma50": 1,
        "price_above_ma200": 1,
        "portfolio_core_compounder_engine_score": score,
        "portfolio_future_winner_engine_score": score,
        "portfolio_early_scout_engine_score": score,
        "long_hold_compounder_score": score,
        "capital_efficiency_score": score,
        "sector_adjusted_quality_score": score,
        "multi_year_winner_score": score,
        "future_winner_scout_score": score,
        "rs_acceleration_score": score,
        "oneil_leadership_score": score,
        "industry_group_strength_score": score,
        "theme_phase_multiplier_primary": 1.10,
        "theme_phase_multiplier_max": 1.10,
        "profitability_inflection_score": score,
        "profit_turn_positive_4q": 1,
        "cashflow_turn_positive_4q": 1,
        "post_breakout_hold_score": 0.80,
        "risk_penalty": 0,
        "stage2_overext_penalty": 0,
    }


def test_main_v2_shadow() -> None:
    rows = [base_row("AAA", 3.0), base_row("BBB", 2.5), base_row("CCC", 2.0), base_row("DDD", 1.5)]
    result = compose_main_sleeve_portfolio(rows, regime_state="neutral")
    weights = result["main_v2_weights"]
    assert weights
    assert result["audit"]["research_only"] is True
    assert result["audit"]["production_activation_allowed"] is False
    assert max(weights.values()) <= 0.15000001
    assert result["audit"]["n_conflicts"] >= 1
    assert abs(sum(weights.values()) + result["cash_target"] - 1.0) < 1e-9


def test_concentrated_policy_audit() -> None:
    holdings = [{"ticker": "AAA", "weight": 0.30, "sector": "Tech"}]
    scored = [
        {
            "ticker": "AAA",
            "entry_quality_score": 0.20,
            "price_above_ma50": 1,
            "price_above_ma200": 1,
            "fundamental_reliability_score": 0.80,
            "rs_acceleration_score": 0.50,
        }
    ]
    audit = audit_concentrated_portfolio(holdings, scored_rows=scored, regime_state="neutral")
    assert audit["recommended_capacity"] == 0.20
    assert audit["cap_violations"]
    assert audit["entry_blocked"]
    assert audit["audit"]["production_activation_allowed"] is False


def sprint_row(ticker: str, score: float) -> dict:
    row = base_row(ticker, score)
    row.update(
        {
            "regime_state": "bull",
            "market_cap_live": 5_000_000_000,
            "current_price_live": 50,
            "dollar_vol_20d": 50_000_000,
            "near_52w_high_pct": -0.03,
            "breakout_fresh_20d": 1,
            "breakout_volume_z": 1,
            "volume_dryup_20d": 0.2,
            "volatility_contraction_score": 0.5,
            "breakout_setup_quality_score": 1.0,
            "explosion_entry_score": 0.5,
            "explosion_exit_score": 0.0,
            "h6_dynamic_leader_score": 0.7,
            "eps_revision_score": 1.0,
            "live_event_risk_score": 0.0,
            "atr14_pct": 0.04,
            "rsi14": 65,
        }
    )
    return row


def test_alpha_sprint_activation() -> None:
    rows = [sprint_row("AAA", 2.0), sprint_row("BBB", 1.8), sprint_row("CCC", 1.5)]
    bull = build_alpha_sprint_snapshot(rows, regime_state="bull")
    assert bull["audit"]["candidate_count"] >= 2
    assert bull["portfolio"]["activation"]["active"] is True
    assert sum(bull["portfolio"]["weights"].values()) <= 0.05000001
    neutral = build_alpha_sprint_snapshot(rows, regime_state="neutral")
    assert neutral["portfolio"]["activation"]["active"] is False
    assert neutral["portfolio"]["weights"] == {}


def test_orchestrator_arbitrary_mandates() -> None:
    result = compose_unified_portfolio(
        mandate_weights={
            "main": {"AAA": 1.0},
            "concentrated": {"AAA": 1.0},
            "alpha_sprint": {"BBB": 1.0},
        },
        regime_state="bull",
        merge_mode="sum_then_cap",
        unified_single_name_cap=0.18,
        capacity_override={"main": 0.60, "concentrated": 0.20, "alpha_sprint": 0.10},
    )
    assert result["unified_weights"]["AAA"] == 0.18
    assert result["unified_weights"]["BBB"] == 0.10
    assert result["by_mandate_capacity"]["alpha_sprint"] == 0.10
    assert audit_unified_portfolio(result)["all_passed"] is True


if __name__ == "__main__":
    test_main_v2_shadow()
    test_concentrated_policy_audit()
    test_alpha_sprint_activation()
    test_orchestrator_arbitrary_mandates()
    print("main_v2_policy_smoke: ok")
