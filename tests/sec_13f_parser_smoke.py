#!/usr/bin/env python3
"""Smoke checks for SEC 13F parsing and institutional shadow scoring."""
from __future__ import annotations

import sys
import subprocess
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import tools.run_sec_13f_parser as parser_module  # noqa: E402
from tools.run_sec_13f_parser import amendment_type_from_text, market_value_usd, parse_13f_index, parse_13f_xml, write_outputs  # noqa: E402
from tools.run_sec_institutional_signals import build_13f_signal, prepare_13f_holdings  # noqa: E402


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


def test_13f_parser_max_filings_prefers_latest_accepted_at() -> None:
    older = {
        "ticker": "OLD",
        "cik10": "0000000001",
        "accession_number": "0000000001-20-000001",
        "form_type": "13F-HR",
        "filing_date": "2020-02-15",
        "accepted_at": "2020-02-15T18:00:00+00:00",
        "available_from": "2020-02-15T18:00:00+00:00",
        "period_of_report": "2019-12-31",
        "primary_document": "bad.xml",
        "filing_url": "",
    }
    newer = {
        **older,
        "ticker": "NEW",
        "cik10": "0000000002",
        "accession_number": "0000000002-26-000001",
        "filing_date": "2026-05-15",
        "accepted_at": "2026-05-15T18:00:00+00:00",
        "available_from": "2026-05-15T18:00:00+00:00",
        "period_of_report": "2026-03-31",
    }
    frame = parse_13f_index(
        pd.DataFrame([older, newer]),
        raw_dir=Path("."),
        max_filings=1,
        sleep_s=0.0,
    )
    assert len(frame) == 1
    assert frame.iloc[0]["manager_cik"] == "0000000002"


def test_13f_parser_excludes_not_yet_available_filings() -> None:
    base = {
        "ticker": "MGR",
        "cik10": "0000000001",
        "accession_number": "0000000001-26-000001",
        "form_type": "13F-HR",
        "filing_date": "2026-08-14",
        "accepted_at": "2026-08-14T20:00:00+00:00",
        "available_from": "2026-08-14T22:00:00+00:00",
        "period_of_report": "2026-06-30",
        "primary_document": "info.xml",
        "filing_url": "",
    }
    original_cache = parser_module.cache_13f_document
    try:
        parser_module.cache_13f_document = (  # type: ignore[assignment]
            lambda *args, **kwargs: (Path("fixture.xml"), SAMPLE_13F)
        )
        before = parse_13f_index(
            pd.DataFrame([base]),
            raw_dir=Path("."),
            as_of="2026-08-14T21:59:59+00:00",
        )
        after = parse_13f_index(
            pd.DataFrame([base]),
            raw_dir=Path("."),
            as_of="2026-08-14T22:00:00+00:00",
        )
    finally:
        parser_module.cache_13f_document = original_cache  # type: ignore[assignment]
    assert before.empty
    assert len(after) == 1


def test_institutional_signal_cli_refuses_empty_verified_result() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        holdings = root / "holdings.csv"
        output = root / "signals"
        pd.DataFrame(columns=["manager_cik", "ticker_mapped", "report_period"]).to_csv(holdings, index=False)
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "run_sec_institutional_signals.py"),
                "--holdings",
                str(holdings),
                "--output-dir",
                str(output),
                "--require-nonempty",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "refusing publication" in (result.stdout + result.stderr)
        assert not output.exists()


def test_amendment_type_and_restatement_snapshot_semantics() -> None:
    assert amendment_type_from_text("<amendmentType>RESTATEMENT</amendmentType>") == "RESTATEMENT"
    assert amendment_type_from_text("<ns:amendmentType>NEW HOLDINGS</ns:amendmentType>") == "NEW HOLDINGS"
    rows = []
    for ticker in ["AAPL", "MSFT"]:
        rows.append(
            {
                "manager_cik": "0000000001",
                "ticker_mapped": ticker,
                "report_period": "2026-06-30",
                "available_from": "2026-08-14T20:00:00+00:00",
                "accepted_at": "2026-08-14T20:00:00+00:00",
                "source_accession": "base",
                "form_type": "13F-HR",
                "amendment_type": "",
                "shares": 10.0,
                "market_value_usd": 100.0,
            }
        )
    rows.append(
        {
            **rows[0],
            "accepted_at": "2026-08-17T20:00:00+00:00",
            "available_from": "2026-08-17T20:00:00+00:00",
            "source_accession": "restatement",
            "form_type": "13F-HR/A",
            "amendment_type": "RESTATEMENT",
            "shares": 20.0,
        }
    )
    rows.append(
        {
            **rows[0],
            "ticker_mapped": "NVDA",
            "accepted_at": "2026-08-18T20:00:00+00:00",
            "available_from": "2026-08-18T20:00:00+00:00",
            "source_accession": "new-holdings",
            "form_type": "13F-HR/A",
            "amendment_type": "NEW HOLDINGS",
        }
    )
    prepared = prepare_13f_holdings(pd.DataFrame(rows))
    assert set(prepared["ticker"]) == {"AAPL", "NVDA"}
    assert "MSFT" not in set(prepared["ticker"])
    historical = prepare_13f_holdings(pd.DataFrame(rows), as_of="2026-08-15T00:00:00+00:00")
    assert set(historical["ticker"]) == {"AAPL", "MSFT"}


if __name__ == "__main__":
    test_13f_xml_parser_extracts_information_table_rows()
    test_13f_signal_is_pit_and_scores_accumulation()
    test_13f_write_outputs_normalizes_parse_error_dtypes()
    test_13f_parser_excludes_not_yet_available_filings()
    test_institutional_signal_cli_refuses_empty_verified_result()
    test_amendment_type_and_restatement_snapshot_semantics()
    print("sec_13f_parser_smoke: PASS")
