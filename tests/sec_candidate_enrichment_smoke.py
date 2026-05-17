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
    for dt in ["2026-05-12", "2026-05-13"]:
        rows.extend(
            [
                {
                    "rebalance_date": dt,
                    "ticker": "AAPL",
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
                    "ticker": "MSFT",
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
        }
    ]


def test_sec_candidate_enrichment_is_pit_and_research_only() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        candidate = root / "candidate_replay_book.csv"
        form4 = root / "form4_transactions.parquet"
        out = root / "sec_enriched"
        pd.DataFrame(_candidate_rows()).to_csv(candidate, index=False)
        pd.DataFrame(_form4_rows()).to_parquet(form4, index=False)

        payload = run(
            argparse.Namespace(
                candidate_book=str(candidate),
                form4=str(form4),
                output_dir=str(out),
                lookback_days=90,
            )
        )

        assert payload["research_only"] is True
        assert payload["production_activation_allowed"] is False
        assert payload["score_total_changed"] is False
        assert payload["rows_with_sec_evidence"] == 1
        enriched = pd.read_csv(out / "candidate_replay_book_sec_enriched.csv")
        aapl_before = enriched[(enriched["ticker"] == "AAPL") & (enriched["rebalance_date"] == "2026-05-12")].iloc[0]
        aapl_after = enriched[(enriched["ticker"] == "AAPL") & (enriched["rebalance_date"] == "2026-05-13")].iloc[0]
        msft_after = enriched[(enriched["ticker"] == "MSFT") & (enriched["rebalance_date"] == "2026-05-13")].iloc[0]
        assert float(aapl_before["early_evidence_score"]) == 0.0
        assert float(aapl_after["early_evidence_score"]) > 0.0
        assert float(aapl_after["evidence_confidence_score"]) > 0.0
        assert float(msft_after["early_evidence_score"]) == 0.0
        assert list(enriched["score_total"]) == [1.23, 2.34, 1.23, 2.34]
        assert "leader_onset_sec_v2_score" in enriched.columns
        assert "period_forward_return" in enriched.columns
        summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        assert summary["columns_added"]
        assert (out / "report.md").exists()


if __name__ == "__main__":
    test_sec_candidate_enrichment_is_pit_and_research_only()
    print("sec_candidate_enrichment_smoke: PASS")
