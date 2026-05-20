#!/usr/bin/env python3
"""Smoke test official-first Telegram verdict summary."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parent.parent


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_auto_verdict_summary_ignores_legacy_ship_as_official() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_json(
            root / "account_evaluation" / "official_metrics.json",
            {
                "official_metric_mode": "broker_ledger_next_close",
                "production_target_pass": False,
                "portfolios": {
                    "main": {
                        "cagr": 0.18,
                        "sharpe": 0.9,
                        "max_dd": -0.34,
                        "avg_cash_weight": 0.04,
                        "broker_trade_count": 100,
                        "ending_capital_usd": 450000,
                    },
                    "concentrated": {
                        "cagr": 0.27,
                        "sharpe": 0.96,
                        "max_dd": -0.39,
                        "avg_cash_weight": 0.0,
                        "broker_trade_count": 50,
                        "ending_capital_usd": 850000,
                    },
                },
            },
        )
        write_json(
            root / "account_evaluation" / "account_evaluation_summary.json",
            {"production_target_pass": False, "research_target_pass": True},
        )
        write_json(root / "backtest_metrics.json", {"cagr": 0.99, "sharpe": 9.0, "max_dd": -0.01})
        write_json(
            root / "concentrated_backtest_metrics.json",
            {"strategy_cagr": 0.99, "sharpe": 9.0, "max_dd": -0.01, "production_valid": False},
        )

        proc = subprocess.run(
            [sys.executable, str(REPO_ROOT / "tools" / "auto_verdict_summary.py"), "--base", str(root)],
            cwd=REPO_ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
        out = proc.stdout
        assert "OFFICIAL metric mode: broker-ledger next-close account replay" in out
        assert "OFFICIAL RESULT: NO PRODUCTION SHIP" in out
        assert "research_target_pass=true" in out
        assert "rotate CURRENT_BASELINE" not in out


if __name__ == "__main__":
    test_auto_verdict_summary_ignores_legacy_ship_as_official()
    print("auto_verdict_summary_smoke: PASS")
