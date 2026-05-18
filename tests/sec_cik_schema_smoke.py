#!/usr/bin/env python3
"""Smoke tests for SEC CIK and submissions schema handling."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_sec_submissions_collector import archive_file_overlaps, filings_from_archive_payload, filings_from_submissions  # noqa: E402
from tools.sec_edgar_common import available_from, normalize_cik10  # noqa: E402


def test_cik10_preserves_leading_zeroes() -> None:
    assert normalize_cik10(320193) == "0000320193"
    assert normalize_cik10("0000320193") == "0000320193"
    assert normalize_cik10("320193.0") == "0000320193"


def test_submissions_index_requires_pit_available_from() -> None:
    payload = {
        "filings": {
            "recent": {
                "form": ["4", "10-Q"],
                "accessionNumber": ["0000320193-26-000001", "0000320193-26-000002"],
                "acceptanceDateTime": ["2026-05-15T22:30:00.000Z", "2026-05-14T12:00:00.000Z"],
                "filingDate": ["2026-05-15", "2026-05-14"],
                "reportDate": ["2026-05-13", "2026-03-31"],
                "primaryDocument": ["xslF345X05/form4.xml", "aapl-20260331.htm"],
            }
        }
    }
    frame = filings_from_submissions(
        ticker="AAPL",
        cik10="320193",
        payload=payload,
        forms={"4"},
        safety_delay_hours=12.0,
        max_filings_per_ticker=10,
    )
    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["cik10"] == "0000320193"
    assert row["form_type"] == "4"
    assert str(row["available_from"]).startswith("2026-05-16T10:30:00")
    assert "Archives/edgar/data/320193" in row["filing_url"]
    assert pd.notna(available_from(row["accepted_at"]))


def test_archive_backfill_respects_date_range_and_source() -> None:
    start = pd.Timestamp("2018-05-18", tz="UTC")
    end = pd.Timestamp("2026-05-18", tz="UTC")
    assert archive_file_overlaps({"filingFrom": "2019-01-01", "filingTo": "2019-12-31"}, start, end)
    assert not archive_file_overlaps({"filingFrom": "2010-01-01", "filingTo": "2010-12-31"}, start, end)
    payload = {
        "form": ["4", "4", "8-K"],
        "accessionNumber": ["0000320193-18-000001", "0000320193-16-000001", "0000320193-20-000001"],
        "acceptanceDateTime": ["2018-06-01T22:30:00.000Z", "2016-06-01T22:30:00.000Z", "2020-01-01T00:00:00.000Z"],
        "filingDate": ["2018-06-01", "2016-06-01", "2020-01-01"],
        "reportDate": ["2018-05-30", "2016-05-30", "2019-12-31"],
        "primaryDocument": ["form4-2018.xml", "form4-2016.xml", "event.htm"],
    }
    frame = filings_from_archive_payload(
        ticker="AAPL",
        cik10="320193",
        payload=payload,
        forms={"4"},
        safety_delay_hours=12.0,
        source="sec_submissions_file:CIK0000320193-submissions-001.json",
        start_date=start,
        end_date=end,
    )
    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["accession_number"] == "0000320193-18-000001"
    assert row["source"].startswith("sec_submissions_file:")


def main() -> int:
    test_cik10_preserves_leading_zeroes()
    test_submissions_index_requires_pit_available_from()
    test_archive_backfill_respects_date_range_and_source()
    print("sec_cik_schema_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
