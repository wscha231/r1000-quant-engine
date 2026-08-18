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
        "accession_number": f"{str(cik).zfill(10)}-26-000001",
        "period_of_report": period_end,
        "accepted_at": accepted_at,
        "available_from": accepted_at,
        "form_type": form_type,
    }


def holding(cik: int, period_end: str, available_from: str, *, parse_error: bool = False) -> dict[str, str]:
    return {
        "manager_cik": str(cik).zfill(10),
        "report_period": period_end,
        "available_from": available_from,
        "source_accession": f"{str(cik).zfill(10)}-26-000001",
        "issuer_name": "PARSE_ERROR: fixture" if parse_error else "EXAMPLE INC",
        "cusip": "123456789",
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


def test_not_yet_available_filing_does_not_count_toward_coverage() -> None:
    schedule = load_schedule(ROOT / "research" / "sec_13f_filing_schedule.json")
    selected = manager_ciks_from_text("M1:1")
    future = pd.DataFrame([filing(1, "2026-06-30", "2026-08-14T20:00:00+00:00")])
    future["available_from"] = "2026-08-14T22:00:00+00:00"
    payload = evaluate_freshness(
        schedule=schedule,
        filings=future,
        selected_manager_ciks=selected,
        as_of=date(2026, 8, 18),
        as_of_at="2026-08-14T21:59:59+00:00",
    )
    assert payload["status"] == "blocked"
    assert "missing_due_period:2026-06-30" in payload["blockers"]


def test_due_period_parsed_holdings_coverage_is_required() -> None:
    schedule = load_schedule(ROOT / "research" / "sec_13f_filing_schedule.json")
    selected = manager_ciks_from_text(",".join(f"M{cik}:{cik}" for cik in range(1, 11)))
    accepted_at = "2026-08-14T20:00:00+00:00"
    current = pd.DataFrame([filing(cik, "2026-06-30", accepted_at) for cik in range(1, 9)])
    parsed = pd.DataFrame(
        [holding(cik, "2026-06-30", accepted_at, parse_error=(cik == 8)) for cik in range(1, 9)]
    )
    blocked = evaluate_freshness(
        schedule=schedule,
        filings=current,
        selected_manager_ciks=selected,
        as_of=date(2026, 8, 18),
        holdings=parsed,
        require_parsed_holdings=True,
    )
    assert blocked["required_period_parsed_manager_count"] == 7
    assert blocked["required_period_parse_error_manager_count"] == 1
    assert any(item.startswith("parsed_manager_coverage_below_threshold") for item in blocked["blockers"])
    parsed.loc[parsed["manager_cik"].eq("0000000008"), "issuer_name"] = "EXAMPLE INC"
    ready = evaluate_freshness(
        schedule=schedule,
        filings=current,
        selected_manager_ciks=selected,
        as_of=date(2026, 8, 18),
        holdings=parsed,
        require_parsed_holdings=True,
    )
    assert ready["freshness_ready"] is True
    assert ready["required_period_parsed_manager_coverage"] == 0.8


if __name__ == "__main__":
    test_official_schedule_contains_sec_2026_deadlines()
    test_due_quarter_missing_is_blocked()
    test_due_quarter_with_sufficient_manager_coverage_is_ready()
    test_empty_manager_universe_is_blocked()
    test_not_yet_available_filing_does_not_count_toward_coverage()
    test_due_period_parsed_holdings_coverage_is_required()
    print("sec_13f_filing_freshness_smoke: PASS")
