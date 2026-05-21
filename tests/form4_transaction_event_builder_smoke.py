#!/usr/bin/env python3
"""Smoke tests for Form 4 transaction event construction."""
from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.run_form4_transaction_event_builder import build_form4_events, run  # noqa: E402


def sample_form4() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "issuer_ticker": "AAA",
                "issuer_cik10": "0000000001",
                "reporting_owner_cik": "0000000101",
                "reporting_owner_name": "Example CEO",
                "officer_title": "Chief Executive Officer",
                "is_director": True,
                "is_officer": True,
                "is_ten_percent_owner": False,
                "transaction_date": "2026-05-10",
                "filing_date": "2026-05-12",
                "accepted_at": "2026-05-12T21:30:00Z",
                "available_from": "2026-05-12T21:30:00Z",
                "transaction_code": "P",
                "transaction_shares": 10_000,
                "transaction_price": 20.0,
                "transaction_value": 200_000.0,
                "shares_owned_after": 50_000,
                "accession_number": "0000000001-26-000001",
            },
            {
                "issuer_ticker": "AAA",
                "issuer_cik10": "0000000001",
                "reporting_owner_cik": "0000000102",
                "reporting_owner_name": "Example CFO",
                "officer_title": "Chief Financial Officer",
                "is_director": False,
                "is_officer": True,
                "is_ten_percent_owner": False,
                "transaction_date": "2026-05-10",
                "filing_date": "2026-05-12",
                "accepted_at": "2026-05-12T22:00:00Z",
                "available_from": "2026-05-12T22:00:00Z",
                "transaction_code": "P",
                "transaction_shares": 8_000,
                "transaction_price": 20.0,
                "transaction_value": 160_000.0,
                "shares_owned_after": 25_000,
                "accession_number": "0000000001-26-000001",
            },
            {
                "issuer_ticker": "BBB",
                "issuer_cik10": "0000000002",
                "reporting_owner_cik": "0000000201",
                "reporting_owner_name": "Example Director",
                "officer_title": "",
                "is_director": True,
                "is_officer": False,
                "is_ten_percent_owner": False,
                "transaction_date": "2026-05-11",
                "filing_date": "2026-05-13",
                "accepted_at": "2026-05-13T21:30:00Z",
                "available_from": "2026-05-13T21:30:00Z",
                "transaction_code": "S",
                "transaction_shares": 5_000,
                "transaction_price": 30.0,
                "transaction_value": 150_000.0,
                "shares_owned_after": 10_000,
                "accession_number": "0000000002-26-000001",
            },
            {
                "issuer_ticker": "CCC",
                "issuer_cik10": "0000000003",
                "reporting_owner_cik": "0000000301",
                "reporting_owner_name": "Award Recipient",
                "officer_title": "Officer",
                "is_director": False,
                "is_officer": True,
                "is_ten_percent_owner": False,
                "transaction_date": "2026-05-13",
                "filing_date": "2026-05-14",
                "accepted_at": "2026-05-14T21:30:00Z",
                "available_from": "2026-05-14T21:30:00Z",
                "transaction_code": "A",
                "transaction_shares": 1_000,
                "transaction_price": 0.0,
                "transaction_value": 0.0,
                "accession_number": "0000000003-26-000001",
            },
        ]
    )


def test_form4_event_builder_classifies_purchases_sales_and_awards() -> None:
    metadata = pd.DataFrame(
        [
            {"ticker": "AAA", "market_cap": 100_000_000.0, "issuer_float": 10_000_000.0, "dollar_volume_20d": 8_000_000.0},
            {"ticker": "BBB", "market_cap": 200_000_000.0, "issuer_float": 20_000_000.0, "dollar_volume_20d": 20_000_000.0},
        ]
    )
    events = build_form4_events(sample_form4(), metadata)
    assert len(events) == 4
    buys = events[events["transaction_code"].eq("P")]
    sale = events[events["transaction_code"].eq("S")].iloc[0]
    award = events[events["transaction_code"].eq("A")].iloc[0]
    assert int(buys["same_filing_buy_count"].max()) == 2
    assert buys["post_disclosure_event_seed_score"].min() > 0
    assert sale["post_disclosure_event_seed_score"] < 0
    assert bool(award["is_signal_candidate"]) is False
    assert int(events["available_from"].isna().sum()) == 0
    assert bool(events["research_only"].all()) is True
    assert bool((~events["production_activation_allowed"]).all()) is True


def test_form4_event_builder_cli_outputs_summary() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        form4 = root / "data_pit" / "sec" / "form4_transactions.parquet"
        metadata = root / "scored_latest.csv"
        pit = root / "data_pit" / "sec" / "form4_transaction_events.parquet"
        out = root / "outputs" / "form4_transaction_events"
        form4.parent.mkdir(parents=True, exist_ok=True)
        sample_form4().to_parquet(form4, index=False)
        pd.DataFrame({"ticker": ["AAA"], "market_cap": [100_000_000.0], "issuer_float": [10_000_000.0]}).to_csv(metadata, index=False)
        payload = run(Namespace(form4=str(form4), metadata=str(metadata), pit_output=str(pit), output_dir=str(out)))
        assert payload["status"] == "completed", payload
        assert payload["p_code_buy_rows"] == 2
        assert payload["s_code_sale_rows"] == 1
        assert payload["available_from_before_accepted_at"] == 0
        saved = pd.read_parquet(pit)
        assert len(saved) == 4
        summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        assert summary["score_total_changed"] is False


if __name__ == "__main__":
    test_form4_event_builder_classifies_purchases_sales_and_awards()
    test_form4_event_builder_cli_outputs_summary()
    print("form4_transaction_event_builder_smoke: PASS")
