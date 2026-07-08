#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.collect_earnings_estimates_finnhub import apply_estimate_revision_confirmation  # noqa: E402


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
            },
        ]
    )


def test_confirmation_default_off_changes_nothing() -> None:
    out, summary = apply_estimate_revision_confirmation(_scored(), _signals(), decision_date="2026-07-09", enabled=False)
    assert summary["enabled"] is False
    assert summary["selection_change_count"] == 0
    assert out["portfolio_future_winner_engine_score"].tolist() == [1.0, 1.0]


def test_confirmation_uses_only_available_latest_signals() -> None:
    out, summary = apply_estimate_revision_confirmation(_scored(), _signals(), decision_date="2026-07-09", enabled=True)
    assert summary["enabled"] is True
    assert summary["selection_change_count"] == 1
    aaa = out[out["ticker"].eq("AAA")].iloc[0]
    bbb = out[out["ticker"].eq("BBB")].iloc[0]
    assert aaa["estimate_revision_replacement_gate_pass"] == 1
    assert aaa["portfolio_future_winner_engine_score"] > 1.0
    assert bbb["estimate_revision_replacement_gate_pass"] == 0
    assert bbb["portfolio_future_winner_engine_score"] == 1.0


def test_empty_archive_is_neutral() -> None:
    out, summary = apply_estimate_revision_confirmation(_scored(), pd.DataFrame(), decision_date="2026-07-09", enabled=True)
    assert summary["selection_change_count"] == 0
    assert out["portfolio_future_winner_engine_score"].tolist() == [1.0, 1.0]


if __name__ == "__main__":
    test_confirmation_default_off_changes_nothing()
    test_confirmation_uses_only_available_latest_signals()
    test_empty_archive_is_neutral()
    print("estimate_confirm_selection_smoke: PASS")
