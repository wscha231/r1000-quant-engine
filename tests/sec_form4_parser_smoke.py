#!/usr/bin/env python3
"""Smoke checks for SEC Form 4 parsing and ownership shadow scoring."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_sec_form4_parser import (  # noqa: E402
    FORM4_COLUMNS,
    cache_name,
    form4_url_candidates,
    parse_form4_xml,
    raw_form4_primary_document,
    write_outputs,
)
from tools.run_sec_ownership_signals import build_form4_signal  # noqa: E402


SAMPLE_FORM4 = """<?xml version="1.0"?>
<ownershipDocument>
  <issuer>
    <issuerCik>0000320193</issuerCik>
    <issuerTradingSymbol>AAPL</issuerTradingSymbol>
  </issuer>
  <reportingOwner>
    <reportingOwnerId>
      <rptOwnerCik>0001111111</rptOwnerCik>
      <rptOwnerName>Example CEO</rptOwnerName>
    </reportingOwnerId>
    <reportingOwnerRelationship>
      <isDirector>1</isDirector>
      <isOfficer>1</isOfficer>
      <isTenPercentOwner>0</isTenPercentOwner>
      <officerTitle>Chief Executive Officer</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2026-05-10</value></transactionDate>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>1000</value></transactionShares>
        <transactionPricePerShare><value>175.50</value></transactionPricePerShare>
      </transactionAmounts>
      <postTransactionAmounts>
        <sharesOwnedFollowingTransaction><value>5000</value></sharesOwnedFollowingTransaction>
      </postTransactionAmounts>
      <ownershipNature>
        <directOrIndirectOwnership><value>D</value></directOrIndirectOwnership>
      </ownershipNature>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>
