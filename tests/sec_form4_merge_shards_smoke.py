#!/usr/bin/env python3
"""Smoke test for merging SEC Form 4 shard outputs."""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_sec_form4_merge_shards import run  # noqa: E402


def test_merge_shards_dedupes_and_builds_signals() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pit_root = root / "data_pit" / "sec"
        shard0 = pit_root / "shards" / "shard_0_of_2"
        shard1 = pit_root / "shards" / "shard_1_of_2"
        shard0.mkdir(parents=True)
        shard1.mkdir(parents=True)
        filings = pd.DataFrame(
            [
                {
                    "ticker": "ABC",
                    "cik10": "123",
                    "accession_number": "0000000123-26-000001",
                    "form_type": "4",
                    "filing_date": "2026-05-01",
                    "accepted_at": "2026-05-01T21:00:00Z",
                    "available_from": "2026-05-02T09:00:00Z",
                }
            ]
        )
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
                    "transaction_date": "2026-04-30",
                    "filing_date": "2026-05-01",
                    "accepted_at": "2026-05-01T21:00:00Z",
                    "available_from": "2026-05-02T09:00:00Z",
                    "transaction_code": "P",
                    "transaction_shares": 1000.0,
                    "transaction_price": 10.0,
                    "transaction_value": 10000.0,
                    "security_title": "Common Stock",
                    "accession_number": "0000000123-26-000001",
                }
            ]
        )
        filings.to_parquet(shard0 / "sec_filings_index.parquet", index=False)
        filings.to_parquet(shard1 / "sec_filings_index.parquet", index=False)
        tx.to_parquet(shard0 / "form4_transactions.parquet", index=False)
        tx.to_parquet(shard1 / "form4_transactions.parquet", index=False)

        section16_filings = filings.copy()
        section16_tx = pd.DataFrame(
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
                    "reporting_owners_json": '[{"reporting_owner_cik":"0000000999","reporting_owner_name":"CEO","officer_title":"Chief Executive Officer","is_director":true,"is_officer":true,"is_ten_percent_owner":false,"is_other":false}]',
                    "form_type": "4",
                    "period_of_report": "2026-04-30",
                    "transaction_date": "2026-04-30",
                    "filing_date": "2026-05-01",
                    "accepted_at": "2026-05-01T21:00:00Z",
                    "available_from": "2026-05-02T09:00:00Z",
                    "transaction_code": "P",
                    "acquired_disposed_code": "A",
                    "transaction_shares": 200.0,
                    "transaction_price": 10.0,
                    "transaction_value": 2000.0,
                    "ownership_nature": "",
                    "direct_or_indirect": "D",
                    "shares_owned_after": 1200.0,
                    "is_derivative": False,
                    "security_title": "Common Stock",
                    "underlying_security_title": "",
                    "underlying_shares": None,
                    "conversion_or_exercise_price": None,
                    "equity_swap_involved": False,
                    "accession_number": "0000000123-26-000001",
                    "filing_url": "https://www.sec.gov/example.xml",
                }
            ]
        )
        section16_holdings = pd.DataFrame(
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
                    "reporting_owners_json": '[{"reporting_owner_cik":"0000000999","reporting_owner_name":"CEO","officer_title":"Chief Executive Officer","is_director":true,"is_officer":true,"is_ten_percent_owner":false,"is_other":false}]',
                    "form_type": "3",
                    "period_of_report": "2026-04-01",
                    "filing_date": "2026-04-01",
                    "accepted_at": "2026-04-01T20:00:00Z",
                    "available_from": "2026-04-01T20:00:00Z",
                    "ownership_nature": "",
                    "direct_or_indirect": "D",
                    "shares_owned": 1000.0,
                    "is_derivative": False,
                    "security_title": "Common Stock",
                    "underlying_security_title": "",
                    "underlying_shares": None,
                    "conversion_or_exercise_price": None,
                    "accession_number": "0000000123-26-000000",
                    "filing_url": "https://www.sec.gov/example3.xml",
                }
            ]
        )
        for shard in (shard0, shard1):
            section16_filings.to_parquet(shard / "section16_filings.parquet", index=False)
            section16_tx.to_parquet(shard / "section16_transactions.parquet", index=False)
            section16_holdings.to_parquet(shard / "section16_holdings.parquet", index=False)

        summary = run(
            argparse.Namespace(
                pit_root=str(pit_root),
                output_dir=str(root / "outputs" / "sec_ownership_signals"),
                as_of_dates_csv="",
                as_of_date_column="rebalance_date",
                window_days=90,
            )
        )
        assert summary["filing_rows"] == 1
        assert summary["transaction_rows"] == 1
        assert summary["signal_rows"] == 1
        assert summary["section16_filing_rows"] == 1
        assert summary["section16_transaction_rows"] == 1
        assert summary["section16_holding_rows"] == 1
        assert summary["section16_ownership_state_rows"] == 1
        canonical = pd.read_parquet(pit_root / "sec_ownership_signals.parquet")
        assert canonical.iloc[0]["ticker"] == "ABC"
        assert canonical.iloc[0]["sec_form4_cluster_buy_score"] > 0
        state = pd.read_parquet(pit_root / "section16_ownership_state.parquet")
        assert state.iloc[0]["reporting_owner_cik"] == "0000000999"
        assert state.iloc[0]["shares_owned"] == 1200.0
        assert state.iloc[0]["state_source"] == "transaction"


if __name__ == "__main__":
    test_merge_shards_dedupes_and_builds_signals()
    print("sec_form4_merge_shards_smoke: PASS")
