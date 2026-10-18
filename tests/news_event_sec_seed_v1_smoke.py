#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.build_news_event_sec_seed_v1 import (  # noqa: E402
    build_events,
    normalize_eligibility,
)
from tools.run_sec_submissions_collector import filings_from_submissions  # noqa: E402
from research.news_event_alpha_v1.runtime import normalize_events  # noqa: E402


def test_collector_preserves_sec_items():
    payload = {
        "filings": {
            "recent": {
                "form": ["8-K"],
                "accessionNumber": ["0000000001-25-000001"],
                "primaryDocument": ["x.htm"],
                "acceptanceDateTime": ["2025-03-10T20:15:00Z"],
                "filingDate": ["2025-03-10"],
                "reportDate": ["2025-03-10"],
                "items": ["1.01,9.01"],
            }
        }
    }
    frame = filings_from_submissions(
        "ABC",
        "1",
        payload,
        forms=["8-K"],
        history_start="2025-01-01",
        history_end="2025-12-31",
    )
    assert len(frame) == 1
    assert frame.iloc[0]["items"] == "1.01,9.01"


def test_sec_seed_is_official_but_does_not_invent_amount_or_theme_breadth():
    filings = pd.DataFrame(
        [
            {
                "ticker": "ABC",
                "cik10": "0000000001",
                "accession_number": "0000000001-25-000001",
                "form_type": "8-K",
                "available_from": "2025-03-10T20:15:00+00:00",
                "accepted_at": "2025-03-10T20:15:00+00:00",
                "items": "1.01,9.01",
                "filing_url": "https://www.sec.gov/example",
            },
            {
                "ticker": "ABC",
                "cik10": "0000000001",
                "accession_number": "0000000001-25-000002",
                "form_type": "8-K",
                "available_from": "2025-04-10T20:15:00+00:00",
                "accepted_at": "2025-04-10T20:15:00+00:00",
                "items": "8.01,9.01",
                "filing_url": "https://www.sec.gov/example2",
            },
            {
                "ticker": "KRX",
                "cik10": "0000000002",
                "accession_number": "0000000002-25-000001",
                "form_type": "8-K",
                "available_from": "2025-03-11T20:15:00+00:00",
                "accepted_at": "2025-03-11T20:15:00+00:00",
                "items": "1.01",
                "filing_url": "",
            },
        ]
    )
    eligibility = normalize_eligibility(
        pd.DataFrame(
            [
                {
                    "ticker": "ABC",
                    "instrument": "COMMON",
                    "exchange": "XNAS",
                    "listing_country": "US",
                    "eligible_from": "2020-01-01",
                    "eligible_to": "2030-01-01",
                    "verified_asof": True,
                },
                {
                    "ticker": "KRX",
                    "instrument": "COMMON",
                    "exchange": "XKRX",
                    "listing_country": "KR",
                    "eligible_from": "2020-01-01",
                    "eligible_to": "2030-01-01",
                    "verified_asof": True,
                },
            ]
        )
    )
    events, rejected = build_events(
        filings,
        eligibility,
        history_start="2025-01-01",
        history_end="2025-12-31",
    )
    assert len(events) == 1
    event = events[0]
    assert event["security_id"] == "ABC"
    assert event["event_type"] == "MATERIAL_DEFINITIVE_AGREEMENT"
    assert event["official_evidence"] is True
    assert event["material_agreement_confirmed"] is True
    assert event["economic_value_confirmed"] is False
    assert event["economic_amount_usd"] is None
    assert event["business_relation_new"] is False
    assert event["theme_peer_ids"] == []
    assert len(rejected) == 2
    reasons = {x["reason"] for x in rejected}
    assert "NO_SUPPORTED_8K_ITEM" in reasons
    assert "NO_VERIFIED_US_COMMON_ADR_ELIGIBILITY" in reasons

    normalized = normalize_events(events)
    assert len(normalized) == 1
    assert normalized[0]["material_agreement_confirmed"] is True


def main() -> int:
    test_collector_preserves_sec_items()
    test_sec_seed_is_official_but_does_not_invent_amount_or_theme_breadth()
    print("news_event_sec_seed_v1_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