"""


def test_form4_xml_parser_extracts_open_market_purchase() -> None:
    rows = parse_form4_xml(
        SAMPLE_FORM4,
        "0000320193-26-000001",
        {
            "filing_date": "2026-05-12",
            "accepted_at": "2026-05-12T21:30:00+00:00",
            "available_from": "2026-05-13T00:00:00+00:00",
            "filing_url": "https://www.sec.gov/example.xml",
        },
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["issuer_ticker"] == "AAPL"
    assert row["issuer_cik10"] == "0000320193"
    assert row["reporting_owner_cik"] == "0001111111"
    assert row["transaction_code"] == "P"
    assert row["transaction_value"] == 175_500.0
    assert row["available_from"] == "2026-05-13T00:00:00+00:00"


def test_form4_signal_is_shadow_only_and_uses_available_from_filter() -> None:
    rows = parse_form4_xml(
        SAMPLE_FORM4,
        "0000320193-26-000001",
        {
            "filing_date": "2026-05-12",
            "accepted_at": "2026-05-12T21:30:00+00:00",
            "available_from": "2026-05-13T00:00:00+00:00",
        },
    )
    frame = pd.DataFrame(rows)
    before = build_form4_signal(frame, as_of="2026-05-12T23:59:59+00:00")
    after = build_form4_signal(frame, as_of="2026-05-13T00:00:00+00:00")
    assert before.empty
    assert after.loc[0, "ticker"] == "AAPL"
    assert after.loc[0, "sec_form4_cluster_buy_score"] > 0
    assert "score_total" not in after.columns


def test_form4_signal_scores_all_insiders_with_ten_percent_owner_subscore() -> None:
    frame = pd.DataFrame(
        [
            {
                "issuer_ticker": "ABCD",
                "issuer_cik10": "0000000001",
                "reporting_owner_cik": "0000001001",
                "reporting_owner_name": "Large Holder",
                "officer_title": "",
                "is_director": False,
                "is_officer": False,
                "is_ten_percent_owner": True,
                "transaction_code": "P",
                "transaction_value": 2_000_000.0,
                "available_from": "2026-05-13T00:00:00+00:00",
            },
            {
                "issuer_ticker": "ABCD",
                "issuer_cik10": "0000000001",
                "reporting_owner_cik": "0000001002",
                "reporting_owner_name": "Outside Director",
                "officer_title": "",
                "is_director": True,
                "is_officer": False,
                "is_ten_percent_owner": False,
                "transaction_code": "P",
                "transaction_value": 250_000.0,
                "available_from": "2026-05-13T00:00:00+00:00",
            },
        ]
    )
    signals = build_form4_signal(frame, as_of="2026-05-14T00:00:00+00:00")
    assert signals.loc[0, "ticker"] == "ABCD"
    assert signals.loc[0, "insider_buy_count"] == 2
    assert signals.loc[0, "ten_percent_owner_buy_count"] == 1
    assert signals.loc[0, "sec_form4_ten_percent_owner_buy_score"] > 0
    assert signals.loc[0, "sec_form4_ceo_cfo_buy_score"] == 0


def test_form4_signal_filters_invalid_ticker_placeholders() -> None:
    frame = pd.DataFrame(
        [
            {
                "issuer_ticker": "NONE",
                "issuer_cik10": "0000000001",
                "reporting_owner_cik": "0000001001",
                "transaction_code": "P",
                "transaction_value": 100_000_000.0,
                "available_from": "2026-05-13T00:00:00+00:00",
            },
            {
                "issuer_ticker": "REAL",
                "issuer_cik10": "0000000002",
                "reporting_owner_cik": "0000001002",
                "transaction_code": "P",
                "transaction_value": 1_000_000.0,
                "available_from": "2026-05-13T00:00:00+00:00",
            },
        ]
    )
    signals = build_form4_signal(frame, as_of="2026-05-14T00:00:00+00:00")
    assert list(signals["ticker"]) == ["REAL"]


def test_xsl_form4_primary_document_uses_raw_xml_and_safe_cache_name() -> None:
    primary_doc = "xslF345X06/form4-05152026_080501.xml"
    assert raw_form4_primary_document(primary_doc) == "form4-05152026_080501.xml"
    assert "/" not in cache_name("0001778564-26-000049", primary_doc)
    urls = form4_url_candidates(
        "0001535527",
        "0001778564-26-000049",
        primary_doc,
        "https://www.sec.gov/Archives/edgar/data/1535527/000177856426000049/xslF345X06/form4-05152026_080501.xml",
    )
    assert urls[0].endswith("/000177856426000049/form4-05152026_080501.xml")
    assert "/xslF345X06/" not in urls[0]


def test_form4_output_schema_tolerates_parse_error_placeholders() -> None:
    row = {col: "" for col in FORM4_COLUMNS}
    row.update(
        {
            "issuer_ticker": "BROKEN",
            "issuer_cik10": "123",
            "reporting_owner_cik": "",
            "is_director": "",
            "is_officer": "",
            "is_ten_percent_owner": "",
            "is_derivative": "",
            "transaction_code": "PARSE_ERROR",
            "ownership_nature": "synthetic parse failure",
        }
    )
    with tempfile.TemporaryDirectory() as tmp:
        paths = write_outputs(pd.DataFrame([row]), Path(tmp))
        out = pd.read_parquet(paths["parquet"])
    assert bool(out.loc[0, "is_director"]) is False
    assert bool(out.loc[0, "is_officer"]) is False
    assert bool(out.loc[0, "is_ten_percent_owner"]) is False
    assert out.loc[0, "issuer_cik10"] == "0000000123"


if __name__ == "__main__":
    test_form4_xml_parser_extracts_open_market_purchase()
    test_form4_signal_is_shadow_only_and_uses_available_from_filter()
    test_form4_signal_scores_all_insiders_with_ten_percent_owner_subscore()
    test_form4_signal_filters_invalid_ticker_placeholders()
    test_xsl_form4_primary_document_uses_raw_xml_and_safe_cache_name()
    test_form4_output_schema_tolerates_parse_error_placeholders()
    print("sec_form4_parser_smoke passed")
