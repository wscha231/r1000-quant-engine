#!/usr/bin/env python3
"""Offline contract checks for the SEC capital-allocation event screen."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.run_sec_capital_allocation_event as capital  # noqa: E402
import tools.run_sec_filing_quality_event as quality  # noqa: E402


CIK = "0000000123"


def fixture(action_tag: str, action_value: float) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, dict[str, str]]]:
    accn = "0000000123-24-000001"
    payload = {
        "cik": 123,
        "facts": {
            "dei": {
                "EntityCommonStockSharesOutstanding": {
                    "units": {"shares": [{"end": "2024-06-30", "val": 100000.0, "accn": accn, "fy": 2024, "fp": "Q2", "form": "10-Q"}]}
                }
            },
            "us-gaap": {
                action_tag: {
                    "units": {"USD": [{"start": "2024-04-01", "end": "2024-06-30", "val": action_value, "accn": accn, "fy": 2024, "fp": "Q2", "form": "10-Q", "filed": "1900-01-01"}]}
                }
            },
        },
    }
    raw = json.dumps(payload).encode()
    item = quality.CompanyfactsPayload(CIK, payload, quality.sha256_bytes(raw), "fixture.json")
    facts = capital.extract_capital_facts(item)
    filings = pd.DataFrame([{
        "ticker": "TEST", "cik10": CIK, "accession_number": accn, "form_type": "10-Q",
        "period_of_report": "2024-06-30", "accepted_at": "2024-07-01T19:00:00Z",
    }])
    return facts, filings, {CIK: {"companyfacts_sha256": item.sha256, "companyfacts_member": item.source_member}}


def prices() -> pd.DataFrame:
    dates = pd.bdate_range("2023-01-03", "2025-12-31")
    return pd.concat([
        pd.DataFrame({"ticker": ticker, "date": dates, "raw_close": raw, "adjusted_close": adjusted})
        for ticker, raw, adjusted in (("TEST", 10.0, 5.0), ("SPY", 500.0, 500.0))
    ], ignore_index=True)


def build(tag: str, value: float) -> pd.Series:
    facts, filings, sources = fixture(tag, value)
    events, diagnostics = capital.build_events(
        facts, filings, prices(), sources=sources, submissions_sha256="fixture-sha"
    )
    assert diagnostics["filed_date_fallback_used"] is False
    return events.iloc[0]


def test_repurchase_is_positive_and_uses_raw_close_for_market_cap() -> None:
    row = build("PaymentsForRepurchaseOfCommonStock", 20000.0)
    assert row["sec_capital_allocation_event"] == "positive"
    assert np.isclose(row["market_cap"], 1000000.0)
    assert np.isclose(row["raw_close"], 10.0)


def test_common_issuance_and_convertible_proceeds_are_negative() -> None:
    issuance = build("ProceedsFromIssuanceOfCommonStock", 20000.0)
    convertible = build("ProceedsFromConvertibleDebt", 20000.0)
    assert issuance["sec_capital_allocation_event"] == "negative"
    assert convertible["sec_capital_allocation_event"] == "negative"


def test_filed_only_row_fails_closed() -> None:
    facts, filings, sources = fixture("PaymentsForRepurchaseOfCommonStock", 20000.0)
    filings["accepted_at"] = ""
    events, diagnostics = capital.build_events(
        facts, filings, prices(), sources=sources, submissions_sha256="fixture-sha"
    )
    assert events.empty
    assert diagnostics["missing_exact_acceptance_count"] == 1


def test_implausible_share_context_is_neutral() -> None:
    facts, filings, sources = fixture("PaymentsForRepurchaseOfCommonStock", 20000.0)
    facts.loc[facts["fact_group"].eq("shares_outstanding"), "value"] = 1.0
    events, diagnostics = capital.build_events(
        facts, filings, prices(), sources=sources, submissions_sha256="fixture-sha"
    )
    row = events.iloc[0]
    assert row["sec_capital_allocation_event"] == "neutral"
    assert not bool(row["market_cap_valid"])
    assert diagnostics["market_cap_invalid_count"] == 1


def test_source_screen_is_underpowered_and_entry_is_after_acceptance() -> None:
    facts, filings, sources = fixture("PaymentsForRepurchaseOfCommonStock", 20000.0)
    events, _ = capital.build_events(facts, filings, prices(), sources=sources, submissions_sha256="fixture-sha")
    labeled, summary = capital.source_screen(
        events, prices(), oos_start=capital.OOS_START, oos2_start=capital.OOS2_START, iterations=20, seed=287
    )
    assert labeled.iloc[0]["entry_date"] == "2024-07-01"
    assert summary["verdict"] == "UNDERPOWERED"
    assert summary["portfolio_ab_authorized"] is False
