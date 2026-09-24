#!/usr/bin/env python3
"""Smoke checks for SEC Form 4 parsing and ownership shadow scoring."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_sec_form4_parser import cache_name, form4_url_candidates, parse_form4_xml, raw_form4_primary_document  # noqa: E402
from tools.run_sec_ownership_signals import build_form4_signal  # noqa: E402
from tools.run_sec_section16_parser import build_ownership_state, parse_section16_xml  # noqa: E402
from tools.run_sec_form4_merge_shards import normalize_section16_holdings, normalize_section16_transactions  # noqa: E402


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




SAMPLE_FORM3 = """<?xml version="1.0"?>
<ownershipDocument>
  <documentType>3</documentType>
  <periodOfReport>2026-05-01</periodOfReport>
  <issuer><issuerCik>0000320193</issuerCik><issuerTradingSymbol>AAPL</issuerTradingSymbol></issuer>
  <reportingOwner>
    <reportingOwnerId><rptOwnerCik>0002222222</rptOwnerCik><rptOwnerName>New Director</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><isDirector>1</isDirector><isOfficer>0</isOfficer><isTenPercentOwner>0</isTenPercentOwner></reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeHolding>
      <securityTitle><value>Common Stock</value></securityTitle>
      <postTransactionAmounts><sharesOwnedFollowingTransaction><value>250000</value></sharesOwnedFollowingTransaction></postTransactionAmounts>
      <ownershipNature><directOrIndirectOwnership><value>D</value></directOrIndirectOwnership></ownershipNature>
    </nonDerivativeHolding>
  </nonDerivativeTable>
</ownershipDocument>
"""

SAMPLE_FORM5 = """<?xml version="1.0"?>
<ownershipDocument>
  <documentType>5</documentType>
  <periodOfReport>2026-12-31</periodOfReport>
  <issuer><issuerCik>0000320193</issuerCik><issuerTradingSymbol>AAPL</issuerTradingSymbol></issuer>
  <reportingOwner>
    <reportingOwnerId><rptOwnerCik>0003333333</rptOwnerCik><rptOwnerName>Example Director</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><isDirector>1</isDirector><isOfficer>0</isOfficer><isTenPercentOwner>0</isTenPercentOwner></reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2026-11-10</value></transactionDate>
      <transactionCoding><transactionCode>G</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>50</value></transactionShares>
        <transactionPricePerShare><value>0</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
      <postTransactionAmounts><sharesOwnedFollowingTransaction><value>950</value></sharesOwnedFollowingTransaction></postTransactionAmounts>
      <ownershipNature><directOrIndirectOwnership><value>D</value></directOrIndirectOwnership></ownershipNature>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>
"""

SAMPLE_MULTI_OWNER_FORM3 = """<?xml version="1.0"?>
<ownershipDocument>
  <documentType>3</documentType>
  <periodOfReport>2026-05-01</periodOfReport>
  <issuer><issuerCik>0000320193</issuerCik><issuerTradingSymbol>AAPL</issuerTradingSymbol></issuer>
  <reportingOwner>
    <reportingOwnerId><rptOwnerCik>0004444444</rptOwnerCik><rptOwnerName>Owner A</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><isDirector>1</isDirector></reportingOwnerRelationship>
  </reportingOwner>
  <reportingOwner>
    <reportingOwnerId><rptOwnerCik>0005555555</rptOwnerCik><rptOwnerName>Owner B</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><isDirector>1</isDirector></reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeHolding>
      <securityTitle><value>Common Stock</value></securityTitle>
      <postTransactionAmounts><sharesOwnedFollowingTransaction><value>1000</value></sharesOwnedFollowingTransaction></postTransactionAmounts>
      <ownershipNature><directOrIndirectOwnership><value>I</value></directOrIndirectOwnership></ownershipNature>
    </nonDerivativeHolding>
  </nonDerivativeTable>
