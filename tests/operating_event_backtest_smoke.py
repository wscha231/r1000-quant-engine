#!/usr/bin/env python3
"""Smoke tests for operating event backtest verification."""
from __future__ import annotations

import csv
import json
import sys
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.run_operating_event_backtest import run  # noqa: E402


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def seed_portfolio(latest: Path, portfolio: str, target_rows: list[dict], risk_rows: list[dict]) -> None:
    write_csv(latest / "reports" / f"operating_{portfolio}_target_book.csv", target_rows)
    for folder in ["broker_replay", "broker_position_risk_replay", "broker_execution_policy_replay"]:
        write_json(
            latest / folder / portfolio / "metrics.json",
            {
                "status": "completed",
                "metric_mode": folder,
                "cagr": 0.21,
                "max_dd": -0.18,
                "sharpe": 1.1,
                "end_date": "2026-01-31",
                "trade_count": 4,
            },
        )
        write_csv(
            latest / folder / portfolio / "equity_curve.csv",
            [
                {"date": "2026-01-05", "equity_usd": 100000.0},
                {"date": "2026-01-31", "equity_usd": 102000.0},
            ],
        )
    write_csv(latest / "broker_position_risk_replay" / portfolio / "risk_actions.csv", risk_rows)
    write_csv(latest / "broker_execution_policy_replay" / portfolio / "policy_decisions.csv", [{"date": "2026-01-05", "ticker": "AAA"}])


def test_operating_event_backtest_marks_partial_and_full_evidence() -> None:
    with TemporaryDirectory() as tmp:
        latest = Path(tmp) / "latest"
        out = Path(tmp) / "out"
        seed_portfolio(
            latest,
            "main",
            [
                {"rebalance_date": "2026-01-02", "ticker": "AAA", "weight": 1.0},
                {"rebalance_date": "2026-01-15", "ticker": "BBB", "weight": 1.0},
            ],
            [
                {
                    "signal_date": "2026-01-10",
                    "fill_date": "2026-01-12",
                    "ticker": "AAA",
                    "reason": "weekly_relative_exit",
                    "price_return": -0.09,
                    "relative_return": -0.13,
                    "gross_value": 12000.0,
                }
            ],
        )
        seed_portfolio(
            latest,
            "concentrated",
            [{"rebalance_date": "2026-01-02", "ticker": "CCC", "weight": 1.0}],
            [],
        )

        payload = run(Namespace(latest_run=str(latest), output_dir=str(out)))
        assert payload["status"] == "completed"
        assert payload["daily_risk_overlay_validated"] is True
        assert payload["daily_risk_action_evidence_count"] == 1
        assert payload["full_nonmonthly_entry_replacement_validated"] is False
        rows = {row["portfolio"]: row for row in payload["portfolios"]}
        assert rows["main"]["full_nonmonthly_entry_replacement_validated"] is True
        assert rows["main"]["operating_event_backtest_status"] == "full_nonmonthly_entry_replacement_validated"
        assert rows["concentrated"]["operating_event_backtest_status"] == "partial_daily_risk_overlay_validated"
        evidence = list(csv.DictReader((out / "nonmonthly_trade_evidence.csv").open(encoding="utf-8")))
        assert len(evidence) == 1
        assert evidence[0]["signal_date"] == "2026-01-10"
        assert (out / "operating_event_backtest_summary.json").exists()
        assert (out / "operating_event_backtest_report.md").exists()


if __name__ == "__main__":
    test_operating_event_backtest_marks_partial_and_full_evidence()
    print("operating_event_backtest_smoke: ok")
