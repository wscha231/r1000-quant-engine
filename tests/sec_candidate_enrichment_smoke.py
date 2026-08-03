#!/usr/bin/env python3
"""Smoke checks for SEC-enriched candidate replay books."""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_sec_enriched_candidate_replay import run  # noqa: E402


def _candidate_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for dt in ["2026-05-12", "2026-05-13", "2026-05-15"]:
        rows.extend(
            [
                {
                    "rebalance_date": dt,
                    "valuation_price_cutoff_date": dt,
                    "feature_available_from": f"{dt}T20:00:00Z",
                    "ticker": "AAPL",
                    "Name": "Apple Inc.",
                    "score_total": 1.23,
                    "portfolio_future_winner_engine_score": 0.90,
                    "selection_market_confirmation_score": 0.80,
                    "industry_group_strength_score": 0.70,
                    "rs_acceleration_score": 0.60,
                    "entry_quality_score": 0.50,
                    "period_forward_return": 9.99,
                },
                {
                    "rebalance_date": dt,
                    "valuation_price_cutoff_date": dt,
                    "feature_available_from": f"{dt}T20:00:00Z",
                    "ticker": "MSFT",
                    "Name": "Microsoft Corporation",
                    "score_total": 2.34,
                    "portfolio_future_winner_engine_score": 0.30,
                    "selection_market_confirmation_score": 0.40,
                    "industry_group_strength_score": 0.20,
                    "rs_acceleration_score": 0.10,
                    "entry_quality_score": 0.20,
                    "period_forward_return": -9.99,
                },
            ]
        )
    return rows


def _form4_rows() -> list[dict[str, object]]:
    return [
        {
            "issuer_ticker": "AAPL",
            "issuer_cik10": "0000320193",
            "reporting_owner_cik": "0001111111",
            "reporting_owner_name": "Example CEO",
            "officer_title": "Chief Executive Officer",
            "is_director": True,
            "is_officer": True,
            "is_ten_percent_owner": False,
            "transaction_date": "2026-05-10",
            "filing_date": "2026-05-12",
            "accepted_at": "2026-05-13T00:00:00+00:00",
            "available_from": "2026-05-13T00:00:00+00:00",
            "transaction_code": "P",
            "transaction_shares": 1000.0,
            "transaction_price": 100.0,
            "transaction_value": 100000.0,
            "ownership_nature": "",
            "direct_or_indirect": "D",
            "shares_owned_after": 5000.0,
            "is_derivative": False,
            "security_title": "Common Stock",
            "accession_number": "0000320193-26-000001",
            "filing_url": "https://www.sec.gov/example.xml",
        },
        {
            "issuer_ticker": "MSFT",
            "issuer_cik10": "0000789019",
            "reporting_owner_cik": "0002222222",
            "reporting_owner_name": "Example CFO",
            "officer_title": "Chief Financial Officer",
            "is_director": False,
            "is_officer": True,
            "is_ten_percent_owner": False,
            "transaction_date": "2026-05-12",
            "filing_date": "2026-05-13",
            "accepted_at": "2026-05-13T21:00:00+00:00",
            "available_from": "2026-05-13T21:00:00+00:00",
            "transaction_code": "P",
            "transaction_shares": 500.0,
            "transaction_price": 200.0,
            "transaction_value": 100000.0,
            "ownership_nature": "",
            "direct_or_indirect": "D",
            "shares_owned_after": 2500.0,
            "is_derivative": False,
            "security_title": "Common Stock",
            "accession_number": "0000789019-26-000001",
            "filing_url": "https://www.sec.gov/example-msft.xml",
        },
    ]


