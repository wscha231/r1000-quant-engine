#!/usr/bin/env python3
"""Smoke tests for the read-only daily operating-model review."""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.build_operating_model_review import build_review, render_markdown  # noqa: E402


def account_payload() -> dict:
    return {
        "official_metric_mode": "broker_ledger_next_close",
        "target_type": "interim_operating_gate",
        "target_contract_status": "unresolved_user_decision_required",
        "target_contract": {
            "canonical_mission": {
                "main": {"cagr": 0.35, "max_dd": -0.25},
                "concentrated": {"cagr": 0.50, "max_dd": -0.25},
            }
        },
        "strengthened_pass": False,
        "portfolios": {
            "main": {
                "valid_for_production": True,
                "end_date": "2026-08-20",
                "cagr": 0.36,
                "max_dd": -0.24,
                "strengthened_pass": True,
            },
            "concentrated": {
                "valid_for_production": True,
                "end_date": "2026-08-20",
                "cagr": 0.49,
                "max_dd": -0.23,
                "strengthened_pass": False,
                "tier2_failing": ["oos_is_cagr_ratio_max"],
            },
        },
    }


def cadence_payload() -> dict:
    return {
        "production_mutated": False,
        "daily_decision_scope": ["crisis/reentry state"],
        "weekly_decision_scope": ["watchlist refresh"],
        "monthly_or_event_decision_scope": ["full universe re-ranking"],
        "full_universe_rerank_frequency": "monthly_or_event_triggered",
        "mid_month_reentry_allowed": True,
        "abcd_cadence_challenger": {
            "contract_ready": True,
            "accepted_champion": "A",
            "recommended_operating_candidate": "D",
            "historical_backtest_executed": False,
        },
    }


def catalog_payload() -> dict:
    names = (
        "price_cache_dir",
        "macro_daily_snapshot",
        "companyfacts_zip",
        "sec_13f_holdings",
        "form4_transactions",
        "forward_earnings_estimate_snapshots",
        "forward_earnings_revision_signals",
    )
    return {
        "health": "ok",
        "datasets": [
            {
                "name": name,
                "status": "ok",
                "freshness": "fresh",
                "modified_utc": "2026-08-21T00:00:00+00:00",
            }
            for name in names
        ],
    }


def test_review_separates_evidence_blockers_from_research_review_items() -> None:
    payload = build_review(
        {
            "status": "warn",
            "ready_for_policy_replay": True,
            "ready_for_fullrun": False,
            "latest_observable_close_date": "2026-08-20",
            "latest_target_date": "2026-08-19",
        },
        {"status": "ok", "primary_weekly_eval_date": "2026-08-20"},
        account_payload(),
        cadence_payload(),
        catalog_payload(),
        sources={},
    )

    assert payload["status"] == "RESEARCH_REVIEW_REQUIRED"
    assert payload["blockers"] == []
    assert "concentrated_canonical_mission_not_met" in payload["review_items"]
    assert "concentrated_strengthened_gates_not_met" in payload["review_items"]
    assert "target_contract_unresolved_user_decision_required" in payload["review_items"]
    assert payload["official_evaluation"]["canonical_mission_checks"]["main"]["canonical_mission_pass"] is True
    assert payload["rebalance_plan"]["accepted_champion"] == "A"
    assert payload["rebalance_plan"]["recommended_research_candidate"] == "D"
    assert payload["fullrun_executed"] is False
    assert payload["live_trading_enabled"] is False
    report = render_markdown(payload)
    assert "research-only virtual trading" in report
    assert "separately approved historical fullrun" in report


def test_review_fails_closed_on_stale_or_wrong_official_evidence() -> None:
    account = account_payload()
    account["official_metric_mode"] = "weight_level_proxy"
    payload = build_review(
        {
            "status": "blocked",
            "ready_for_policy_replay": False,
            "latest_observable_close_date": "2026-08-20",
        },
        {"status": "stale", "primary_weekly_eval_date": "2026-08-01"},
        account,
        cadence_payload(),
        catalog_payload(),
        sources={},
    )

    assert payload["status"] == "BLOCKED_EVIDENCE"
    assert "current_data_not_ready_for_policy_replay" in payload["blockers"]
    assert "weekly_mark_to_market_stale" in payload["blockers"]
    assert "weekly_mark_to_market_not_aligned_with_latest_observable_close" in payload["blockers"]
    assert "official_metric_mode_is_not_broker_ledger_next_close" in payload["blockers"]


if __name__ == "__main__":
    test_review_separates_evidence_blockers_from_research_review_items()
    test_review_fails_closed_on_stale_or_wrong_official_evidence()
    print("operating_model_review_smoke: PASS")
