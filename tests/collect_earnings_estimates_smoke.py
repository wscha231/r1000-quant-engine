#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.collect_earnings_estimates_finnhub import (  # noqa: E402
    alphavantage_to_payloads,
    clean_vendor_order,
    fmp_to_payloads,
    main,
    parse_snapshot_row,
    sanitize_error_message,
    vendor_estimate_access_from_errors,
)
import tools.collect_earnings_estimates_finnhub as collector  # noqa: E402


def _write_fixture(root: Path, ticker: str = "AAA") -> None:
    (root / f"{ticker}_eps.json").write_text(
        json.dumps(
            {
                "data": [
                    {"period": "2026", "avg": 1.20, "high": 1.35, "low": 1.05, "numberAnalysts": 8},
                    {"period": "2027", "avg": 1.45, "high": 1.60, "low": 1.20, "numberAnalysts": 7},
                ]
            }
        ),
        encoding="utf-8",
    )
    (root / f"{ticker}_revenue.json").write_text(
        json.dumps({"data": [{"period": "2026", "avg": 1200.0, "numberAnalysts": 6}]}),
        encoding="utf-8",
    )
    (root / f"{ticker}_earnings.json").write_text(
        json.dumps(
            [
                {"period": "2026-03-31", "actual": 0.31, "estimate": 0.28, "surprisePercent": 10.7},
                {"period": "2026-06-30", "actual": 0.34, "estimate": 0.32, "surprisePercent": 6.2},
            ]
        ),
        encoding="utf-8",
    )
    (root / f"{ticker}_recommendation.json").write_text(
        json.dumps([{"period": "2026-07-01", "strongBuy": 4, "buy": 5, "hold": 3, "sell": 1, "strongSell": 0}]),
        encoding="utf-8",
    )


def test_parse_snapshot_stamps_fetch_date_not_fiscal_period() -> None:
    row = parse_snapshot_row(
        "AAA",
        fetch_date=pd.Timestamp("2026-07-09"),
        eps_payload={"data": [{"period": "2027", "avg": 1.45, "high": 1.6, "low": 1.2}]},
        revenue_payload={"data": [{"period": "2027", "avg": 1500.0}]},
        earnings_payload=[{"period": "2026-06-30", "actual": 0.34, "estimate": 0.32, "surprisePercent": 6.2}],
        recommendation_payload=[{"period": "2026-07-01", "strongBuy": 3, "buy": 4, "sell": 1, "strongSell": 0}],
    )
    assert row["as_of_date"] == "2026-07-09"
    assert row["available_from"] == "2026-07-09"
    assert row["actual_report_date"] == "2026-06-30"
    assert row["available_from"] != row["actual_report_date"]
    assert row["est_eps_fy1"] == 1.45
    assert row["est_eps_revision_breadth"] > 0
    assert row["vendor_estimate_access"] is True


def test_vendor_entitlement_errors_are_redacted_and_blocking() -> None:
    raw = "403 Client Error: Forbidden for url: https://finnhub.io/api/v1/stock/eps-estimate?symbol=AAPL&token=secret-key"
    clean = sanitize_error_message(raw)
    assert "secret-key" not in clean
    assert "token=***" in clean
    av_clean = sanitize_error_message("https://www.alphavantage.co/query?function=EARNINGS_ESTIMATES&symbol=AAPL&apikey=alpha-secret")
    assert "alpha-secret" not in av_clean
    assert "apikey=***" in av_clean
    av_body_clean = sanitize_error_message(
        "We have detected your API key as ABC123XYZ and our standard API rate limit is 25 requests per day."
    )
    assert "ABC123XYZ" not in av_body_clean
    assert "API key as ***" in av_body_clean
    errors = [
        {
            "ticker": "AAPL",
            "endpoint": "/stock/eps-estimate",
            "status_code": 403,
            "vendor_entitlement_blocked": True,
            "error": clean,
        }
    ]
    assert vendor_estimate_access_from_errors(errors) is False
    row = parse_snapshot_row(
        "AAPL",
        fetch_date=pd.Timestamp("2026-07-09"),
        eps_payload={},
        revenue_payload={},
        earnings_payload=[],
        recommendation_payload=[],
        eps_estimate_access=False,
        revenue_estimate_access=False,
    )
    assert row["vendor_estimate_access"] is False
    assert row["has_forward_estimate"] == 0


