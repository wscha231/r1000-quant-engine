#!/usr/bin/env python3
"""Smoke tests for SEC CIK and submissions schema handling."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_sec_submissions_collector import filings_from_submissions  # noqa: E402
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


def main() -> int:
    test_cik10_preserves_leading_zeroes()
    test_submissions_index_requires_pit_available_from()
    print("sec_cik_schema_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

