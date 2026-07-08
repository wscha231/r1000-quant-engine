#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.collect_earnings_estimates_finnhub import compute_estimate_revision_features  # noqa: E402


def test_estimate_revision_features_compute_rising_revision_and_narrowing_dispersion() -> None:
    snapshots = pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "as_of_date": "2026-04-01",
                "available_from": "2026-04-01",
                "est_eps_fy1": 1.00,
                "est_eps_fy2": 1.20,
                "est_rev_fy1": 100.0,
                "est_dispersion": 0.40,
                "earnings_surprise_last": 2.0,
                "est_eps_revision_breadth": 0.20,
                "surprise_streak": 1,
            },
            {
                "ticker": "AAA",
                "as_of_date": "2026-06-01",
                "available_from": "2026-06-01",
                "est_eps_fy1": 1.10,
                "est_eps_fy2": 1.30,
                "est_rev_fy1": 110.0,
                "est_dispersion": 0.30,
                "earnings_surprise_last": 4.0,
                "est_eps_revision_breadth": 0.30,
                "surprise_streak": 2,
            },
            {
                "ticker": "AAA",
                "as_of_date": "2026-07-01",
                "available_from": "2026-07-01",
                "est_eps_fy1": 1.25,
                "est_eps_fy2": 1.45,
                "est_rev_fy1": 125.0,
                "est_dispersion": 0.20,
                "earnings_surprise_last": 5.0,
                "est_eps_revision_breadth": 0.50,
                "surprise_streak": 3,
            },
        ]
    )
    out, summary = compute_estimate_revision_features(snapshots, as_of_date="2026-07-01")
    assert summary["status"] == "completed", summary
    latest = out.sort_values("available_from").iloc[-1]
    assert latest["est_eps_revision_30d"] > 0
    assert latest["est_eps_revision_90d"] > 0
    assert latest["est_rev_revision_30d"] > 0
    assert latest["est_dispersion_change_30d"] <= 0
    assert latest["estimate_revision_confirmed"] == 1
    assert latest["estimate_revision_replacement_gate_pass"] == 1
    assert latest["estimate_revision_future_winner_multiplier"] > 1.0
    assert summary["available_from_is_fetch_date"] is True


if __name__ == "__main__":
    test_estimate_revision_features_compute_rising_revision_and_narrowing_dispersion()
    print("estimate_revision_features_smoke: PASS")
