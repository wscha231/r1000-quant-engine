#!/usr/bin/env python3
"""Smoke test for the report-only winner onset study."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.run_winner_onset_study import (
    build_hold_diagnostics,
    build_phase_snapshots,
    detect_onset_events,
    load_tickers_from_scored,
    render_policy_yaml,
    summarize_patterns,
)


def synthetic_history() -> pd.DataFrame:
    dates = pd.bdate_range("2020-01-01", periods=1000)
    close = np.empty(len(dates), dtype=float)
    close[:430] = np.linspace(10.0, 11.0, 430)
    close[430:500] = np.linspace(11.0, 14.0, 70)
    close[500:620] = np.linspace(14.0, 33.0, 120)
    close[620:740] = np.linspace(33.0, 48.0, 120)
    close[740:] = np.linspace(48.0, 42.0, len(dates) - 740)
    volume = np.full(len(dates), 1_000_000.0)
    volume[420:620] = 1_350_000.0
    return pd.DataFrame({"close": close, "volume": volume}, index=dates)


def synthetic_spy() -> pd.DataFrame:
    dates = pd.bdate_range("2020-01-01", periods=1000)
    close = np.linspace(100.0, 125.0, len(dates))
    volume = np.full(len(dates), 10_000_000.0)
    return pd.DataFrame({"close": close, "volume": volume}, index=dates)


def main() -> int:
    hist = synthetic_history()
    spy = synthetic_spy()
    events = detect_onset_events(
        "TEST",
        hist,
        spy_hist=spy,
        min_peak_return_12m=1.25,
        min_forward_6m=0.45,
        readiness_min=0.45,
    )
    assert events, "expected at least one onset event"
    event = events[0]
    assert event.ticker == "TEST"
    assert event.peak_return_12m >= 1.25
    assert event.peak_multiple_12m >= 2.25
    assert event.winner_tier in {"major_winner", "major_2_5x", "super_5x", "monster_10x", "extreme_30x"}
    assert event.forward_6m_return >= 0.45
    assert 0.0 <= event.entry_readiness_score <= 1.0

    histories = {"TEST": hist}
    snapshots = build_phase_snapshots(events, histories, spy_hist=spy)
    holds = build_hold_diagnostics(events, histories)
    assert not snapshots.empty
    assert set([-3, -1, 0, 1, 3]).issubset(set(snapshots["offset_months"].astype(int)))
    assert not holds.empty
    assert float(holds.iloc[0]["max_return_12m"]) >= 1.25

    events_df = pd.DataFrame([event.__dict__ for event in events])
    summary = summarize_patterns(events_df, snapshots, holds)
    assert summary["event_count"] >= 1
    assert summary["winner_tier_counts"]
    assert summary["production_activation_allowed"] is False
    policy = render_policy_yaml(summary)
    assert "production_activation_allowed: false" in policy
    assert "winner_onset_hold_candidate" in policy
    assert "monster_winner_archive_candidate" in policy

    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        scored = out / "scored.csv"
        pd.DataFrame([
            {"ticker": "TEST", "score": 1.0, "market_cap_live": 12_000_000_000, "dollar_vol_20d": 50_000_000},
            {"ticker": "MICRO", "score": 2.0, "market_cap_live": 100_000_000, "dollar_vol_20d": 50_000_000},
            {"ticker": "ILLIQ", "score": 3.0, "market_cap_live": 12_000_000_000, "dollar_vol_20d": 1_000_000},
        ]).to_csv(scored, index=False)
        assert load_tickers_from_scored(scored, min_current_mcap_usd=5_000_000_000) == ["TEST"]
        events_df.to_csv(out / "events.csv", index=False)
        snapshots.to_csv(out / "phase_snapshots.csv", index=False)
        holds.to_csv(out / "hold_diagnostics.csv", index=False)
        (out / "pattern_summary.json").write_text(json.dumps(summary), encoding="utf-8")

    print("winner_onset_study_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
