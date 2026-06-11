#!/usr/bin/env python3
"""Smoke checks for healthy baseline lock creation."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd
import json

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.create_healthy_baseline_lock import build_lock  # noqa: E402


def test_healthy_baseline_lock_requires_broker_and_broad_universe() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        latest = Path(tmp)
        (latest / "account_evaluation").mkdir()
        (latest / "portfolio_system_guard").mkdir()
        (latest / "broker_replay" / "main").mkdir(parents=True)
        (latest / "broker_replay" / "concentrated").mkdir(parents=True)
        official = {
            "official_metric_mode": "broker_ledger_next_close",
            "portfolios": {
                "main": {
                    "cagr": 0.21,
                    "max_dd": -0.30,
                    "sharpe": 1.0,
                    "position_count": 15,
                    "valid_for_production": True,
                    "official_source": "broker_replay/main/metrics.json",
                },
                "concentrated": {
                    "cagr": 0.32,
                    "max_dd": -0.35,
                    "sharpe": 1.1,
                    "position_count": 5,
                    "valid_for_production": True,
                    "official_source": "broker_replay/concentrated/metrics.json",
                },
            },
        }
        broker_base = {
            "status": "completed",
            "metric_mode": "broker_ledger_next_close",
            "valid_for_production": True,
            "years": 7.1,
            "start_date": "2019-01-31",
            "end_date": "2026-03-31",
        }
        (latest / "account_evaluation" / "official_metrics.json").write_text(json.dumps(official), encoding="utf-8")
        (latest / "broker_replay" / "main" / "metrics.json").write_text(
            json.dumps({**broker_base, "cagr": 0.21, "max_dd": -0.30, "sharpe": 1.0}),
            encoding="utf-8",
        )
        (latest / "broker_replay" / "concentrated" / "metrics.json").write_text(
            json.dumps({**broker_base, "cagr": 0.32, "max_dd": -0.35, "sharpe": 1.1}),
            encoding="utf-8",
        )
        (latest / "portfolio_system_guard" / "error_check.json").write_text('{"hard_error_count": 0}', encoding="utf-8")
        pd.DataFrame(
            {
                "ticker": [f"T{i}" for i in range(450)],
                "universe_source": ["current_constituents_proxy_static_seed"] * 450,
            }
        ).to_csv(latest / "scored_latest.csv", index=False)
        (latest / "reports").mkdir()
        (latest / "reports" / "candidate_replay_book.csv").write_text("rebalance_date,ticker\n2026-01-31,A\n", encoding="utf-8")
        payload, blockers = build_lock(latest, "123", "master", "abc", 400)
        assert blockers == []
        assert payload["promotion_eligible"] is True
        assert payload["scored_row_count"] == 450
        assert payload["r1000_base_count"] == 450
        assert payload["broker_period_years"] >= 6.8
        assert payload["candidate_replay_book_present"] is True
        assert payload["main_cagr"] == 0.21


def test_baseline_lock_blocks_collapsed_universe() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        latest = Path(tmp)
        (latest / "account_evaluation").mkdir()
        (latest / "account_evaluation" / "official_metrics.json").write_text(
            '{"official_metric_mode":"broker_ledger_next_close","portfolios":{"main":{"cagr":0.1},"concentrated":{"cagr":0.2}}}',
            encoding="utf-8",
        )
        pd.DataFrame({"ticker": ["A", "B"], "universe_source": ["leader_rescue"] * 2}).to_csv(latest / "scored_latest.csv", index=False)
        payload, blockers = build_lock(latest, "123", "master", "abc", 400)
        assert "scored_row_count_below_floor" in blockers
        assert payload["promotion_eligible"] is False


def main() -> int:
    test_healthy_baseline_lock_requires_broker_and_broad_universe()
    test_baseline_lock_blocks_collapsed_universe()
    print("baseline_lock_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
