#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from r1000_config import PHASE18_ESTIMATE_REVISION_COLUMNS  # noqa: E402
from tools.collect_earnings_estimates_finnhub import (  # noqa: E402
    apply_estimate_revision_confirmation,
    collection_attempt_id,
)


def _scored() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"ticker": "AAA", "portfolio_future_winner_engine_score": 1.00},
            {"ticker": "BBB", "portfolio_future_winner_engine_score": 1.00},
        ]
    )


def _signals() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "available_from": "2026-07-08",
                "est_eps_fy1": 1.25,
                "est_eps_revision_breadth": 0.60,
                "est_dispersion_change_30d": -0.10,
                "estimate_revision_confirmed": 1,
                "estimate_revision_replacement_gate_pass": 1,
                "estimate_revision_future_winner_multiplier": 1.03,
                "has_forward_estimate": 1,
            },
            {
                "ticker": "BBB",
                "available_from": "2026-12-31",
                "est_eps_fy1": 2.00,
                "est_eps_revision_breadth": 1.00,
                "est_dispersion_change_30d": -0.50,
                "estimate_revision_confirmed": 1,
                "estimate_revision_replacement_gate_pass": 1,
                "estimate_revision_future_winner_multiplier": 1.05,
                "has_forward_estimate": 1,
            },
        ]
    )


def _valid_legacy_signal() -> pd.DataFrame:
    row = dict.fromkeys(PHASE18_ESTIMATE_REVISION_COLUMNS, 0.0)
    row.update(
        {
            "ticker": "AAA",
            "as_of_date": "2026-07-08",
            "available_from": "2026-07-08",
            "fetch_source": "finnhub",
            "eps_estimate_access": True,
            "revenue_estimate_access": True,
            "vendor_estimate_access": True,
            "has_forward_estimate": 1,
            "est_eps_fy1": 1.25,
            "est_eps_fy2": 1.40,
            "est_rev_fy1": 100.0,
            "n_analysts": 5,
            "est_dispersion": 0.10,
            "actual_eps_last": 1.0,
            "actual_report_date": "",
            "earnings_surprise_last": 0.0,
            "surprise_streak": 0,
            "recommendation_period": "",
            "recommendation_bull_count": 0,
            "recommendation_bear_count": 0,
            "est_eps_revision_breadth": 0.60,
            "est_dispersion_change_30d": -0.10,
            "estimate_revision_confirmed": 1,
            "estimate_revision_replacement_gate_pass": 1,
            "estimate_revision_future_winner_multiplier": 1.03,
        }
    )
    return pd.DataFrame([row])


def test_confirmation_default_off_changes_nothing() -> None:
    out, summary = apply_estimate_revision_confirmation(
        _scored(), _signals(), decision_date="2026-07-09", enabled=False
    )
    assert summary["enabled"] is False
    assert summary["selection_change_count"] == 0
    assert out["portfolio_future_winner_engine_score"].tolist() == [1.0, 1.0]
    assert out["estimate_revision_confirmed"].tolist() == [0, 0]
    assert out["estimate_revision_replacement_gate_pass"].tolist() == [0, 0]
    assert out["estimate_revision_future_winner_multiplier"].tolist() == [1.0, 1.0]


def test_legacy_date_only_signals_are_not_admitted() -> None:
    out, summary = apply_estimate_revision_confirmation(
        _scored(), _signals(), decision_date="2026-07-09", enabled=True
    )
    assert summary["enabled"] is True
    assert summary["selection_change_count"] == 0
    aaa = out[out["ticker"].eq("AAA")].iloc[0]
    bbb = out[out["ticker"].eq("BBB")].iloc[0]
    assert aaa["estimate_revision_replacement_gate_pass"] == 0
    assert aaa["portfolio_future_winner_engine_score"] == 1.0
    assert bbb["estimate_revision_replacement_gate_pass"] == 0
    assert bbb["portfolio_future_winner_engine_score"] == 1.0


def test_complete_legacy_signal_is_admitted_when_enabled() -> None:
    out, summary = apply_estimate_revision_confirmation(
        _scored(), _valid_legacy_signal(), decision_date="2026-07-09", enabled=True
    )
    assert summary["selection_change_count"] == 1
    aaa = out[out["ticker"].eq("AAA")].iloc[0]
    assert aaa["estimate_revision_confirmed"] == 1
    assert aaa["estimate_revision_replacement_gate_pass"] == 1
    assert aaa["estimate_revision_future_winner_multiplier"] > 1.0
    assert aaa["portfolio_future_winner_engine_score"] > 1.0


def test_empty_archive_is_neutral() -> None:
    out, summary = apply_estimate_revision_confirmation(
        _scored(), pd.DataFrame(), decision_date="2026-07-09", enabled=True
    )
    assert summary["selection_change_count"] == 0
    assert out["portfolio_future_winner_engine_score"].tolist() == [1.0, 1.0]


def test_missing_forward_estimate_signal_is_neutral() -> None:
    signals = _valid_legacy_signal()
    signals.loc[0, "has_forward_estimate"] = 0
    signals.loc[0, "est_eps_fy1"] = 0.0
    out, summary = apply_estimate_revision_confirmation(
        _scored(), signals, decision_date="2026-07-09", enabled=True
    )
    assert summary["selection_change_count"] == 0
    aaa = out[out["ticker"].eq("AAA")].iloc[0]
    assert aaa["estimate_revision_replacement_gate_pass"] == 0
    assert aaa["portfolio_future_winner_engine_score"] == 1.0


def test_collection_attempt_id_binds_logical_run() -> None:
    day = pd.Timestamp("2026-07-01")
    a = collection_attempt_id(day, ["AAA", "BBB"], logical_attempt_id="run-1")
    reordered = collection_attempt_id(day, ["bbb", "AAA", "AAA"], logical_attempt_id="run-1")
    other_run = collection_attempt_id(day, ["AAA", "BBB"], logical_attempt_id="run-2")
    other_day = collection_attempt_id(pd.Timestamp("2026-07-02"), ["AAA", "BBB"], logical_attempt_id="run-1")
    assert a == reordered
    assert a != other_run
    assert a != other_day


if __name__ == "__main__":
    test_confirmation_default_off_changes_nothing()
    test_legacy_date_only_signals_are_not_admitted()
    test_complete_legacy_signal_is_admitted_when_enabled()
    test_empty_archive_is_neutral()
    test_missing_forward_estimate_signal_is_neutral()
    test_collection_attempt_id_binds_logical_run()
    print("estimate_confirm_selection_smoke: PASS")
