#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_run287_w4_form4_13f_source_screen import run  # noqa: E402


class Args:
    pass


def candidate_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for idx in range(80):
        is_oos = idx >= 40
        rebalance_date = "2025-01-31" if is_oos else "2023-01-31"
        ticker = "AAA" if idx % 2 == 0 else "BBB"
        rows.append(
            {
                "rebalance_date": rebalance_date,
                "ticker": ticker,
                "Name": f"{ticker} Corp",
                "sector": "Technology",
                "industry_group": "Semiconductors",
                "period_forward_return": 0.10 if ticker == "AAA" else -0.10,
            }
        )
    rows.append(
        {
            "rebalance_date": "2025-01-31",
            "ticker": "FUT",
            "Name": "Future Only Corp",
            "sector": "Technology",
            "industry_group": "Semiconductors",
            "period_forward_return": 0.30,
        }
    )
    return rows


def form4_rows() -> list[dict[str, object]]:
    return [
        {
            "issuer_ticker": "(AAA)",
            "issuer_cik10": "0000000001",
            "reporting_owner_cik": "0000000101",
            "reporting_owner_name": "AAA CEO",
            "officer_title": "Chief Executive Officer",
            "is_director": True,
            "is_officer": True,
            "is_ten_percent_owner": False,
            "transaction_date": "2022-12-15",
            "filing_date": "2022-12-16",
            "accepted_at": "2022-12-16T21:00:00Z",
            "available_from": "2022-12-16T21:00:00Z",
            "transaction_code": "P",
            "transaction_shares": 10_000,
            "transaction_price": 20.0,
            "transaction_value": 200_000.0,
            "shares_owned_after": 50_000,
            "accession_number": "aaa-2022",
        },
        {
            "issuer_ticker": "AAA",
            "issuer_cik10": "0000000001",
            "reporting_owner_cik": "0000000101",
            "reporting_owner_name": "AAA CEO",
            "officer_title": "Chief Executive Officer",
            "is_director": True,
            "is_officer": True,
            "is_ten_percent_owner": False,
            "transaction_date": "2024-12-15",
            "filing_date": "2024-12-16",
            "accepted_at": "2024-12-16T21:00:00Z",
            "available_from": "2024-12-16T21:00:00Z",
            "transaction_code": "P",
            "transaction_shares": 10_000,
            "transaction_price": 20.0,
            "transaction_value": 200_000.0,
            "shares_owned_after": 60_000,
            "accession_number": "aaa-2024",
        },
        {
            "issuer_ticker": "BBB",
            "issuer_cik10": "0000000002",
            "reporting_owner_cik": "0000000201",
            "reporting_owner_name": "BBB Director",
            "officer_title": "",
            "is_director": True,
            "is_officer": False,
            "is_ten_percent_owner": False,
            "transaction_date": "2024-12-15",
            "filing_date": "2024-12-16",
            "accepted_at": "2024-12-16T21:00:00Z",
            "available_from": "2024-12-16T21:00:00Z",
            "transaction_code": "S",
            "transaction_shares": 10_000,
            "transaction_price": 20.0,
            "transaction_value": 200_000.0,
            "shares_owned_after": 40_000,
            "accession_number": "bbb-2024",
        },
        {
            "issuer_ticker": "FUT",
            "issuer_cik10": "0000000003",
            "reporting_owner_cik": "0000000301",
            "reporting_owner_name": "Future CEO",
            "officer_title": "Chief Executive Officer",
            "is_director": True,
            "is_officer": True,
            "is_ten_percent_owner": False,
            "transaction_date": "2025-02-01",
            "filing_date": "2025-02-02",
            "accepted_at": "2025-02-02T21:00:00Z",
            "available_from": "2025-02-02T21:00:00Z",
            "transaction_code": "P",
            "transaction_shares": 10_000,
            "transaction_price": 20.0,
            "transaction_value": 200_000.0,
            "shares_owned_after": 40_000,
            "accession_number": "future-after-rebalance",
        },
    ]


