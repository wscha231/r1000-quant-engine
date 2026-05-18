#!/usr/bin/env python3
"""Smoke checks for SEC evidence learning pipeline orchestration."""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_sec_evidence_learning_pipeline import run  # noqa: E402


def candidate_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    dates = ["2026-05-12", "2026-05-13", "2026-05-16"]
    for dt in dates:
        for i in range(30):
            ticker = "AAPL" if i == 0 else f"T{i:02d}"
            base = 1.0 - i / 40.0
            rows.append(
                {
                    "rebalance_date": dt,
                    "ticker": ticker,
                    "Name": "Apple Inc." if ticker == "AAPL" else f"Ticker {i}",
                    "score_total": base,
                    "portfolio_future_winner_engine_score": base,
                    "selection_market_confirmation_score": base * 0.8,
                    "industry_group_strength_score": base * 0.7,
                    "rs_acceleration_score": base * 0.6,
                    "entry_quality_score": base * 0.5,
                    "market_cap_live": 3_000_000_000_000.0 if ticker == "AAPL" else 10_000_000_000.0,
                    "period_forward_return": 0.18 if ticker == "AAPL" else (0.06 - i * 0.002),
                }
            )
    return rows


def form4_rows() -> list[dict[str, object]]:
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


def thirteen_f_rows() -> list[dict[str, object]]:
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
            "ticker_mapped": "AAPL",
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
            "ticker_mapped": "AAPL",
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


def test_sec_evidence_learning_pipeline_outputs_research_artifacts() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        candidate = root / "candidate.csv"
        form4 = root / "form4.parquet"
        holdings_13f = root / "13f.parquet"
        out = root / "learning"
        pd.DataFrame(candidate_rows()).to_csv(candidate, index=False)
        pd.DataFrame(form4_rows()).to_parquet(form4, index=False)
        pd.DataFrame(thirteen_f_rows()).to_parquet(holdings_13f, index=False)

        payload = run(
            argparse.Namespace(
                candidate_book=str(candidate),
                form4=str(form4),
                institutional_13f=str(holdings_13f),
                price_cache=str(root / "cache_prices"),
                output_dir=str(out),
                form4_lookback_days=90,
                institutional_lookback_days=210,
                top_n=5,
                run_broker_grid=False,
                starting_capital=100000.0,
                fill_mode="next_close",
                cost_bps=25.0,
                max_fill_lag_days=7,
                styles="sec_evidence_shadow,sec_support_overlay",
                target_ns="1",
                single_name_caps="1.0",
                max_variants=1,
                min_market_cap_usd=0.0,
                min_dollar_volume_usd=0.0,
                min_price=0.0,
                main_target_ns="",
                main_single_name_caps="",
                concentrated_target_ns="",
                concentrated_single_name_caps="",
                min_manager_observations=1,
                allow_unfillable_targets=True,
            )
        )

        assert payload["status"] == "completed"
        assert payload["research_only"] is True
        assert payload["production_activation_allowed"] is False
        assert payload["enriched_rows"] == 90
        assert payload["rows_with_form4_evidence"] > 0
        assert payload["rows_with_13f_evidence"] > 0
        assert payload["score_learning"]["status"] == "completed"
        enriched = pd.read_csv(out / "candidate_replay_book_sec_enriched.csv")
        assert "leader_onset_sec_v3_score" in enriched.columns
        assert "leader_onset_sec_v4_support_score" in enriched.columns
        assert "score_total" in enriched.columns
        assert json.loads((out / "summary.json").read_text(encoding="utf-8"))["promotion_allowed"] is False
        assert (out / "score_weight_grid.csv").exists()
        assert (out / "signal_audit" / "13f_manager_alpha.csv").exists()
        assert (out / "selection_quality" / "selection_quality_summary.json").exists()


if __name__ == "__main__":
    test_sec_evidence_learning_pipeline_outputs_research_artifacts()
    print("sec_evidence_learning_pipeline_smoke: PASS")