</ownershipDocument>
"""


def test_section16_form3_preserves_initial_holdings_without_fabricating_trade() -> None:
    tx, holdings = parse_section16_xml(
        SAMPLE_FORM3,
        filing={
            "form_type": "3",
            "filing_date": "2026-05-02",
            "accepted_at": "2026-05-02T20:00:00+00:00",
            "available_from": "2026-05-02T20:00:00+00:00",
            "accession_number": "0000320193-26-000003",
        },
    )
    assert tx == []
    assert len(holdings) == 1
    assert holdings[0]["form_type"] == "3"
    assert holdings[0]["shares_owned"] == 250000.0
    state = build_ownership_state(pd.DataFrame(tx), pd.DataFrame(holdings))
    assert len(state) == 1
    assert state.iloc[0]["reporting_owner_cik"] == "0002222222"
    assert state.iloc[0]["shares_owned"] == 250000.0


def test_section16_form5_preserves_transaction_as_data_only() -> None:
    tx, holdings = parse_section16_xml(
        SAMPLE_FORM5,
        filing={
            "form_type": "5",
            "filing_date": "2027-02-10",
            "accepted_at": "2027-02-10T21:00:00+00:00",
            "available_from": "2027-02-10T21:00:00+00:00",
            "accession_number": "0000320193-27-000005",
        },
    )
    assert holdings == []
    assert len(tx) == 1
    assert tx[0]["form_type"] == "5"
    assert tx[0]["transaction_code"] == "G"
    assert tx[0]["transaction_value"] == 0.0


def test_section16_merge_normalizers_preserve_form_and_derivative_identity() -> None:
    tx = pd.DataFrame(
        [
            {
                "issuer_ticker": "abc",
                "issuer_cik10": "123",
                "reporting_owner_cik": "999",
                "reporting_owners_json": "[]",
                "form_type": "5",
                "transaction_date": "2026-11-10",
                "transaction_code": "G",
                "acquired_disposed_code": "D",
                "security_title": "Option",
                "is_derivative": True,
                "transaction_shares": 50,
                "transaction_price": 0,
                "transaction_value": None,
                "available_from": "2027-02-10T21:00:00Z",
                "accession_number": "0000000123-27-000005",
            }
        ]
    )
    norm_tx = normalize_section16_transactions(pd.concat([tx, tx], ignore_index=True))
    assert len(norm_tx) == 1
    assert norm_tx.iloc[0]["form_type"] == "5"
    assert bool(norm_tx.iloc[0]["is_derivative"]) is True

    holdings = pd.DataFrame(
        [
            {
                "issuer_ticker": "abc",
                "issuer_cik10": "123",
                "reporting_owner_cik": "999",
                "reporting_owners_json": "[]",
                "form_type": "3",
                "security_title": "Common Stock",
                "is_derivative": False,
                "direct_or_indirect": "D",
                "shares_owned": 1000,
                "available_from": "2026-05-01T20:00:00Z",
                "accession_number": "0000000123-26-000003",
            }
        ]
    )
    norm_h = normalize_section16_holdings(pd.concat([holdings, holdings], ignore_index=True))
    assert len(norm_h) == 1
    assert norm_h.iloc[0]["form_type"] == "3"


def test_late_form5_does_not_regress_newer_effective_ownership_state() -> None:
    owner_json = '[{"reporting_owner_cik":"0000000999","reporting_owner_name":"CEO","officer_title":"Chief Executive Officer","is_director":true,"is_officer":true,"is_ten_percent_owner":false,"is_other":false}]'
    tx = pd.DataFrame(
        [
            {
                "issuer_ticker": "ABC",
                "issuer_cik10": "123",
                "reporting_owner_cik": "999",
                "reporting_owner_name": "CEO",
                "officer_title": "Chief Executive Officer",
                "is_director": True,
                "is_officer": True,
                "is_ten_percent_owner": False,
                "is_other": False,
                "reporting_owner_count": 1,
                "reporting_owners_json": owner_json,
                "form_type": "4",
                "period_of_report": "2026-12-15",
                "transaction_date": "2026-12-15",
                "filing_date": "2026-12-16",
                "accepted_at": "2026-12-16T20:00:00Z",
                "available_from": "2026-12-16T20:00:00Z",
                "shares_owned_after": 1200.0,
                "is_derivative": False,
                "security_title": "Common Stock",
                "direct_or_indirect": "D",
                "accession_number": "0000000123-26-000010",
            },
            {
                "issuer_ticker": "ABC",
                "issuer_cik10": "123",
                "reporting_owner_cik": "999",
                "reporting_owner_name": "CEO",
                "officer_title": "Chief Executive Officer",
                "is_director": True,
                "is_officer": True,
                "is_ten_percent_owner": False,
                "is_other": False,
                "reporting_owner_count": 1,
                "reporting_owners_json": owner_json,
                "form_type": "5",
                "period_of_report": "2026-12-31",
                "transaction_date": "2026-11-10",
                "filing_date": "2027-02-10",
                "accepted_at": "2027-02-10T21:00:00Z",
                "available_from": "2027-02-10T21:00:00Z",
                "shares_owned_after": 900.0,
                "is_derivative": False,
                "security_title": "Common Stock",
                "direct_or_indirect": "D",
                "accession_number": "0000000123-27-000005",
            },
        ]
    )
    state = build_ownership_state(tx, pd.DataFrame())
    assert len(state) == 1
    assert state.iloc[0]["form_type"] == "4"
    assert state.iloc[0]["state_effective_date"] == "2026-12-15"
    assert state.iloc[0]["shares_owned"] == 1200.0


def test_section16_multi_owner_state_fails_closed_instead_of_duplicating_ownership() -> None:
    tx, holdings = parse_section16_xml(
        SAMPLE_MULTI_OWNER_FORM3,
        filing={
            "form_type": "3",
            "accepted_at": "2026-05-02T20:00:00+00:00",
            "available_from": "2026-05-02T20:00:00+00:00",
            "accession_number": "0000320193-26-000004",
        },
    )
    assert tx == []
    assert len(holdings) == 1
    assert holdings[0]["reporting_owner_count"] == 2
    assert "0004444444" in holdings[0]["reporting_owners_json"]
    assert "0005555555" in holdings[0]["reporting_owners_json"]
    state = build_ownership_state(pd.DataFrame(tx), pd.DataFrame(holdings))
    assert state.empty


if __name__ == "__main__":
    test_form4_xml_parser_extracts_open_market_purchase()
    test_form4_signal_is_shadow_only_and_uses_available_from_filter()
    test_xsl_form4_primary_document_uses_raw_xml_and_safe_cache_name()
    test_section16_form3_preserves_initial_holdings_without_fabricating_trade()
    test_section16_form5_preserves_transaction_as_data_only()
    test_section16_merge_normalizers_preserve_form_and_derivative_identity()
    test_late_form5_does_not_regress_newer_effective_ownership_state()
    test_section16_multi_owner_state_fails_closed_instead_of_duplicating_ownership()
    print("sec_form4_parser_smoke passed")
