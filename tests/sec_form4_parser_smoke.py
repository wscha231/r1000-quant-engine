#!/usr/bin/env python3
"""Smoke tests for SEC Form 4 parsing."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_sec_form4_parser import parse_form4_document, parse_form4_xml  # noqa: E402


FORM4_XML = """<?xml version="1.0"?>
<ownershipDocument>
  <issuer>
    <issuerCik>0000320193</issuerCik>
    <issuerTradingSymbol>AAPL</issuerTradingSymbol>
  </issuer>
  <reportingOwner>
    <reportingOwnerId>
      <rptOwnerCik>0001234567</rptOwnerCik>
      <rptOwnerName>Test CEO</rptOwnerName>
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
      <transactionDate><value>2026-05-13</value></transactionDate>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>1000</value></transactionShares>
        <transactionPricePerShare><value>125.50</value></transactionPricePerShare>
      </transactionAmounts>
      <postTransactionAmounts>
        <sharesOwnedFollowingTransaction><value>12000</value></sharesOwnedFollowingTransaction>
      </postTransactionAmounts>
      <ownershipNature><directOrIndirectOwnership><value>D</value></directOrIndirectOwnership></ownershipNature>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2026-05-14</value></transactionDate>
      <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>200</value></transactionShares>
        <transactionPricePerShare><value>130.00</value></transactionPricePerShare>
      </transactionAmounts>
      <postTransactionAmounts>
        <sharesOwnedFollowingTransaction><value>11800</value></sharesOwnedFollowingTransaction>
      </postTransactionAmounts>
      <ownershipNature><directOrIndirectOwnership><value>D</value></directOrIndirectOwnership></ownershipNature>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>
"""


def test_parse_form4_open_market_purchase_and_sale() -> None:
    rows = parse_form4_xml(FORM4_XML, "0000320193-26-000001")
    assert len(rows) == 2
    buy = rows[0]
    sale = rows[1]
    assert buy["issuer_ticker"] == "AAPL"
    assert buy["issuer_cik10"] == "0000320193"
    assert buy["reporting_owner_cik"] == "0001234567"
    assert buy["is_director"] is True
    assert buy["is_officer"] is True
    assert buy["transaction_code"] == "P"
    assert buy["transaction_value"] == 125500.0
    assert sale["transaction_code"] == "S"
    assert sale["transaction_value"] == 26000.0


def test_parse_rendered_html_form4_table() -> None:
    html = """
    <html><body>
      <a href="/cgi-bin/browse-edgar?action=getcompany&CIK=0001214128">LEVINSON ARTHUR D</a>
      Issuer Name [ AAPL ]
      <a href="/cgi-bin/browse-edgar?action=getcompany&CIK=0000320193">Apple Inc.</a>
      Director Officer 10% Owner
      <table><tr><th>Table I - Non-Derivative Securities Acquired, Disposed of, or Beneficially Owned</th></tr>
      <tr><td>Common Stock</td><td>05/06/2026</td><td></td><td>S</td><td></td><td>149,527</td><td>D</td><td>$284.57</td><td>3,920,049</td><td>D</td><td></td></tr>
      <tr><td>Common Stock</td><td>05/07/2026</td><td></td><td>P</td><td></td><td>1,000</td><td>A</td><td>$125.50</td><td>3,921,049</td><td>D</td><td></td></tr>
      </table>
    </body></html>
    """
    rows = parse_form4_document(html, "0000320193-26-000003")
    assert len(rows) == 2
    assert rows[0]["issuer_ticker"] == "AAPL"
    assert rows[0]["issuer_cik10"] == "0000320193"
    assert rows[0]["transaction_code"] == "S"
    assert rows[0]["transaction_value"] == 149527 * 284.57
    assert rows[1]["transaction_code"] == "P"
    assert rows[1]["transaction_value"] == 125500.0


def main() -> int:
    test_parse_form4_open_market_purchase_and_sale()
    test_parse_rendered_html_form4_table()
    print("sec_form4_parser_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
