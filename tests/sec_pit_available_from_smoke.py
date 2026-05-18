#!/usr/bin/env python3
"""Smoke tests for SEC PIT availability and ownership signals."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_sec_ownership_signals import build_form4_signals  # noqa: E402


def sample_transactions() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "issuer_ticker": "INTC",
                "issuer_cik10": "0000050863",
                "reporting_owner_cik": "0001111111",
                "reporting_owner_name": "CEO Buyer",
                "officer_title": "Chief Executive Officer",
                "is_director": True,
                "is_officer": True,
                "is_ten_percent_owner": False,
                "transaction_date": "2026-05-01",
                "filing_date": "2026-05-03",
                "accepted_at": "2026-05-03T22:00:00.000Z",
                "available_from": "2026-05-04T10:00:00+00:00",
                "transaction_code": "P",
                "transaction_shares": 10000,
                "transaction_price": 30.0,
                "transaction_value": 300000.0,
            },
            {
                "issuer_ticker": "INTC",
                "issuer_cik10": "0000050863",
                "reporting_owner_cik": "0002222222",
                "reporting_owner_name": "Grant Noise",
                "officer_title": "Director",
                "is_director": True,
                "is_officer": False,
                "is_ten_percent_owner": False,
                "transaction_date": "2026-05-01",
                "filing_date": "2026-05-03",
                "accepted_at": "2026-05-03T22:01:00.000Z",
                "available_from": "2026-05-04T10:01:00+00:00",
                "transaction_code": "A",
                "transaction_shares": 50000,
                "transaction_price": 0.0,
                "transaction_value": 0.0,
            },
        ]
    )


def test_available_from_blocks_transaction_date_lookahead() -> None:
    tx = sample_transactions()
    before = build_form4_signals(tx, as_of=pd.Timestamp("2026-05-03T23:00:00Z"))
    assert before.empty
    after = build_form4_signals(tx, as_of=pd.Timestamp("2026-05-04T12:00:00Z"))
    assert len(after) == 1
    row = after.iloc[0]
    assert row["ticker"] == "INTC"
    assert row["form4_open_market_buy_count"] == 1
    assert row["sec_form4_cluster_buy_score"] > 0
    assert row["sec_form4_ceo_cfo_buy_score"] > 0
    assert row["early_evidence_score"] > 0


def main() -> int:
    test_available_from_blocks_transaction_date_lookahead()
    print("sec_pit_available_from_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