def holdings_rows() -> list[dict[str, object]]:
    return [
        {
            "manager_cik": "0000100000",
            "manager_name": "Example Manager",
            "report_period": "2022-09-30",
            "filing_date": "2022-11-14",
            "accepted_at": "2022-11-14T21:00:00Z",
            "available_from": "2022-11-14T21:00:00Z",
            "ticker_mapped": "AAA",
            "shares": 100_000,
            "market_value_usd": 1_000_000,
        },
        {
            "manager_cik": "0000100000",
            "manager_name": "Example Manager",
            "report_period": "2022-12-31",
            "filing_date": "2023-01-15",
            "accepted_at": "2023-01-15T21:00:00Z",
            "available_from": "2023-01-15T21:00:00Z",
            "ticker_mapped": "AAA",
            "shares": 150_000,
            "market_value_usd": 1_800_000,
        },
        {
            "manager_cik": "0000100000",
            "manager_name": "Example Manager",
            "report_period": "2024-09-30",
            "filing_date": "2024-11-14",
            "accepted_at": "2024-11-14T21:00:00Z",
            "available_from": "2024-11-14T21:00:00Z",
            "ticker_mapped": "AAA",
            "shares": 160_000,
            "market_value_usd": 1_900_000,
        },
        {
            "manager_cik": "0000100000",
            "manager_name": "Example Manager",
            "report_period": "2024-12-31",
            "filing_date": "2025-01-15",
            "accepted_at": "2025-01-15T21:00:00Z",
            "available_from": "2025-01-15T21:00:00Z",
            "ticker_mapped": "AAA",
            "shares": 220_000,
            "market_value_usd": 3_000_000,
        },
        {
            "manager_cik": "0000100000",
            "manager_name": "Example Manager",
            "report_period": "2024-09-30",
            "filing_date": "2024-11-14",
            "accepted_at": "2024-11-14T21:00:00Z",
            "available_from": "2024-11-14T21:00:00Z",
            "ticker_mapped": "BBB",
            "shares": 100_000,
            "market_value_usd": 1_000_000,
        },
        {
            "manager_cik": "0000100000",
            "manager_name": "Example Manager",
            "report_period": "2024-12-31",
            "filing_date": "2025-01-15",
            "accepted_at": "2025-01-15T21:00:00Z",
            "available_from": "2025-01-15T21:00:00Z",
            "ticker_mapped": "BBB",
            "shares": 25_000,
            "market_value_usd": 200_000,
        },
        {
            "manager_cik": "0000100000",
            "manager_name": "Example Manager",
            "report_period": "2024-12-31",
            "filing_date": "2025-02-15",
            "accepted_at": "2025-02-15T21:00:00Z",
            "available_from": "2025-02-15T21:00:00Z",
            "ticker_mapped": "FUT",
            "shares": 500_000,
            "market_value_usd": 9_000_000,
        },
    ]


def test_w4_form4_13f_source_screen_is_research_only_and_pit_safe() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        candidate = root / "candidate.csv"
        form4 = root / "form4.parquet"
        sec13f = root / "13f.parquet"
        managers = root / "missing_managers.csv"
        out = root / "out"
        pd.DataFrame(candidate_rows()).to_csv(candidate, index=False)
        pd.DataFrame(form4_rows()).to_parquet(form4, index=False)
        pd.DataFrame(holdings_rows()).to_parquet(sec13f, index=False)

        args = Args()
        args.input = str(candidate)
        args.form4_path = str(form4)
        args.sec13f_path = str(sec13f)
        args.manager_universe = str(managers)
        args.output_dir = str(out)
        args.oos_start = "2024-07-01"
        args.min_rows = 5
        args.min_oos_high_count = 2
        args.sample_rows = 50
        payload = run(args)

        assert payload["status"] == "completed"
        assert payload["research_only"] is True
        assert payload["candidate_allowed"] is False
        assert payload["fullrun_dispatched"] is False
        assert payload["new_alpha_hook_added"] is False
        assert payload["threshold_tuning_performed"] is False
        assert payload["used_forward_return_in_ranking"] is False
        assert payload["forward_returns_audit_only"] is True
        assert payload["production_promotion_allowed"] is False
        assert payload["live_trading_enabled"] is False
        assert payload["same_day_disclosure_policy"] == "excluded_no_intraday_rebalance_contract"
        assert "w4_combined_score" in [item["signal"] for item in payload["signal_summaries"]]

        sample = pd.read_csv(out / "enriched_candidate_sample.csv")
        assert "w4_combined_score" in sample.columns
        future = sample[sample["ticker"].eq("FUT")]
        assert future.empty, "post-rebalance FUT disclosure must not leak into 2025-01-31 row"
        assert (out / "summary.json").exists()
        assert (out / "signal_stats.csv").exists()
        assert (out / "report.md").exists()


def main() -> int:
    test_w4_form4_13f_source_screen_is_research_only_and_pit_safe()
    print("run287_w4_form4_13f_source_screen_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
