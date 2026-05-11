#!/usr/bin/env python3
"""Smoke tests for the portfolio system target guard."""
from __future__ import annotations

import csv
import sys
import json
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.run_portfolio_system_guard import run  # noqa: E402


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


def test_portfolio_system_guard_reports_target_gaps() -> None:
    with TemporaryDirectory() as tmp:
        out_dir = Path(tmp) / "guard"
        latest = Path(tmp) / "latest"
        write_json(
            latest / "broker_replay" / "main" / "metrics.json",
            {"status": "completed", "metric_mode": "broker_ledger_next_close", "valid_for_production": True, "cagr": 0.21, "max_dd": -0.36, "sharpe": 0.97, "end_date": "2026-01-10"},
        )
        write_json(
            latest / "broker_replay" / "concentrated" / "metrics.json",
            {
                "status": "completed",
                "metric_mode": "broker_ledger_next_close",
                "valid_for_production": True,
                "cagr": 0.34,
                "max_dd": -0.40,
                "sharpe": 1.09,
                "end_date": "2026-01-10",
                "target_book_filter": {"target_stock_names": "4", "weighting_mode": "score_power"},
            },
        )
        write_json(latest / "backtest_metrics.json", {"strategy_cagr": 0.99, "max_dd": -0.01, "sharpe": 9.0})
        write_json(latest / "concentrated_backtest_metrics.json", {"strategy_cagr": 0.99, "max_dd": -0.01, "sharpe": 9.0})
        write_csv(latest / "reports" / "main_monthly_weights.csv", [{"rebalance_date": "2025-12-31", "ticker": "AAA", "weight": 1.0}])
        write_csv(
            latest / "reports" / "concentrated_strategy_holdings.csv",
            [{"rebalance_date": "2025-12-31", "ticker": "AAA", "weight": 1.0, "target_stock_names": 4, "weighting_mode": "score_power"}],
        )
        write_csv(latest / "portfolio_latest.csv", [{"ticker": "AAA", "weight": 0.5}, {"ticker": "BBB", "weight": 0.5}])
        write_csv(
            latest / "concentrated_portfolio_latest.csv",
            [{"rebalance_date": "2026-01-10", "ticker": "AAA", "weight": 1.0, "target_stock_names": 4, "weighting_mode": "score_power"}],
        )
        write_csv(
            latest / "broker_replay" / "main" / "positions_latest.csv",
            [{"ticker": f"T{i}", "weight": 0.1} for i in range(10)],
        )
        write_csv(
            latest / "operating_snapshot" / "current_operating_holdings_latest.csv",
            [{"portfolio_kind": "main", "ticker": "AAA", "current_weight": 1.0}],
        )
        result = run(
            Namespace(
                latest_run=str(latest),
                output_dir=str(out_dir),
                main_cagr_target=0.30,
                main_max_dd_target=-0.15,
                concentrated_cagr_target=0.50,
                concentrated_max_dd_target=-0.18,
                strict_targets=False,
            )
        )
        assert result["overall_status"] == "blocked"
        assert result["targets_pass"] is False
        assert len(result["portfolio_status"]) == 2
        main = result["portfolio_status"][0]
        concentrated = result["portfolio_status"][1]
        assert main["portfolio"] == "main"
        assert concentrated["portfolio"] == "concentrated"
        assert main["metric_source"] == "broker_ledger_next_close"
        assert concentrated["metric_source"] == "broker_ledger_next_close"
        assert main["cagr_gap_pp"] > 0
        assert concentrated["cagr_gap_pp"] > 0
        main_metric_check = next(row for row in result["error_checks"] if row["check"] == "main_metrics_available")
        assert main_metric_check["severity"] in {"ok", "warn"}
        checks = {row["check"]: row for row in result["error_checks"]}
        assert checks["main_target_book_reaches_broker_end"]["severity"] == "warn"
        assert checks["current_only_operating_holdings_available"]["passed"] is True
        assert checks["main_current_position_count_near_latest_target_count"]["passed"] is False
        assert checks["concentrated_replay_filter_matches_latest_target"]["passed"] is True
        assert (out_dir / "system_guard_report.md").exists()
        assert (out_dir / "target_gap.json").exists()


if __name__ == "__main__":
    test_portfolio_system_guard_reports_target_gaps()
    print("portfolio_system_guard_smoke: ok")