def _thirteen_f_rows() -> list[dict[str, object]]:
    return [
        {
            "manager_cik": "0001067983",
            "manager_name": "Example Manager",
            "report_period": "2025-12-31",
            "filing_date": "2026-02-14",
            "accepted_at": "2026-02-14T18:00:00+00:00",
            "available_from": "2026-02-14T18:00:00+00:00",
            "cusip": "037833100",
            "issuer_name": "APPLE INC",
            "title_of_class": "COM",
            "ticker_mapped": "",
            "shares": 100000.0,
            "share_type": "SH",
            "market_value_usd": 10_000_000.0,
            "put_call": "",
            "investment_discretion": "SOLE",
            "other_manager": "",
            "voting_authority_sole": 100000.0,
            "voting_authority_shared": 0.0,
            "voting_authority_none": 0.0,
            "source_accession": "0001067983-26-000001",
            "filing_url": "https://www.sec.gov/example-13f.xml",
        },
        {
            "manager_cik": "0001067983",
            "manager_name": "Example Manager",
            "report_period": "2026-03-31",
            "filing_date": "2026-05-15",
            "accepted_at": "2026-05-15T18:00:00+00:00",
            "available_from": "2026-05-15T18:00:00+00:00",
            "cusip": "037833100",
            "issuer_name": "APPLE INC",
            "title_of_class": "COM",
            "ticker_mapped": "",
            "shares": 180000.0,
            "share_type": "SH",
            "market_value_usd": 18_000_000.0,
            "put_call": "",
            "investment_discretion": "SOLE",
            "other_manager": "",
            "voting_authority_sole": 180000.0,
            "voting_authority_shared": 0.0,
            "voting_authority_none": 0.0,
            "source_accession": "0001067983-26-000002",
            "filing_url": "https://www.sec.gov/example-13f-2.xml",
        },
    ]


def _etf_rows() -> list[dict[str, object]]:
    return [
        {
            "etf_ticker": "AIQ",
            "etf_label": "AI ETF",
            "theme": "ai_infra",
            "holding_ticker": "AAPL",
            "holding_name": "Apple Inc.",
            "holding_weight": 0.08,
            "source": "fixture",
            "as_of_date": "2026-05-13T00:00:00+00:00",
            "available_from": "2026-05-13T00:00:00+00:00",
        },
        {
            "etf_ticker": "SEMI",
            "etf_label": "Semi ETF",
            "theme": "semis",
            "holding_ticker": "AAPL",
            "holding_name": "Apple Inc.",
            "holding_weight": 0.05,
            "source": "fixture",
            "as_of_date": "2026-05-13T00:00:00+00:00",
            "available_from": "2026-05-13T00:00:00+00:00",
        },
    ]


