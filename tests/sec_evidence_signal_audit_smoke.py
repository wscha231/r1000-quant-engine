#!/usr/bin/env python3
"""Smoke checks for SEC evidence signal audit outputs."""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_sec_evidence_signal_audit import run  # noqa: E402


def candidate_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for dt in ["2026-05-13", "2026-05-16"]:
        rows.extend(
            [
                {
                    "rebalance_date": dt,
                    "ticker": "AAPL",
                    "Name": "Apple Inc.",
                    "score_total": 1.0,
                    "portfolio_future_winner_engine_score": 0.90,
                    "selection_market_confirmation_score": 0.80,
                    "industry_group_strength_score": 0.70,
                    "rs_acceleration_score": 0.60,
                    "entry_quality_score": 0.50,
                    "market_cap_live": 3_000_000_000_000.0,
                    "period_forward_return": 0.14,
                },
                {
                    "rebalance_date": dt,
                    "ticker": "MSFT",
                    "Name": "Microsoft Corporation",
                    "score_total": 0.8,
                    "portfolio_future_winner_engine_score": 0.40,
                    "selection_market_confirmation_score": 0.30,
                    "industry_group_strength_score": 0.30,
                    "rs_acceleration_score": 0.20,
                    "entry_quality_score": 0.20,
                    "market_cap_live": 2_500_000_000_000.0,
                    "period_forward_return": -0.02,
                },
            ]
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
            "accession_number": "0000320193-26-000001",
        },
        {
            "issuer_ticker": "MSFT",
            "issuer_cik10": "0000789019",
            "reporting_owner_cik": "0002222222",
            "reporting_owner_name": "Example Seller",
            "officer_title": "Director",
            "is_director": True,
            "is_officer": False,
            "is_ten_percent_owner": False,
            "transaction_date": "2026-05-10",
            "filing_date": "2026-05-12",
            "accepted_at": "2026-05-13T00:00:00+00:00",
            "available_from": "2026-05-13T00:00:00+00:00",
            "transaction_code": "S",
            "transaction_shares": 100.0,
            "transaction_price": 200.0,
            "transaction_value": 20000.0,
            "accession_number": "0000789019-26-000001",
        },
    ]


def thirteen_f_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for manager_cik, manager_name, ticker, issuer, shares, value in [
        ("0000000001", "Good Manager", "AAPL", "APPLE INC", 200000.0, 20_000_000.0),
        ("0000000002", "Weak Manager", "MSFT", "MICROSOFT CORP", 100000.0, 10_000_000.0),
    ]:
        rows.append(
            {
                "manager_cik": manager_cik,
                "manager_name": manager_name,
                "report_period": "2025-12-31",
                "filing_date": "2026-02-14",
                "accepted_at": "2026-02-14T18:00:00+00:00",
                "available_from": "2026-02-14T18:00:00+00:00",
                "cusip": ticker,
                "issuer_name": issuer,
                "ticker_mapped": ticker,
                "shares": shares / 2,
                "market_value_usd": value / 2,
                "source_accession": f"{manager_cik}-26-000001",
            }
        )
        rows.append(
            {
                "manager_cik": manager_cik,
                "manager_name": manager_name,
                "report_period": "2026-03-31",
                "filing_date": "2026-05-15",
                "accepted_at": "2026-05-15T18:00:00+00:00",
                "available_from": "2026-05-15T18:00:00+00:00",
                "cusip": ticker,
                "issuer_name": issuer,
                "ticker_mapped": ticker,
                "shares": shares,
                "market_value_usd": value,
                "source_accession": f"{manager_cik}-26-000002",
            }
        )
    return rows


def test_sec_evidence_signal_audit_outputs_bucket_and_manager_reports() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        candidate = root / "candidate.csv"
        form4 = root / "form4.parquet"
        holdings = root / "13f.parquet"
        out = root / "audit"
        pd.DataFrame(candidate_rows()).to_csv(candidate, index=False)
        pd.DataFrame(form4_rows()).to_parquet(form4, index=False)
        pd.DataFrame(thirteen_f_rows()).to_parquet(holdings, index=False)

        payload = run(
            argparse.Namespace(
                candidate_book=str(candidate),
                form4=str(form4),
                institutional_13f=str(holdings),
                output_dir=str(out),
                form4_lookback_days=90,
                institutional_lookback_days=210,
                already_enriched=False,
                min_manager_observations=1,
                min_feature_nonzero_rows=1,
            )
        )

        assert payload["status"] == "completed"
        assert payload["research_only"] is True
        assert payload["production_activation_allowed"] is False
        assert payload["rows_with_form4_evidence"] > 0
        assert payload["rows_with_13f_evidence"] > 0
        form4_perf = pd.read_csv(out / "form4_buy_sell_performance.csv")
        assert "buy_only" in set(form4_perf["bucket"])
        managers = pd.read_csv(out / "13f_manager_alpha.csv")
        assert "Good Manager" in set(managers["manager_name"])
        good = managers[managers["manager_name"] == "Good Manager"].iloc[0]
        weak = managers[managers["manager_name"] == "Weak Manager"].iloc[0]
        assert float(good["manager_quality_score"]) > float(weak["manager_quality_score"])
        summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        assert summary["score_total_changed"] is False
        assert (out / "sec_score_feature_diagnostics.csv").exists()
        assert (out / "sec_score_policy_recommendation.json").exists()
        policy = json.loads((out / "sec_score_policy_recommendation.json").read_text(encoding="utf-8"))
        assert policy["research_only"] is True
        assert (out / "report.md").exists()


if __name__ == "__main__":
    test_sec_evidence_signal_audit_outputs_bucket_and_manager_reports()
    print("sec_evidence_signal_audit_smoke: PASS")
