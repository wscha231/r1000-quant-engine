#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.collect_earnings_estimates_h1 import (  # noqa: E402
    compute_estimate_revision_features,
    parse_snapshot_row,
)


def test_parse_missing_remains_null_and_recommendation_is_separate() -> None:
    row = parse_snapshot_row(
        "AAA",
        fetch_date=pd.Timestamp("2026-09-18T01:00:00Z"),
        eps_payload={"data": []},
        revenue_payload={"data": []},
        earnings_payload=[],
        recommendation_payload=[{"period": "2026-09-01", "strongBuy": 2, "buy": 3, "hold": 4, "sell": 1, "strongSell": 0}],
    )
    assert row["est_eps_fy1"] is None
    assert row["est_rev_fy1"] is None
    assert row["actual_eps_last"] is None
    assert row["recommendation_balance"] == (5 - 1) / (5 + 1)
    assert row["est_eps_revision_breadth"] is None
    assert "T" in row["available_from"]


def test_same_period_revision_and_rollover_block() -> None:
    rows = []
    for observed, period, avg in [
        ("2026-04-01T20:00:00Z", "2027-12-31", 10.0),
        ("2026-06-01T20:00:00Z", "2027-12-31", 11.0),
        ("2026-07-01T20:00:00Z", "2027-12-31", 12.0),
        ("2027-01-02T20:00:00Z", "2028-12-31", 13.0),
    ]:
        rows.append(
            parse_snapshot_row(
                "AAA",
                fetch_date=pd.Timestamp(observed),
                eps_payload={"data": [{"period": period, "avg": avg, "high": avg * 1.1, "low": avg * 0.9}]},
                revenue_payload={"data": [{"period": period, "avg": avg * 100}]},
                earnings_payload=[],
                recommendation_payload=[],
            )
        )
    out, summary = compute_estimate_revision_features(pd.DataFrame(rows))
    assert summary["status"] == "completed"
    july = out[out["as_of_date"].dt.month == 7].iloc[0]
    assert july["est_eps_revision_30d"] > 0
    assert july["est_eps_revision_90d"] > 0
    assert july["est_rev_revision_30d"] > 0
    january = out[out["as_of_date"].dt.year == 2027].iloc[0]
    assert pd.isna(january["est_eps_revision_30d"])
    assert pd.isna(january["est_eps_revision_90d"])
    assert january["revision_period_status"] == "NO_SAME_PERIOD_LOOKBACK"


def test_missing_history_does_not_confirm() -> None:
    row = parse_snapshot_row(
        "BBB",
        fetch_date=pd.Timestamp("2026-09-18T01:00:00Z"),
        eps_payload={"data": [{"period": "2027-12-31", "avg": 0.0, "high": 0.1, "low": -0.1}]},
        revenue_payload={"data": []},
        earnings_payload=[],
        recommendation_payload=[],
    )
    out, _ = compute_estimate_revision_features(pd.DataFrame([row]))
    latest = out.iloc[0]
    assert latest["est_eps_fy1"] == 0.0
    assert pd.isna(latest["est_eps_revision_30d"])
    assert latest["estimate_revision_confirmed"] == 0
    assert latest["estimate_revision_future_winner_multiplier"] == 1.0


if __name__ == "__main__":
    test_parse_missing_remains_null_and_recommendation_is_separate()
    test_same_period_revision_and_rollover_block()
    test_missing_history_does_not_confirm()
    print("collect_earnings_estimates_h1_smoke: PASS (3 tests)")