def test_sec_candidate_enrichment_is_pit_and_research_only() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        candidate = root / "candidate_replay_book.csv"
        form4 = root / "form4_transactions.parquet"
        holdings_13f = root / "institutional_13f_holdings.parquet"
        etf_holdings = root / "etf_holdings.parquet"
        out = root / "sec_enriched"
        pd.DataFrame(_candidate_rows()).to_csv(candidate, index=False)
        pd.DataFrame(_form4_rows()).to_parquet(form4, index=False)
        pd.DataFrame(_thirteen_f_rows()).to_parquet(holdings_13f, index=False)
        pd.DataFrame(_etf_rows()).to_parquet(etf_holdings, index=False)

        payload = run(
            argparse.Namespace(
                candidate_book=str(candidate),
                form4=str(form4),
                institutional_13f=str(holdings_13f),
                etf_holdings=str(etf_holdings),
                output_dir=str(out),
                lookback_days=90,
                institutional_lookback_days=210,
                strict_source_contract=True,
            )
        )

        assert payload["research_only"] is True
        assert payload["production_activation_allowed"] is False
        assert payload["score_total_changed"] is False
        assert payload["rows_with_sec_evidence"] == 3
        assert payload["rows_with_13f_evidence"] == 3
        assert payload["rows_with_etf_evidence"] == 2
        assert payload["rows_with_smart_money_evidence"] == 4
        assert payload["source_contract_status"] == "STRICT_PIT_SOURCE_CONTRACT_READY"
        enriched = pd.read_csv(out / "candidate_replay_book_sec_enriched.csv")
        aapl_before = enriched[(enriched["ticker"] == "AAPL") & (enriched["rebalance_date"] == "2026-05-12")].iloc[0]
        aapl_after = enriched[(enriched["ticker"] == "AAPL") & (enriched["rebalance_date"] == "2026-05-13")].iloc[0]
        aapl_after_13f = enriched[(enriched["ticker"] == "AAPL") & (enriched["rebalance_date"] == "2026-05-15")].iloc[0]
        msft_after = enriched[(enriched["ticker"] == "MSFT") & (enriched["rebalance_date"] == "2026-05-13")].iloc[0]
        msft_next_session = enriched[(enriched["ticker"] == "MSFT") & (enriched["rebalance_date"] == "2026-05-15")].iloc[0]
        assert float(aapl_before["early_evidence_score"]) == 0.0
        assert float(aapl_after["early_evidence_score"]) > 0.0
        assert float(aapl_after["evidence_confidence_score"]) > 0.0
        assert float(aapl_after["institutional_evidence_score"]) > 0.0
        assert float(aapl_after_13f["institutional_evidence_score"]) > 0.0
        assert float(aapl_after_13f["etf_holdings_score"]) > 0.0
        assert float(aapl_after_13f["smart_money_shadow_score"]) > 0.0
        assert float(aapl_after_13f["evidence_fusion_score"]) > 0.0
        assert float(aapl_after_13f["smart_money_evidence_source_count"]) >= 2.0
        assert float(aapl_after_13f["sec_13f_value_delta_usd"]) != float(aapl_after["sec_13f_value_delta_usd"])
        assert float(aapl_after_13f["sec_combined_evidence_score"]) >= float(aapl_after["early_evidence_score"]) * 0.45
        assert "leader_onset_sec_v3_score" in enriched.columns
        assert "smart_money_shadow_score" in enriched.columns
        assert float(msft_after["early_evidence_score"]) == 0.0
        assert float(msft_next_session["early_evidence_score"]) > 0.0
        assert list(enriched["score_total"]) == [1.23, 2.34, 1.23, 2.34, 1.23, 2.34]
        assert "leader_onset_sec_v2_score" in enriched.columns
        assert "period_forward_return" in enriched.columns
        summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        assert summary["columns_added"]
        source_manifest = json.loads(
            (out / "source_manifest.json").read_text(encoding="utf-8")
        )
        assert source_manifest["strict_source_contract"] is True
        assert source_manifest["availability_policy"] == (
            "actual_scheduled_nyse_close_including_half_days"
        )
        assert summary["candidate_book_sha256"] == source_manifest["sources"]["candidate_book"]["sha256"]
        assert summary["output_csv_sha256"] == source_manifest["output"]["sha256"]
        assert (out / "report.md").exists()


def test_strict_contract_rejects_missing_candidate_provenance() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        candidate = root / "candidate.csv"
        form4 = root / "form4.parquet"
        holdings_13f = root / "13f.parquet"
        etf_holdings = root / "etf.parquet"
        output = root / "output"
        pd.DataFrame(
            [{"rebalance_date": "2026-05-13", "ticker": "AAPL"}]
        ).to_csv(candidate, index=False)
        pd.DataFrame(_form4_rows()).to_parquet(form4, index=False)
        pd.DataFrame(_thirteen_f_rows()).to_parquet(holdings_13f, index=False)
        pd.DataFrame(_etf_rows()).to_parquet(etf_holdings, index=False)
        try:
            run(
                argparse.Namespace(
                    candidate_book=str(candidate),
                    form4=str(form4),
                    institutional_13f=str(holdings_13f),
                    etf_holdings=str(etf_holdings),
                    output_dir=str(output),
                    lookback_days=90,
                    institutional_lookback_days=210,
                    strict_source_contract=True,
                )
            )
        except RuntimeError as exc:
            assert "candidate_missing_columns" in str(exc)
        else:
            raise AssertionError("strict SEC source contract unexpectedly passed")
        assert not (output / "candidate_replay_book_sec_enriched.csv").exists()


if __name__ == "__main__":
    test_sec_candidate_enrichment_is_pit_and_research_only()
    test_strict_contract_rejects_missing_candidate_provenance()
    print("sec_candidate_enrichment_smoke: PASS")
