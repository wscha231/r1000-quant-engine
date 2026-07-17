#!/usr/bin/env python3
"""Synthetic checks for semiconductor factor/residual diagnostics."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.analyze_run287_semiconductor_damage as semi  # noqa: E402


def test_factor_state_is_past_only_and_residual_alert_is_separate() -> None:
    dates = pd.bdate_range("2022-01-03", periods=900)
    spy = pd.Series(np.linspace(100.0, 150.0, len(dates)), index=dates)
    soxx = pd.Series(np.linspace(100.0, 200.0, len(dates)), index=dates)
    wdc = soxx.copy()
    # A final factor loss and an additional held-name residual loss.
    soxx.iloc[-1] = soxx.iloc[-2] * 0.95
    wdc.iloc[-1] = wdc.iloc[-2] * 0.85
    prices = pd.DataFrame({"SPY": spy, "SOXX": soxx, "WDC": wdc})
    state = semi.build_factor_state(prices)
    assert np.isfinite(state.iloc[-1]["tail_threshold"])
    expected = soxx.pct_change().iloc[:-1].tail(semi.LOOKBACK).quantile(semi.TAIL_QUANTILE)
    assert np.isclose(state.iloc[-1]["tail_threshold"], expected)
    residuals = semi.current_residuals(prices, dates[-1])
    row = residuals.set_index("ticker").loc["WDC"]
    assert bool(row["sector_residual_alert"])
    assert row["advisory_action"] == "FREEZE_INCREMENTAL_BUY_AND_MANUAL_REVIEW"
