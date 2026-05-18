#!/usr/bin/env python3
"""Smoke test for merging SEC Form 4 shard outputs."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_sec_form4_merge_shards import run  # noqa: E402


class Args:
    pit_root = ""
    output_dir = ""
    as_of_dates_csv = ""
    as_of_date_column = "rebalance_date"
    window_days = 90


def test_merge_shards_dedupes_and_builds_signals() -> None:
    root = ROOT / "_tmp_sec_form4_merge_smoke"
    if root.exists():
        import shutil

        shutil.rmtree(root)
    shard0 = root / "data_pit" / "sec" / "shards" / "shard_0_of_2"
    shard1 = root / "data_pit" / "sec" / "shards" / "shard_1_of_2"
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
    args = Args()
    args.pit_root = str(root / "data_pit" / "sec")
    args.output_dir = str(root / "outputs" / "sec_ownership_signals")
    summary = run(args)
    assert summary["filing_rows"] == 1
    assert summary["transaction_rows"] == 1
    assert summary["signal_rows"] == 1
    canonical = pd.read_parquet(root / "data_pit" / "sec" / "sec_ownership_signals.parquet")
    assert canonical.iloc[0]["ticker"] == "ABC"
    assert canonical.iloc[0]["sec_form4_cluster_buy_score"] > 0
    import shutil

    shutil.rmtree(root)


def main() -> int:
    test_merge_shards_dedupes_and_builds_signals()
    print("sec_form4_merge_shards_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
