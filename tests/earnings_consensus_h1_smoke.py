#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.earnings_consensus_h1 import (
    build_snapshot,
    causal_event_id,
    classify_attempt_state,
    frozen_pre_event_consensus,
    retry_priority,
    revision_features,
)


def test_missing_not_zero_and_recommendation_separate() -> None:
    row = build_snapshot(
        "AAA",
        eps_payload={"data": []},
        revenue_payload={"data": []},
        recommendation_payload=[{"period": "2026-09-01", "strongBuy": 2, "buy": 3, "hold": 4, "sell": 1, "strongSell": 0}],
        observed_at="2026-09-18T01:00:00Z",
        collected_at="2026-09-18T01:01:00Z",
        fetch_source="test",
    )
    assert row["eps_fy1_avg"] is None
    assert row["rev_fy1_avg"] is None
    assert row["has_forward_estimate"] == 0
    assert row["recommendation_balance"] == (5 - 1) / (5 + 1)
    assert row["est_eps_revision_breadth"] is None


def test_explicit_zero_preserved() -> None:
    row = build_snapshot(
        "ZERO",
        eps_payload={"data": [{"period": "2027-12-31", "avg": 0, "high": 0.1, "low": -0.1, "numberAnalysts": 3}]},
        revenue_payload={"data": []},
        recommendation_payload=[],
        observed_at="2026-09-18T01:00:00Z",
        collected_at="2026-09-18T01:01:00Z",
    )
    assert row["eps_fy1_avg"] == 0.0
    assert row["has_forward_estimate"] == 1


def test_revision_requires_same_period() -> None:
    a = build_snapshot("AAA", eps_payload={"data": [{"period": "2027-12-31", "avg": 10}]}, revenue_payload={"data": []}, recommendation_payload=[], observed_at="2026-08-01T12:00:00Z", collected_at="2026-08-01T12:01:00Z")
    b = build_snapshot("AAA", eps_payload={"data": [{"period": "2027-12-31", "avg": 11}]}, revenue_payload={"data": []}, recommendation_payload=[], observed_at="2026-09-01T12:00:00Z", collected_at="2026-09-01T12:01:00Z")
    c = build_snapshot("AAA", eps_payload={"data": [{"period": "2028-12-31", "avg": 12}]}, revenue_payload={"data": []}, recommendation_payload=[], observed_at="2027-01-02T12:00:00Z", collected_at="2027-01-02T12:01:00Z")
    assert abs(revision_features(b, a)["eps_revision_same_period"] - 0.1) < 1e-12
    assert revision_features(c, b)["eps_revision_same_period"] is None
    assert revision_features(c, b)["revision_status"] == "FISCAL_PERIOD_ROLLOVER_OR_MISSING"


def test_frozen_consensus_no_future() -> None:
    rows = []
    for dt, val in [("2026-08-01T20:00:00Z", 10), ("2026-09-10T20:00:00Z", 11), ("2026-09-18T20:00:00Z", 99)]:
        rows.append(build_snapshot("AAA", eps_payload={"data": [{"period": "2026-12-31", "avg": val}]}, revenue_payload={"data": []}, recommendation_payload=[], observed_at=dt, collected_at=dt))
    frozen = frozen_pre_event_consensus(rows, event_available_at="2026-09-15T20:00:00Z", fiscal_period_end="2026-12-31")
    assert frozen is not None and frozen["eps_fy1_avg"] == 11.0


def test_queue_state_separation() -> None:
    assert classify_attempt_state(has_success=False, success_age_days=None, selection_count=0, last_error_class=None) == "NEVER_ATTEMPTED"
    assert classify_attempt_state(has_success=False, success_age_days=None, selection_count=2, last_error_class="NO_COVERAGE") == "PROVIDER_NO_COVERAGE"
    assert classify_attempt_state(has_success=False, success_age_days=None, selection_count=2, last_error_class="TIMEOUT") == "TRANSIENT_FAILURE"
    assert classify_attempt_state(has_success=True, success_age_days=10, selection_count=2, last_error_class=None, stale_after_days=7) == "STALE_SUCCESS"
    assert retry_priority("NEVER_ATTEMPTED") < retry_priority("PROVIDER_NO_COVERAGE")
    assert retry_priority("STALE_SUCCESS", earnings_near=True) < retry_priority("STALE_SUCCESS")


def test_causal_id_stable() -> None:
    a = causal_event_id("aaa", "2026-12-31", "2027-01-31T21:00:00Z")
    b = causal_event_id("AAA", "2026-12-31", "2027-01-31T21:00:00+00:00")
    assert a == b and len(a) == 24


if __name__ == "__main__":
    tests = [value for key, value in list(globals().items()) if key.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"earnings_consensus_h1_smoke: PASS ({len(tests)} tests)")
