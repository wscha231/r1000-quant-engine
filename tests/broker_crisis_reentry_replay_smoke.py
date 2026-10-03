#!/usr/bin/env python3
"""Smoke test broker-ledger conversion of crisis re-entry target books."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from tools.run_broker_crisis_reentry_replay import run  # noqa: E402
from tools.run_broker_crisis_reentry_replay import render_report  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def _write_price(cache: Path, ticker: str, prices: list[float]) -> None:
    dates = pd.bdate_range("2026-01-01", periods=len(prices))
    frame = pd.DataFrame({"Close": prices, "Adj Close": prices, "Open": prices}, index=dates)
    frame.to_parquet(cache / px_cache_name(ticker))


class BlockedCrisisReportChecks(unittest.TestCase):
    def test_blocked_unknown_or_redacted_status_never_formats_stale_values(self):
        metrics = {"cagr": .1, "sharpe": 1.2, "max_dd": -.05, "avg_cash_weight": .1, "trade_count": 2}
        cases = [{**metrics, "status": status} for status in ("blocked", None, "unknown")]
        cases += [{**metrics, "status": "completed", "metric_mode": "DO_NOT_USE"},
                  {**metrics, "status": "completed", "performance_fields_redacted": True}]
        for data in cases:
            with self.subTest(data=data):
                report = render_report(data)
                self.assertEqual(report.count("N/A"), 5)
                self.assertNotIn("10.00%", report)
                self.assertNotIn("0.00%", report)

    def test_missing_or_nonfinite_report_values_are_unavailable_and_zero_is_valid(self):
        fields = ("cagr", "sharpe", "max_dd", "avg_cash_weight", "trade_count")
        for field in fields:
            for value in (None, True, float("nan"), float("inf")):
                with self.subTest(field=field, value=value):
                    report = render_report({"status": "completed", **dict.fromkeys(fields, 0.), field: value})
                    self.assertIn("N/A", report)
        report = render_report({"status": "completed", **dict.fromkeys(fields, 0.)})
        self.assertNotIn("N/A", report)
        self.assertIn("0.00%", report)


def main() -> int:
    with TemporaryDirectory() as td:
        root = Path(td)
        latest = root / "latest"
        crisis = latest / "crisis_reentry_replay"
        crisis.mkdir(parents=True)
        pd.DataFrame(
            [
                {"policy_id": "fast_reentry", "rebalance_date": "2026-01-01", "ticker": "AAA", "weight": 0.70},
                {"policy_id": "fast_reentry", "rebalance_date": "2026-01-01", "ticker": "CASH", "weight": 0.30},
                {"policy_id": "fast_reentry", "rebalance_date": "2026-01-08", "ticker": "AAA", "weight": 0.90},
                {"policy_id": "fast_reentry", "rebalance_date": "2026-01-08", "ticker": "CASH", "weight": 0.10},
                {"policy_id": "other", "rebalance_date": "2026-01-01", "ticker": "BBB", "weight": 1.00},
            ]
        ).to_csv(crisis / "holdings.csv", index=False)

        cache = root / "cache_prices"
        cache.mkdir()
        _write_price(cache, "AAA", [100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111])

        out = root / "out"
        metrics = run(
            latest_run=latest,
            price_cache=cache,
            output_dir=out,
            policy_id="fast_reentry",
            cost_bps=0.0,
        )
        assert metrics["status"] == "completed", metrics
        assert metrics["metric_mode"] == "broker_ledger_next_close", metrics
        assert metrics["candidate_id"] == "main_broker_crisis_reentry_fast_reentry", metrics
        assert metrics["target_book_months"] == 2, metrics
        target = pd.read_csv(out / "target_book.csv")
        assert set(target["policy_id"]) == {"fast_reentry"}
        assert (out / "trades.csv").exists()
        assert (out / "equity_curve.csv").exists()
    if not unittest.TextTestRunner(verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(BlockedCrisisReportChecks)).wasSuccessful():
        return 1
    print("broker_crisis_reentry_replay_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
