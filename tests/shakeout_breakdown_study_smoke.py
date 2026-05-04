#!/usr/bin/env python3
"""Smoke test for shakeout/breakdown event labeling."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.run_shakeout_breakdown_study import (  # noqa: E402
    build_action_replay,
    detect_drawdown_events,
    summarize,
)


def make_history(kind: str) -> pd.DataFrame:
    dates = pd.bdate_range("2020-01-01", periods=820)
    close = np.empty(len(dates), dtype=float)
    close[:300] = np.linspace(40.0, 100.0, 300)
    if kind == "shakeout":
        close[300:320] = np.linspace(100.0, 78.0, 20)
        close[320:410] = np.linspace(78.0, 123.0, 90)
        close[410:620] = np.linspace(123.0, 180.0, 210)
        close[620:] = np.linspace(180.0, 170.0, len(dates) - 620)
    elif kind == "breakdown":
        close[300:320] = np.linspace(100.0, 75.0, 20)
        close[320:500] = np.linspace(75.0, 48.0, 180)
        close[500:] = np.linspace(48.0, 45.0, len(dates) - 500)
    elif kind == "distribution":
        close[300:318] = np.linspace(100.0, 83.0, 18)
        close[318:365] = np.linspace(83.0, 95.0, 47)
        close[365:450] = np.linspace(95.0, 76.0, 85)
        close[450:] = np.linspace(76.0, 72.0, len(dates) - 450)
    else:
        raise ValueError(kind)
    volume = np.full(len(dates), 1_000_000.0)
    volume[295:330] = 1_800_000.0
    return pd.DataFrame({"close": close, "volume": volume}, index=dates)


def make_spy() -> pd.DataFrame:
    dates = pd.bdate_range("2020-01-01", periods=820)
    close = np.linspace(100.0, 130.0, len(dates))
    volume = np.full(len(dates), 10_000_000.0)
    return pd.DataFrame({"close": close, "volume": volume}, index=dates)


def main() -> int:
    spy = make_spy()
    shake_events = detect_drawdown_events("SHAK", make_history("shakeout"), spy_hist=spy, min_drop=0.12)
    break_events = detect_drawdown_events("BRKN", make_history("breakdown"), spy_hist=spy, min_drop=0.12)
    dist_events = detect_drawdown_events("DIST", make_history("distribution"), spy_hist=spy, min_drop=0.12)
    assert shake_events, "expected synthetic shakeout event"
    assert break_events, "expected synthetic breakdown event"
    assert dist_events, "expected synthetic distribution event"
    assert any(e.label in {"SHAKEOUT", "BUYABLE_RESET"} for e in shake_events), [e.label for e in shake_events]
    assert any(e.label in {"TRUE_BREAKDOWN", "DEAD_THEME"} for e in break_events), [e.label for e in break_events]
    assert any(e.label == "DISTRIBUTION" for e in dist_events), [e.label for e in dist_events]

    df = pd.DataFrame([e.__dict__ for e in [shake_events[0], break_events[0], dist_events[0]]])
    action = build_action_replay(df)
    summary = summarize(df, action, type("Args", (), {
        "min_drop": 0.12,
        "lookback_days": 126,
        "min_gap_days": 42,
        "min_current_mcap_usd": 5_000_000_000,
        "min_dollar_vol_20d": 20_000_000,
    })())
    assert summary["production_activation_allowed"] is False
    assert summary["event_count"] == 3
    assert "DISTRIBUTION" in summary["label_counts"]
    assert not action.empty
    assert set(action["action"]) >= {"hold", "trim50", "add25", "exit_to_cash"}
    print("shakeout_breakdown_study_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
