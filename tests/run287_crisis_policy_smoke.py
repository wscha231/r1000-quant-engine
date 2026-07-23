#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run287_crisis_policy import (  # noqa: E402
    RESERVE_REASONS,
    adapt_crisis_state,
    apply_selective_defense,
    canonical_state,
    component_availability,
    strip_future_labels,
    transition_state,
)


def complete_values() -> dict[str, float]:
    return {
        "market_trend_damage_score": 0.10,
        "qqq_below_ma200": 0.0,
        "market_breadth_above_ma200": 0.75,
        "hy_oas_zscore_252d": 0.0,
        "vix_zscore_252d": 0.0,
        "liquidity_confirmation_score": 0.10,
        "rate_shock_score": 0.10,
        "market_sector_participation": 0.70,
        "market_leadership_narrowing": 0.10,
    }


def test_future_columns_removed_and_degraded_is_explicit() -> None:
    frame = pd.DataFrame(
        {"crisis_score": [0.1], "future_63d_drawdown": [-0.5], "false_alarm_no_drawdown_63d": [1]}
    )
    clean = strip_future_labels(frame)
    assert list(clean.columns) == ["crisis_score"]
    values = complete_values()
    values.pop("vix_zscore_252d")
    availability = component_availability(values)
    decision = transition_state(
        raw_state="GREEN",
        prior_state="GREEN",
        raw_state_streak=3,
        values=values,
        availability=availability,
    )
    assert decision.state == "DEGRADED_DATA"
    assert "vix" in decision.missing_critical_components
    assert canonical_state(None) == "DEGRADED_DATA"
    assert canonical_state(pd.NA) == "DEGRADED_DATA"
    assert canonical_state("CRISIS_DEFENSE") == "DEGRADED_DATA"
    assert adapt_crisis_state("CRISIS_DEFENSE") == "CRISIS"
    assert adapt_crisis_state("REENTRY_READY", "REENTRY_STAGE_2") == "REENTRY_STAGE_2"
    unknown = transition_state(
        raw_state="MYSTERY_STATE",
        prior_state="GREEN",
        raw_state_streak=1,
        values=complete_values(),
        availability=component_availability(complete_values()),
    )
    assert unknown.state == "DEGRADED_DATA"


def test_boolean_sources_are_strict_and_reentry_does_not_regress_silently() -> None:
    values = complete_values()
    values["vix_stale"] = "false"
    availability = component_availability(values)
    assert next(row for row in availability if row.component == "vix").fresh is True
    values["vix_stale"] = "ambiguous"
    try:
        component_availability(values)
    except ValueError as exc:
        assert "invalid_boolean:vix_stale:ambiguous" in str(exc)
    else:
        raise AssertionError("ambiguous source boolean was accepted")

    weak_recovery = complete_values()
    weak_recovery.update(
        {
            "qqq_below_ma200": 1.0,
            "market_breadth_above_ma200": 0.0,
            "hy_oas_zscore_252d": 2.0,
            "vix_zscore_252d": 2.0,
            "market_leadership_narrowing": 1.0,
        }
    )
    held = transition_state(
        raw_state="GREEN",
        prior_state="REENTRY_STAGE_2",
        raw_state_streak=3,
        values=weak_recovery,
        availability=component_availability(weak_recovery),
    )
    assert held.state == "REENTRY_STAGE_2"
    assert held.transition_reason == "reentry_stage_held_without_new_risk_event"


def test_selective_sell_priority_and_reserve_reconcile() -> None:
    weights = pd.DataFrame(
        [
            {"ticker": "THESIS", "weight": 0.20},
            {"ticker": "TREND", "weight": 0.20},
            {"ticker": "DUP", "weight": 0.20},
            {"ticker": "WINNER", "weight": 0.35},
            {"ticker": "CASH", "weight": 0.05},
        ]
    )
    evidence = pd.DataFrame(
        [
            {"ticker": "THESIS", "confirmed_thesis_break": True, "current_conviction": 0.9},
            {"ticker": "TREND", "severe_rs_trend_break": True, "current_conviction": 0.8},
            {"ticker": "DUP", "duplicated_exposure": True, "current_conviction": 0.7},
            {"ticker": "WINNER", "current_conviction": 1.0},
        ]
    )
    final, actions, summary = apply_selective_defense(
        weights, state="CRISIS", portfolio_kind="main", evidence=evidence
    )
    assert [row["reason"] for row in actions[:3]] == [
        "THESIS_BREAK",
        "RS_TREND_BREAK",
        "DUPLICATED_EXPOSURE",
    ]
    assert float(final.loc[final["ticker"].eq("WINNER"), "weight"].iloc[0]) == 0.35
    assert abs(float(final.loc[final["ticker"].eq("CASH"), "weight"].iloc[0]) - 0.50) < 1e-12
    reasons = summary["reserve_reasons"]
    assert set(reasons) == set(RESERVE_REASONS)
    assert abs(sum(reasons.values()) - 0.50) < 1e-12
    assert reasons["capacity_unallocated"] == 0.05
    assert abs(reasons["crisis_reserve"] - 0.45) < 1e-12
    assert summary["uniform_noncash_scaling_used"] is False


def test_watch_preserves_winner_and_reentry_changes_actual_gross() -> None:
    weights = pd.DataFrame(
        [{"ticker": "LEADER", "weight": 0.80}, {"ticker": "CASH", "weight": 0.20}]
    )
    watch, watch_actions, watch_summary = apply_selective_defense(
        weights, state="WATCH", portfolio_kind="main"
    )
    assert watch_actions == []
    assert abs(float(watch.loc[watch["ticker"].eq("LEADER"), "weight"].iloc[0]) - 0.80) < 1e-12
    stage, stage_actions, stage_summary = apply_selective_defense(
        weights, state="REENTRY_STAGE_1", portfolio_kind="main"
    )
    assert stage_actions
    assert abs(float(stage.loc[stage["ticker"].ne("CASH"), "weight"].sum()) - 0.20) < 1e-12
    assert abs(stage_summary["reserve_reasons"]["reentry_pending"] - 0.60) < 1e-12
    assert watch_summary["policy"]["block_new_buys"] is True


if __name__ == "__main__":
    test_future_columns_removed_and_degraded_is_explicit()
    test_boolean_sources_are_strict_and_reentry_does_not_regress_silently()
    test_selective_sell_priority_and_reserve_reconcile()
    test_watch_preserves_winner_and_reentry_changes_actual_gross()
    print("run287_crisis_policy_smoke: PASS")
