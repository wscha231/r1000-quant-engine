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

import tools.r1000_live_extension as live_extension
from tools.r1000_live_extension import date_only, infer_anchor_date, latest_date_from_json_payload


def test_infers_anchor_date_from_broker_metrics() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        portfolio_path = root / "portfolio_latest.csv"
        portfolio = pd.DataFrame([{"ticker": "AAA", "weight": 0.2}])
        portfolio.to_csv(portfolio_path, index=False)
        metrics_dir = root / "broker_replay" / "main"
        metrics_dir.mkdir(parents=True)
        (metrics_dir / "metrics.json").write_text(
            json.dumps({"status": "completed", "end_date": "2026-05-29"}),
            encoding="utf-8",
        )

        assert infer_anchor_date(portfolio_path, portfolio, None) == "2026-05-29"


def test_infers_anchor_date_from_official_current_metrics() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        portfolio_path = root / "portfolio_latest.csv"
        portfolio = pd.DataFrame([{"ticker": "AAA", "weight": 0.2}])
        portfolio.to_csv(portfolio_path, index=False)
        current_dir = root / "user_current"
        current_dir.mkdir(parents=True)
        (current_dir / "04_official_metrics.json").write_text(
            json.dumps(
                {
                    "official_metric_mode": "broker_ledger_next_close",
                    "portfolios": {
                        "main": {"end_date": "2026-05-29"},
                        "concentrated": {"end_date": "2026-05-28"},
                    },
                }
            ),
            encoding="utf-8",
        )

        assert infer_anchor_date(portfolio_path, portfolio, None) == "2026-05-29"


def test_portfolio_date_takes_precedence_over_json_metrics() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        portfolio_path = root / "portfolio_latest.csv"
        portfolio = pd.DataFrame([{"ticker": "AAA", "weight": 0.2, "asof": "2026-06-01"}])
        portfolio.to_csv(portfolio_path, index=False)
        metrics_dir = root / "broker_replay" / "main"
        metrics_dir.mkdir(parents=True)
        (metrics_dir / "metrics.json").write_text(
            json.dumps({"status": "completed", "end_date": "2026-05-29"}),
            encoding="utf-8",
        )

        assert infer_anchor_date(portfolio_path, portfolio, None) == "2026-06-01"


def test_generated_at_is_not_an_anchor_date_candidate() -> None:
    payload = {
        "generated_at_utc": "2026-05-30T09:40:15+00:00",
        "portfolios": {"main": {"end_date": "2026-05-29"}},
    }
    assert latest_date_from_json_payload(payload, ["end_date", "as_of_date", "asof", "date", "anchor_date"]) == "2026-05-29"


def test_date_only_normalizes_timezone_aware_values() -> None:
    assert str(date_only(pd.Timestamp("2026-05-29", tz="America/New_York"))) == "2026-05-29"
    assert str(date_only("2026-05-29")) == "2026-05-29"


def test_live_extension_handles_timezone_aware_price_index() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        portfolio_path = root / "portfolio_latest.csv"
        scored_path = root / "scored_latest.csv"
        portfolio = pd.DataFrame([{"ticker": "AAA", "weight": 1.0}])
        portfolio.to_csv(portfolio_path, index=False)
        pd.DataFrame([{"ticker": "AAA", "score": 1.0}]).to_csv(scored_path, index=False)
        metrics_dir = root / "broker_replay" / "main"
        metrics_dir.mkdir(parents=True)
        (metrics_dir / "metrics.json").write_text(
            json.dumps({"status": "completed", "end_date": "2026-05-29"}),
            encoding="utf-8",
        )

        def fake_fetch_history(ticker: str, start: str, end: str):
            index = pd.date_range("2026-05-29", "2026-06-03", freq="B", tz="America/New_York")
            return pd.DataFrame({"close": [100.0, 89.0, 88.0, 90.0]}, index=index)

        original_fetch_history = live_extension.fetch_history
        original_argv = sys.argv[:]
        try:
            live_extension.fetch_history = fake_fetch_history
            sys.argv = [
                "r1000_live_extension.py",
                "--portfolio",
                str(portfolio_path),
                "--scored",
                str(scored_path),
                "--out-dir",
                str(root / "live_extension"),
                "--today",
                "2026-06-03",
                "--start-cap",
                "100000",
            ]
            assert live_extension.main() == 0
        finally:
            live_extension.fetch_history = original_fetch_history
            sys.argv = original_argv

        summary = json.loads((root / "live_extension" / "summary.json").read_text(encoding="utf-8"))
        assert summary["anchor_date"] == "2026-05-29"
        assert summary["n_stops_triggered"] == 1


def main() -> int:
    test_infers_anchor_date_from_broker_metrics()
    test_infers_anchor_date_from_official_current_metrics()
    test_portfolio_date_takes_precedence_over_json_metrics()
    test_generated_at_is_not_an_anchor_date_candidate()
    test_date_only_normalizes_timezone_aware_values()
    test_live_extension_handles_timezone_aware_price_index()
    print("live_extension_anchor_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
