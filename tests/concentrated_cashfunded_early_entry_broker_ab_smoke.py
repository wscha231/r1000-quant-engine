"""Smoke tests for Concentrated cash-funded early-entry harness."""

from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_concentrated_cashfunded_early_entry_broker_ab import (  # noqa: E402
    make_cashfunded_book,
    normalize_candidate_book,
    normalize_target_book,
    validate_signal_names,
    verdict_for_arm,
)


def test_cashfunded_entry_uses_cash_and_preserves_existing_stocks() -> None:
    target = normalize_target_book(
        pd.DataFrame(
            [
                {"rebalance_date": "2020-01-31", "ticker": "AAA", "weight": 0.30, "target_weight": 0.30},
                {"rebalance_date": "2020-01-31", "ticker": "BBB", "weight": 0.20, "target_weight": 0.20},
                {"rebalance_date": "2020-01-31", "ticker": "CASH", "weight": 0.50, "target_weight": 0.50},
            ]
        )
    )
    candidates = normalize_candidate_book(
        pd.DataFrame(
            [
                {"rebalance_date": "2020-01-31", "ticker": "AAA", "future_winner_scout_score": 9.0},
                {"rebalance_date": "2020-01-31", "ticker": "CCC", "future_winner_scout_score": 7.0},
                {"rebalance_date": "2020-01-31", "ticker": "DDD", "future_winner_scout_score": 5.0},
            ]
        ),
        ["future_winner_scout_score"],
    )

    book, events = make_cashfunded_book(
        target_book=target,
        candidates=candidates,
        signal="future_winner_scout_score",
        add_weight=0.07,
    )

    weights = {row["ticker"]: float(row["weight"]) for _, row in book.iterrows()}
    assert weights["AAA"] == 0.30
    assert weights["BBB"] == 0.20
    assert weights["CCC"] == 0.07
    assert weights["CASH"] == 0.43
    assert "DDD" not in weights
    assert len(events) == 1
    assert events.iloc[0]["ticker"] == "CCC"


def test_cashfunded_entry_is_capped_by_available_cash() -> None:
    target = normalize_target_book(
        pd.DataFrame(
            [
                {"rebalance_date": "2020-01-31", "ticker": "AAA", "weight": 0.98, "target_weight": 0.98},
                {"rebalance_date": "2020-01-31", "ticker": "CASH", "weight": 0.02, "target_weight": 0.02},
            ]
        )
    )
    candidates = normalize_candidate_book(
        pd.DataFrame(
            [
                {"rebalance_date": "2020-01-31", "ticker": "CCC", "future_winner_scout_score": 7.0},
            ]
        ),
        ["future_winner_scout_score"],
    )

    book, events = make_cashfunded_book(
        target_book=target,
        candidates=candidates,
        signal="future_winner_scout_score",
        add_weight=0.07,
    )

    weights = {row["ticker"]: float(row["weight"]) for _, row in book.iterrows()}
    assert weights["CCC"] == 0.02
    assert "CASH" not in weights
    assert float(events.iloc[0]["added_weight"]) == 0.02


def test_verdict_requires_cagr_and_mdd_targets() -> None:
    assert (
        verdict_for_arm(
            {"metric_mode": "broker_ledger_next_close", "years": 7.1, "cagr": 0.51, "max_dd": -0.24},
            target_cagr=0.50,
            target_mdd=-0.25,
        )
        == "research_pass_concentrated_candidate"
    )
    assert (
        verdict_for_arm(
            {"metric_mode": "broker_ledger_next_close", "years": 7.1, "cagr": 0.51, "max_dd": -0.26},
            target_cagr=0.50,
            target_mdd=-0.25,
        )
        == "reject_mdd_worse"
    )


def test_forward_return_labels_are_not_allowed_as_signals() -> None:
    validate_signal_names(["future_winner_scout_score", "breakout_setup_quality_score"])
    try:
        validate_signal_names(["period_forward_return"])
    except ValueError as exc:
        assert "forward-return" in str(exc)
    else:
        raise AssertionError("period_forward_return must be rejected as a selection signal")


if __name__ == "__main__":
    test_cashfunded_entry_uses_cash_and_preserves_existing_stocks()
    test_cashfunded_entry_is_capped_by_available_cash()
    test_verdict_requires_cagr_and_mdd_targets()
    test_forward_return_labels_are_not_allowed_as_signals()
    print("concentrated_cashfunded_early_entry_broker_ab_smoke: PASS")
