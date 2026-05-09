#!/usr/bin/env python3
"""Smoke tests for the portfolio system target guard."""
from __future__ import annotations

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


def test_portfolio_system_guard_reports_target_gaps() -> None:
    with TemporaryDirectory() as tmp:
        out_dir = Path(tmp) / "guard"
        latest = Path(tmp) / "latest"
        write_json(
            latest / "broker_replay" / "main" / "metrics.json",
            {"status": "completed", "metric_mode": "broker_ledger_next_close", "valid_for_production": True, "cagr": 0.21, "max_dd": -0.36, "sharpe": 0.97},
        )
        write_json(
            latest / "broker_replay" / "concentrated" / "metrics.json",
            {"status": "completed", "metric_mode": "broker_ledger_next_close", "valid_for_production": True, "cagr": 0.34, "max_dd": -0.40, "sharpe": 1.09},
        )
        write_json(latest / "backtest_metrics.json", {"strategy_cagr": 0.99, "max_dd": -0.01, "sharpe": 9.0})
        write_json(latest / "concentrated_backtest_metrics.json", {"strategy_cagr": 0.99, "max_dd": -0.01, "sharpe": 9.0})
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
        assert (out_dir / "system_guard_report.md").exists()
        assert (out_dir / "target_gap.json").exists()


if __name__ == "__main__":
    test_portfolio_system_guard_reports_target_gaps()
    print("portfolio_system_guard_smoke: ok")