def test_free_vendor_payloads_normalize_to_internal_schema() -> None:
    av_eps, av_rev = alphavantage_to_payloads(
        {
            "annualEarningsEstimates": [
                {
                    "fiscalDateEnding": "2026-12-31",
                    "epsEstimateAverage": "4.20",
                    "epsEstimateHigh": "4.50",
                    "epsEstimateLow": "3.90",
                    "epsEstimateAnalystCount": "12",
                    "revenueEstimateAverage": "1000000000",
                },
                {
                    "fiscalDateEnding": "2027-12-31",
                    "epsEstimateAverage": "5.00",
                    "revenueEstimateAverage": "1200000000",
                },
            ]
        }
    )
    assert av_eps["data"][0]["avg"] == "4.20"
    assert av_rev["data"][0]["avg"] == "1000000000"
    fmp_eps, fmp_rev = fmp_to_payloads(
        [
            {
                "date": "2026-12-31",
                "estimatedEpsAvg": 4.3,
                "estimatedEpsHigh": 4.8,
                "estimatedEpsLow": 3.8,
                "numberAnalystsEstimatedEps": 11,
                "estimatedRevenueAvg": 1010000000,
            }
        ]
    )
    assert fmp_eps["data"][0]["avg"] == 4.3
    assert fmp_rev["data"][0]["avg"] == 1010000000
    assert clean_vendor_order("av,financialmodelingprep,finnhub,alpha") == ["alphavantage", "fmp", "finnhub"]


def test_cli_fixture_writes_snapshot_and_signals() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        fixture = root / "fixture"
        fixture.mkdir()
        _write_fixture(fixture)
        snapshot_dir = root / "snapshots"
        signals = root / "signals.parquet"
        summary = root / "summary.json"
        old_argv = sys.argv[:]
        try:
            sys.argv = [
                "collect_earnings_estimates_finnhub.py",
                "--tickers",
                "AAA",
                "--fixture-dir",
                str(fixture),
                "--fetch-date",
                "2026-07-09",
                "--snapshot-dir",
                str(snapshot_dir),
                "--signals-output",
                str(signals),
                "--summary",
                str(summary),
            ]
            assert main() == 0
        finally:
            sys.argv = old_argv
        assert (snapshot_dir / "estimates_20260709.parquet").exists()
        assert signals.exists()
        payload = json.loads(summary.read_text(encoding="utf-8"))
        assert payload["forward_only"] is True
        assert payload["backtest_acceptance_allowed"] is False
        sig = pd.read_parquet(signals)
        assert sig["available_from"].dt.strftime("%Y-%m-%d").iloc[0] == "2026-07-09"


def test_partial_free_vendor_success_is_not_global_block() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        def fake_collect_live_snapshot(*_: Any, **__: Any) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
            rows = []
            for ticker, has_estimate in [("AAA", 1), ("BBB", 1), ("CCC", 1), ("DDD", 1), ("EEE", 0)]:
                rows.append(
                    {
                        "ticker": ticker,
                        "as_of_date": "2026-07-09",
                        "available_from": "2026-07-09",
                        "fetch_source": "fmp" if has_estimate else "finnhub",
                        "est_eps_fy1": 1.0 if has_estimate else 0.0,
                        "est_eps_fy2": 1.1 if has_estimate else 0.0,
                        "est_rev_fy1": 100.0 if has_estimate else 0.0,
                        "est_dispersion": 0.1,
                        "earnings_surprise_last": 0.0,
                        "est_eps_revision_breadth": 0.0,
                        "surprise_streak": 0,
                        "has_forward_estimate": has_estimate,
                        "vendor_estimate_access": bool(has_estimate),
                    }
                )
            return pd.DataFrame(rows), [
                {
                    "ticker": "EEE",
                    "vendor": "fmp",
                    "endpoint": "/stable/analyst-estimates",
                    "status_code": 402,
                    "vendor_entitlement_blocked": True,
                    "error": "402 Client Error: Payment Required for url: https://financialmodelingprep.com/stable/analyst-estimates?symbol=EEE&apikey=***",
                }
            ]

        old_collect = collector.collect_live_snapshot
        old_argv = sys.argv[:]
        try:
            collector.collect_live_snapshot = fake_collect_live_snapshot
            sys.argv = [
                "collect_earnings_estimates_finnhub.py",
                "--tickers",
                "AAA,BBB,CCC,DDD,EEE",
                "--api-key",
                "dummy",
                "--snapshot-dir",
                str(root / "snapshots"),
                "--signals-output",
                str(root / "signals.parquet"),
                "--summary",
                str(root / "summary.json"),
            ]
            assert collector.main() == 0
        finally:
            collector.collect_live_snapshot = old_collect
            sys.argv = old_argv
        payload = json.loads((root / "summary.json").read_text(encoding="utf-8"))
        assert payload["status"] == "completed", payload
        assert payload["reason"] == "partial_vendor_errors_warn_only", payload
        assert payload["has_forward_estimate_rows"] == 4, payload
        assert payload["estimate_coverage_ratio"] == 0.8, payload
        assert payload["vendor_estimate_access"] is True, payload
        assert payload["vendor_blocked_errors"] is True, payload


if __name__ == "__main__":
    test_parse_snapshot_stamps_fetch_date_not_fiscal_period()
    test_vendor_entitlement_errors_are_redacted_and_blocking()
    test_free_vendor_payloads_normalize_to_internal_schema()
    test_cli_fixture_writes_snapshot_and_signals()
    test_partial_free_vendor_success_is_not_global_block()
    print("collect_earnings_estimates_smoke: PASS")
