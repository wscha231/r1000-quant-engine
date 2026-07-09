#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.collect_earnings_estimates_finnhub import main, parse_snapshot_row  # noqa: E402


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


if __name__ == "__main__":
    test_parse_snapshot_stamps_fetch_date_not_fiscal_period()
    test_cli_fixture_writes_snapshot_and_signals()
    print("collect_earnings_estimates_smoke: PASS")
