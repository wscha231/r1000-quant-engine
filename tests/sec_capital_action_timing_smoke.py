#!/usr/bin/env python3
"""Focused timing decomposition checks."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.analyze_sec_capital_action_timing as timing  # noqa: E402


def test_pre_reaction_post_are_separate_and_not_promotable() -> None:
    dates = pd.bdate_range("2023-01-03", "2025-12-31")
    stock = np.linspace(100.0, 300.0, len(dates))
    spy = np.linspace(100.0, 150.0, len(dates))
    prices = pd.concat(
        [
            pd.DataFrame({"ticker": "TEST", "date": dates, "adjusted_close": stock, "raw_close": stock}),
            pd.DataFrame({"ticker": "SPY", "date": dates, "adjusted_close": spy, "raw_close": spy}),
        ],
        ignore_index=True,
    )
    events = pd.DataFrame(
        [
            {
                "ticker": "TEST",
                "accepted_at": "2024-07-01T19:00:00Z",
                "available_from": "2024-07-01T19:00:00Z",
                "sec_capital_allocation_event": "positive",
            }
        ]
    )
    rows = timing.build_timing_rows(events, prices)
    row = rows.iloc[0]
    assert row["anchor_date"] == "2024-06-28"
    assert row["entry_date"] == "2024-07-01"
    assert np.isfinite(row["pre_21d_spy_excess"])
    assert np.isfinite(row["reaction_spy_excess"])
    assert np.isfinite(row["post_63d_spy_excess"])
    summary = timing.summarize(rows)
    assert summary["status"] == "DESCRIPTIVE_ONLY"
    assert summary["first_disclosure_clean"] is False
    assert summary["portfolio_signal_authorized"] is False
