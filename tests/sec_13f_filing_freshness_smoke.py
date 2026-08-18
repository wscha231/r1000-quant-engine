#!/usr/bin/env python3
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.audit_sec_13f_filing_freshness import (  # noqa: E402
    evaluate_freshness,
    load_schedule,
    manager_ciks_from_text,
)


def filing(cik: int, period_end: str, accepted_at: str, form_type: str = "13F-HR") -> dict[str, str]:
    return {
        "cik10": str(cik).zfill(10),
        "period_of_report": period_end,
        "accepted_at": accepted_at,
        "available_from": accepted_at,
        "form_type": form_type,
    }


def test_official_schedule_contains_sec_2026_deadlines() -> None:
    schedule = load_schedule(ROOT / "research" / "sec_13f_filing_schedule.json")
    deadlines = {item["period_end"]: item["filing_deadline"] for item in schedule["deadlines"]}
    assert deadlines["2026-03-31"] == "2026-05-15"
    assert deadlines["2026-06-30"] == "2026-08-14"
    assert deadlines["2026-09-30"] == "2026-11-16"
    assert schedule["source"]["url"].startswith("https://www.sec.gov/")


def test_due_quarter_missing_is_blocked() -> None:
    schedule = load_schedule(ROOT / "research" / "sec_13f_filing_schedule.json")
    selected = manager_ciks_from_text(",".join(f"M{cik}:{cik}" for cik in range(1, 11)))
    stale = pd.DataFrame(
        [filing(cik, "2026-03-31", f"2026-05-15T20:{cik:02d}:00+00:00") for cik in range(1, 11)]
    )
    payload = evaluate_freshness(
        schedule=schedule,
        filings=stale,
        selected_manager_ciks=selected,
        as_of=date(2026, 8, 18),
    )
    assert payload["status"] == "blocked"
    assert payload["required_due_period_end"] == "2026-06-30"
    assert payload["required_due_deadline"] == "2026-08-14"
    assert "missing_due_period:2026-06-30" in payload["blockers"]


def test_due_quarter_with_sufficient_manager_coverage_is_ready() -> None:
    schedule = load_schedule(ROOT / "research" / "sec_13f_filing_schedule.json")
    selected = manager_ciks_from_text(",".join(f"M{cik}:{cik}" for cik in range(1, 11)))
    current = pd.DataFrame(
        [filing(cik, "2026-06-30", f"2026-08-14T20:{cik:02d}:00+00:00") for cik in range(1, 9)]
        + [filing(1, "2026-06-30", "2026-08-17T14:00:00+00:00", "13F-HR/A")]
    )
    payload = evaluate_freshness(
        schedule=schedule,
        filings=current,
        selected_manager_ciks=selected,
        as_of=date(2026, 8, 18),
    )
    assert payload["status"] == "ready"
    assert payload["freshness_ready"] is True
    assert payload["required_period_manager_count"] == 8
    assert payload["selected_manager_coverage"] == 0.8
    assert payload["monitored_period_amendment_rows"] == 1
    assert payload["newest_period_of_report"] == "2026-06-30"
    assert payload["next_scheduled_period_end"] == "2026-09-30"
    assert payload["next_scheduled_deadline"] == "2026-11-16"


def test_empty_manager_universe_is_blocked() -> None:
    schedule = load_schedule(ROOT / "research" / "sec_13f_filing_schedule.json")
    current = pd.DataFrame(
        [filing(1, "2026-06-30", "2026-08-14T20:00:00+00:00")]
    )
    payload = evaluate_freshness(
        schedule=schedule,
        filings=current,
        selected_manager_ciks=set(),
        as_of=date(2026, 8, 18),
    )
    assert payload["status"] == "blocked"
    assert "selected_manager_universe_empty" in payload["blockers"]


if __name__ == "__main__":
    test_official_schedule_contains_sec_2026_deadlines()
    test_due_quarter_missing_is_blocked()
    test_due_quarter_with_sufficient_manager_coverage_is_ready()
    test_empty_manager_universe_is_blocked()
    print("sec_13f_filing_freshness_smoke: PASS")
