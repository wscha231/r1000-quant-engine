#!/usr/bin/env python3
"""Smoke test for official/deprecated metric hygiene outputs."""
from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.run_metric_hygiene_report import run  # noqa: E402


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def seed_portfolio(root: Path, portfolio: str, *, cagr: float, max_dd: float, avg_cash: float) -> None:
    write_json(
        root / "broker_replay" / portfolio / "metrics.json",
        {
            "status": "completed",
            "metric_mode": "broker_ledger_next_close",
            "valid_for_production": True,
            "cagr": cagr,
            "max_dd": max_dd,
            "sharpe": 1.1,
            "avg_cash_weight": avg_cash,
            "target_book": f"outputs/reports/operating_{portfolio}_target_book.csv",
        },
    )
    write_json(
        root / "broker_replay" / portfolio / "account_state_latest.json",
        {
            "cash_weight": avg_cash,
            "position_count": 8,
        },
    )


def test_metric_hygiene_marks_legacy_metrics_deprecated_and_cash_trap_warns() -> None:
    with TemporaryDirectory() as tmp:
        latest = Path(tmp) / "latest"
        out = Path(tmp) / "metric_hygiene"
        seed_portfolio(latest, "main", cagr=0.31, max_dd=-0.37, avg_cash=0.24)
        seed_portfolio(latest, "concentrated", cagr=0.31, max_dd=-0.40, avg_cash=0.31)
        write_json(
            latest / "account_evaluation" / "official_metrics.json",
            {
                "official_metric_mode": "broker_ledger_next_close",
                "portfolios": {
                    "main": {"target_pass": False},
                    "concentrated": {"target_pass": False},
                },
            },
        )
        write_json(latest / "backtest_metrics.json", {"cagr": 0.90, "max_dd": -0.01, "sharpe": 9.0})
        write_json(latest / "concentrated_backtest_metrics.json", {"cagr": 0.95, "max_dd": -0.02, "sharpe": 9.0})

        result = run(Namespace(latest_run=str(latest), output_dir=str(out)))

        assert result["official_metric_mode"] == "broker_ledger_next_close"
        assert result["target_type"] == "canonical_mission"
        assert result["mission_target_pass"] is False
        assert result["production_target_pass"] is False
        assert result["production_valid_all"] is True
        assert result["cash_trap_warning_count"] == 2
        assert result["official_portfolios"]["main"]["cagr"] == 0.31
        assert result["official_portfolios"]["main"]["max_dd"] == -0.37
        assert result["official_portfolios"]["main"]["cagr_target"] == 0.35
        assert result["official_portfolios"]["main"]["max_dd_target"] == -0.25
        assert result["deprecated_metrics"][0]["DO_NOT_USE_FOR_PRODUCTION"] is True

        deprecated = json.loads((out / "deprecated_legacy_backtest_metrics.json").read_text(encoding="utf-8"))
        assert deprecated["DO_NOT_USE_FOR_PRODUCTION"] is True
        assert deprecated["production_valid"] is False
        assert deprecated["official_metric_required"] == "broker_ledger_next_close"
        assert deprecated["legacy_cagr"] == 0.90
        assert deprecated["official_cagr"] == 0.31

        assert (out / "official_metrics.json").exists()
        assert (out / "deprecated_metric_manifest.json").exists()
        assert (out / "report.md").exists()


def test_metric_hygiene_separates_mission_from_production_validity() -> None:
    with TemporaryDirectory() as tmp:
        latest = Path(tmp) / "latest"
        out = Path(tmp) / "metric_hygiene"
        seed_portfolio(latest, "main", cagr=0.35, max_dd=-0.25, avg_cash=0.05)
        seed_portfolio(latest, "concentrated", cagr=0.50, max_dd=-0.25, avg_cash=0.05)
        main_path = latest / "broker_replay" / "main" / "metrics.json"
        main = json.loads(main_path.read_text(encoding="utf-8"))
        main["valid_for_production"] = False
        write_json(main_path, main)

        result = run(Namespace(latest_run=str(latest), output_dir=str(out)))
        assert result["official_portfolios"]["main"]["target_pass"] is True
        assert result["official_portfolios"]["main"]["production_valid"] is False
        assert result["mission_target_pass"] is True
        assert result["production_valid_all"] is False
        assert result["production_target_pass"] is False


if __name__ == "__main__":
    test_metric_hygiene_marks_legacy_metrics_deprecated_and_cash_trap_warns()
    test_metric_hygiene_separates_mission_from_production_validity()
    print("metric_hygiene_report_smoke: PASS")
