#!/usr/bin/env python3
"""Synthetic contract checks for SEC balance-sheet resilience events."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.run_sec_balance_sheet_resilience_event as balance  # noqa: E402
import tools.run_sec_filing_quality_event as quality  # noqa: E402


CIK = "0000000123"
ACCESSIONS = (
    "0000000123-24-000001",
    "0000000123-24-000002",
    "0000000123-24-000003",
)
PERIODS = ("2024-03-31", "2024-06-30", "2024-09-30")
ACCEPTED = (
    "2024-04-30T20:30:00Z",
    "2024-07-01T19:00:00Z",
    "2024-10-01T19:00:00Z",
)


def tag(values: tuple[float, float, float], *, form: str = "10-Q") -> dict[str, object]:
    return {
        "units": {
            "USD": [
                {
                    "end": period,
                    "val": value,
                    "accn": accession,
                    "form": form,
                    "fy": 2024,
                    "fp": f"Q{index + 1}",
                    "filed": "1900-01-01",
                }
                for index, (period, value, accession) in enumerate(zip(PERIODS, values, ACCESSIONS))
            ]
        }
    }


def payload(*, total_debt_second: bool = False) -> dict[str, object]:
    facts: dict[str, object] = {
        "Assets": tag((100.0, 120.0, 100.0)),
        "CashAndCashEquivalentsAtCarryingValue": tag((10.0, 12.0, 0.0)),
        "LongTermDebtNoncurrent": tag((30.0, 20.0, 50.0)),
        "DebtCurrent": tag((10.0, 16.0, 10.0)),
    }
    if total_debt_second:
        facts["LongTermDebt"] = {
            "units": {
                "USD": [
                    {
                        "end": PERIODS[1],
                        "val": 36.0,
                        "accn": ACCESSIONS[1],
                        "form": "10-Q",
                        "fy": 2024,
                        "fp": "Q2",
                    }
                ]
            }
        }
        facts["LongTermDebtNoncurrent"]["units"]["USD"] = [  # type: ignore[index]
            row for row in facts["LongTermDebtNoncurrent"]["units"]["USD"]  # type: ignore[index]
            if row["accn"] != ACCESSIONS[1]
        ]
        facts["DebtCurrent"]["units"]["USD"] = [  # type: ignore[index]
            row for row in facts["DebtCurrent"]["units"]["USD"]  # type: ignore[index]
            if row["accn"] != ACCESSIONS[1]
        ]
    return {"cik": 123, "facts": {"us-gaap": facts}}


def filings() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": "TEST",
                "cik10": CIK,
                "accession_number": accession,
                "form_type": "10-Q",
                "period_of_report": period,
                "accepted_at": accepted,
            }
            for accession, period, accepted in zip(ACCESSIONS, PERIODS, ACCEPTED)
        ]
    )


def extract(test_payload: dict[str, object]) -> tuple[pd.DataFrame, dict[str, dict[str, str]]]:
    raw = json.dumps(test_payload).encode("utf-8")
    item = quality.CompanyfactsPayload(CIK, test_payload, quality.sha256_bytes(raw), "fixture.json")
    return balance.extract_balance_facts(item), {
        CIK: {"companyfacts_sha256": item.sha256, "companyfacts_member": item.source_member}
    }


def build(test_payload: dict[str, object] | None = None, filing_frame: pd.DataFrame | None = None):
    facts, sources = extract(test_payload or payload())
    return balance.build_events(
        facts,
        filing_frame if filing_frame is not None else filings(),
        sources=sources,
        submissions_sha256="fixture-submissions-sha",
        available_tickers=["TEST"],
    )


def prices() -> pd.DataFrame:
    dates = pd.bdate_range("2023-01-03", "2025-12-31")
    return pd.concat(
        [
            pd.DataFrame(
                {"ticker": ticker, "date": dates, "adjusted_close": np.linspace(start, end, len(dates))}
            )
            for ticker, start, end in (("TEST", 10.0, 20.0), ("SPY", 100.0, 110.0))
        ],
        ignore_index=True,
    )


def test_positive_and_negative_directions_are_within_issuer_changes() -> None:
    events, diagnostics = build()
    by_accession = events.set_index("accession_number")
    assert by_accession.loc[ACCESSIONS[0], "sec_balance_sheet_resilience_event"] == "neutral"
    assert by_accession.loc[ACCESSIONS[1], "sec_balance_sheet_resilience_event"] == "positive"
    assert by_accession.loc[ACCESSIONS[2], "sec_balance_sheet_resilience_event"] == "negative"
    assert np.isclose(by_accession.loc[ACCESSIONS[1], "debt_to_assets"], 0.30)
    assert np.isclose(by_accession.loc[ACCESSIONS[1], "net_debt_to_assets"], 0.20)
    assert by_accession.loc[ACCESSIONS[1], "prior_debt_scope"] == "NONCURRENT_PLUS_CURRENT_COMPLETE"
    assert pd.Timestamp(by_accession.loc[ACCESSIONS[1], "prior_accepted_at"]) < pd.Timestamp(
        by_accession.loc[ACCESSIONS[1], "accepted_at"]
    )
    assert diagnostics["positive_count"] == 1
    assert diagnostics["negative_count"] == 1
    assert diagnostics["filed_date_fallback_used"] is False


def test_changed_debt_scope_is_missing_neutral() -> None:
    events, _ = build(payload(total_debt_second=True))
    row = events.set_index("accession_number").loc[ACCESSIONS[1]]
    assert row["debt_scope"] == "REPORTED_TOTAL_COMPLETE"
    assert row["component_coverage"] == 0
    assert row["sec_balance_sheet_resilience_event"] == "neutral"


def test_filed_only_row_fails_closed() -> None:
    frame = filings().iloc[:2].copy()
    frame.loc[frame.index[1], "accepted_at"] = ""
    events, diagnostics = build(filing_frame=frame)
    assert diagnostics["missing_exact_acceptance_count"] == 1
    assert ACCESSIONS[1] not in set(events["accession_number"])


def test_source_screen_is_underpowered_and_entry_is_after_acceptance() -> None:
    events, _ = build(filing_frame=filings().iloc[:2].copy())
    labeled, summary = balance.source_screen(
        events,
        prices(),
        oos_start=balance.OOS_START,
        oos2_start=balance.OOS2_START,
        iterations=20,
        seed=287,
    )
    row = labeled.set_index("accession_number").loc[ACCESSIONS[1]]
    assert row["entry_date"] == "2024-07-01"
    assert summary["verdict"] == "UNDERPOWERED"
    assert summary["portfolio_ab_authorized"] is False


if __name__ == "__main__":
    test_positive_and_negative_directions_are_within_issuer_changes()
    test_changed_debt_scope_is_missing_neutral()
    test_filed_only_row_fails_closed()
    test_source_screen_is_underpowered_and_entry_is_after_acceptance()
    print("sec_balance_sheet_resilience_event_smoke: PASS")
