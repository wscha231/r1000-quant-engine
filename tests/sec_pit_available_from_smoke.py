#!/usr/bin/env python3
"""Smoke checks for SEC event point-in-time availability."""
from __future__ import annotations

import pandas as pd


def sec_available_from_violations(
    events: pd.DataFrame,
    *,
    rebalance_col: str = "rebalance_date",
    available_from_col: str = "available_from",
    source_col: str = "feature_source",
    sec_source_value: str = "sec",
) -> pd.DataFrame:
    required = {rebalance_col, available_from_col}
    missing = required - set(events.columns)
    assert not missing, f"missing required PIT columns: {sorted(missing)}"

    checked = events.copy()
    if source_col in checked.columns:
        source = checked[source_col].fillna("").astype(str).str.lower()
        checked = checked[source == sec_source_value.lower()].copy()

    available = pd.to_datetime(checked[available_from_col], errors="coerce").dt.normalize()
    rebalance = pd.to_datetime(checked[rebalance_col], errors="coerce").dt.normalize()
    violation_mask = available.isna() | rebalance.isna() | (available > rebalance)
    violations = checked.loc[violation_mask].copy()

    reasons = []
    for idx in violations.index:
        if pd.isna(available.loc[idx]) or pd.isna(rebalance.loc[idx]):
            reasons.append("missing_or_invalid_date")
        else:
            reasons.append("available_from_after_rebalance_date")
    violations["pit_violation_reason"] = reasons
    return violations


def assert_sec_events_are_point_in_time(events: pd.DataFrame) -> None:
    violations = sec_available_from_violations(events)
    assert violations.empty, violations[
        ["ticker", "available_from", "rebalance_date", "pit_violation_reason"]
    ].to_dict("records")


def test_sec_events_pass_when_available_from_is_on_or_before_rebalance() -> None:
    events = pd.DataFrame(
        [
            {
                "ticker": "AAPL",
                "feature_source": "sec",
                "form": "10-Q",
                "event_date": "2024-05-02",
                "available_from": "2024-05-03",
                "rebalance_date": "2024-05-31",
            },
            {
                "ticker": "MSFT",
                "feature_source": "sec",
                "form": "8-K",
                "event_date": "2024-06-14",
                "available_from": "2024-06-28",
                "rebalance_date": "2024-06-28",
            },
            {
                "ticker": "MACRO",
                "feature_source": "macro",
                "available_from": "2024-07-15",
                "rebalance_date": "2024-06-28",
            },
        ]
    )

    assert sec_available_from_violations(events).empty
    assert_sec_events_are_point_in_time(events)


def test_sec_events_flag_lookahead_available_from_dates() -> None:
    events = pd.DataFrame(
        [
            {
                "ticker": "AAPL",
                "feature_source": "sec",
                "form": "10-Q",
                "event_date": "2024-05-02",
                "available_from": "2024-06-03",
                "rebalance_date": "2024-05-31",
            },
            {
                "ticker": "MSFT",
                "feature_source": "sec",
                "form": "8-K",
                "event_date": "2024-06-14",
                "available_from": None,
                "rebalance_date": "2024-06-28",
            },
            {
                "ticker": "NVDA",
                "feature_source": "sec",
                "form": "10-Q",
                "event_date": "2024-06-10",
                "available_from": "2024-06-10",
                "rebalance_date": "2024-06-28",
            },
        ]
    )

    violations = sec_available_from_violations(events)
    assert set(violations["ticker"]) == {"AAPL", "MSFT"}
    assert violations.set_index("ticker").loc["AAPL", "pit_violation_reason"] == "available_from_after_rebalance_date"
    assert violations.set_index("ticker").loc["MSFT", "pit_violation_reason"] == "missing_or_invalid_date"

    try:
        assert_sec_events_are_point_in_time(events)
    except AssertionError as exc:
        assert "AAPL" in str(exc)
        assert "MSFT" in str(exc)
    else:
        raise AssertionError("PIT assertion did not fail for invalid SEC availability rows")


if __name__ == "__main__":
    test_sec_events_pass_when_available_from_is_on_or_before_rebalance()
    test_sec_events_flag_lookahead_available_from_dates()
    print("sec_pit_available_from_smoke: PASS")
