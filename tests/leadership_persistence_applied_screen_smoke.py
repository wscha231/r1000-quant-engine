#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_leadership_persistence_applied_screen import (  # noqa: E402
    replacement_delta_payload,
    sanitize_policy_record,
    screen_portfolio,
)


def _candidate_row(ticker: str, *, market_score: float, leader: bool) -> dict[str, object]:
    rs = 0.25 if leader else -0.05
    return {
        "rebalance_date": "2021-06-30",
        "ticker": ticker,
        "sector": "Technology",
        "industry_group": "Semiconductors",
        "market_leader_lane_score": market_score,
        "quality_compounder_lane_score": 0.0,
        "emerging_tenbagger_lane_score": 0.0,
        "top7_manager_discovery_lane_score": 0.0,
        "cyclical_recovery_lane_score": 0.0,
        "crisis_beneficiary_lane_score": 0.0,
        "rs_spy_1w": 0.01,
        "rs_qqq_1w": 0.01,
        "rs_spy_1m": 0.02,
        "rs_qqq_1m": 0.02,
        "rs_spy_3m": rs,
        "rs_qqq_3m": rs,
        "rs_spy_6m": rs,
        "rs_qqq_6m": rs,
        "rs_benchmark_1w": 0.01,
        "rs_benchmark_3m": rs,
        "rs_benchmark_6m": rs,
        "rs_semis_3m": rs,
        "industry_group_strength_score": 1.0 if leader else -1.0,
        "oneil_leadership_score": 1.0 if leader else -1.0,
        "sec_13f_smart_money_score": 0.5 if leader else 0.0,
        "sec_form4_cluster_buy_score": 0.5 if leader else 0.0,
        "etf_holdings_score_shadow": 0.5 if leader else 0.0,
        "price_above_ma200": 1.0,
        "price_above_ma50": 1.0,
        "negative_fcf_risk_cap": 1.0,
        "dollar_vol_20d": 1_000_000_000.0,
        "market_cap_live": 10_000_000_000.0,
    }


def test_replacement_delta_identifies_marginal_block() -> None:
    payload = replacement_delta_payload(
        portfolio="concentrated",
        rebalance_date=pd.Timestamp("2021-06-30"),
        candidate={"ticker": "NEW", "alphaops_vnext_score": 1.20},
        weakest={
            "ticker": "KEEP",
            "alphaops_vnext_score": 1.00,
            "leader_tier": "DUAL_LEADER",
            "prior_weight": 0.2,
            "rs_benchmark_3m": 0.1,
            "rs_benchmark_6m": 0.2,
        },
        threshold_normal=0.15,
        required_gap=0.25,
        gap_reason="healthy_prior_leader",
    )
    assert payload["would_pass_standard"] is True
    assert payload["passes_persistence_gap"] is False
    assert payload["behavior_delta"] is True


def test_sanitize_policy_record_preserves_csv_false_semantics() -> None:
    row = sanitize_policy_record(
        {
            "ticker": " abc ",
            "top7_standalone_blocked": "False",
            "emerging_tenbagger_hard_reject_reason": float("nan"),
        }
    )
    assert row["ticker"] == "ABC"
    assert row["top7_standalone_blocked"] is False
    assert row["emerging_tenbagger_hard_reject_reason"] == ""


def test_screen_blocks_missing_books_without_false_positive() -> None:
    rows, summary = screen_portfolio(
        pd.DataFrame(),
        pd.DataFrame(),
        pd.DataFrame(),
        portfolio="concentrated",
        target_n=1,
    )
    assert rows == []
    assert summary["status"] == "blocked"
    assert summary["next_action"] == "fix_screen_fidelity_before_ab"


def test_screen_counts_applied_replacement_tests() -> None:
    candidates = pd.DataFrame(
        [
            _candidate_row("KEEP", market_score=1.0, leader=True),
            _candidate_row("NEW", market_score=2.0, leader=True),
            _candidate_row("MISS", market_score=0.0, leader=False),
        ]
    )
    target_book = pd.DataFrame(
        [
            {"rebalance_date": "2021-05-31", "ticker": "KEEP", "weight": 1.0},
            {"rebalance_date": "2021-06-30", "ticker": "NEW", "weight": 1.0},
        ]
    )
    target_book["rebalance_date"] = pd.to_datetime(target_book["rebalance_date"]).dt.normalize()

    rows, summary = screen_portfolio(
        candidates,
        target_book,
        pd.DataFrame(),
        portfolio="concentrated",
        target_n=1,
    )

    assert summary["on_summary"]["protected_prior_rows"] >= 1
    assert summary["on_summary"]["applied_to_replacement_tests"] >= 1
    assert rows
    assert rows[0]["gap_reason"] == "healthy_prior_leader"


if __name__ == "__main__":
    test_replacement_delta_identifies_marginal_block()
    test_sanitize_policy_record_preserves_csv_false_semantics()
    test_screen_blocks_missing_books_without_false_positive()
    test_screen_counts_applied_replacement_tests()
    print("leadership_persistence_applied_screen_smoke passed")
