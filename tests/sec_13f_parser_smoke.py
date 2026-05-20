#!/usr/bin/env python3
"""Smoke checks for SEC 13F parsing and institutional shadow scoring."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_sec_13f_parser import market_value_usd, parse_13f_xml, write_outputs  # noqa: E402
from tools.run_sec_institutional_signals import build_13f_signal  # noqa: E402


SAMPLE_13F = """<?xml version="1.0" encoding="UTF-8"?>
<informationTable>
  <infoTable>
    <nameOfIssuer>APPLE INC</nameOfIssuer>
    <titleOfClass>COM</titleOfClass>
    <cusip>037833100</cusip>
    <ticker>AAPL</ticker>
    <value>10000</value>
    <shrsOrPrnAmt>
      <sshPrnamt>100000</sshPrnamt>
      <sshPrnamtType>SH</sshPrnamtType>
    </shrsOrPrnAmt>
    <investmentDiscretion>SOLE</investmentDiscretion>
    <votingAuthority>
      <Sole>100000</Sole>
      <Shared>0</Shared>
      <None>0</None>
    </votingAuthority>
  </infoTable>
</informationTable>
"""


def _holding_rows() -> list[dict[str, object]]:
    base = parse_13f_xml(
        SAMPLE_13F,
        {
            "cik10": "0001067983",
            "manager_name": "Example Manager",
            "period_of_report": "2025-12-31",
            "filing_date": "2026-02-14",
            "accepted_at": "2026-02-14T18:00:00+00:00",
            "available_from": "2026-02-14T18:00:00+00:00",
            "accession_number": "0001067983-26-000001",
        },
    )
    later = parse_13f_xml(
        SAMPLE_13F.replace("<value>10000</value>", "<value>16000</value>").replace(
            "<sshPrnamt>100000</sshPrnamt>", "<sshPrnamt>160000</sshPrnamt>"
        ),
        {
            "cik10": "0001067983",
            "manager_name": "Example Manager",
            "period_of_report": "2026-03-31",
            "filing_date": "2026-05-15",
            "accepted_at": "2026-05-15T18:00:00+00:00",
            "available_from": "2026-05-15T18:00:00+00:00",
            "accession_number": "0001067983-26-000002",
        },
    )
    second_manager = parse_13f_xml(
        SAMPLE_13F.replace("<value>10000</value>", "<value>4000</value>").replace(
            "<sshPrnamt>100000</sshPrnamt>", "<sshPrnamt>40000</sshPrnamt>"
        ),
        {
            "cik10": "0000002222",
            "manager_name": "Second Manager",
            "period_of_report": "2026-03-31",
            "filing_date": "2026-05-15",
            "accepted_at": "2026-05-15T19:00:00+00:00",
            "available_from": "2026-05-15T19:00:00+00:00",
            "accession_number": "0000002222-26-000002",
        },
    )
    return [*base, *later, *second_manager]


def test_13f_xml_parser_extracts_information_table_rows() -> None:
    rows = parse_13f_xml(
        SAMPLE_13F,
        {
            "cik10": "0001067983",
            "manager_name": "Example Manager",
            "period_of_report": "2026-03-31",
            "accepted_at": "2026-05-15T18:00:00+00:00",
        },
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["manager_cik"] == "0001067983"
    assert row["ticker_mapped"] == "AAPL"
    assert row["cusip"] == "037833100"
    assert row["shares"] == 100000.0
    assert row["market_value_usd"] == 10_000.0
    assert market_value_usd("10000", "2022-12-31") == 10_000_000.0
    assert market_value_usd("10000", "2026-05-15") == 10_000.0


def test_13f_signal_is_pit_and_scores_accumulation() -> None:
    frame = pd.DataFrame(_holding_rows())
    before = build_13f_signal(frame, as_of="2026-05-15T18:30:00+00:00", lookback_days=210)
    after = build_13f_signal(frame, as_of="2026-05-15T23:59:59+00:00", lookback_days=210)
    assert before.loc[0, "ticker"] == "AAPL"
    assert int(before.loc[0, "sec_13f_manager_count"]) == 1
    assert int(after.loc[0, "sec_13f_manager_count"]) == 2
    assert float(after.loc[0, "sec_13f_value_delta_usd"]) > 0.0
    assert float(after.loc[0, "sec_13f_smart_money_score"]) > 0.0
    assert "score_total" not in after.columns


def test_13f_write_outputs_normalizes_parse_error_dtypes() -> None:
    rows = _holding_rows()
    rows.append(
        {
            **{key: "" for key in rows[0].keys()},
            "manager_cik": "0000000003",
            "manager_name": "Bad Filing",
            "shares": "",
            "market_value_usd": "",
            "issuer_name": "PARSE_ERROR: bad fixture",
        }
    )
    with tempfile.TemporaryDirectory() as tmp:
        paths = write_outputs(pd.DataFrame(rows), Path(tmp))
        out = pd.read_parquet(paths["parquet"])
        assert str(out["shares"].dtype).startswith("float")
        assert str(out["market_value_usd"].dtype).startswith("float")
        assert out["issuer_name"].astype(str).str.contains("PARSE_ERROR").any()


if __name__ == "__main__":
    test_13f_xml_parser_extracts_information_table_rows()
    test_13f_signal_is_pit_and_scores_accumulation()
    test_13f_write_outputs_normalizes_parse_error_dtypes()
    print("sec_13f_parser_smoke: PASS")
