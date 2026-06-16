#!/usr/bin/env python3
"""Smoke test for mandatory 8-year broker-ledger window gate."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.run_account_evaluation import evaluate_window_gate  # noqa: E402


def test_window_gate_rejects_short_run() -> None:
    gate = evaluate_window_gate({"start_date": "2019-06-03", "end_date": "2026-06-12", "years": 7.03})
    assert gate["valid"] is False
    assert gate["status"] == "invalid_window"
    assert "broker_ledger_years_below_8" in gate["reasons"]


def test_window_gate_accepts_8_year_run() -> None:
    gate = evaluate_window_gate(
        {"start_date": "2018-06-01", "end_date": "2026-06-12", "years": 8.03},
        equity_window={"exists": True, "trading_day_count": 2025, "start_date": "2018-06-01", "end_date": "2026-06-12"},
        data_readiness={"status": "ready", "ready_for_policy_replay": True, "ready_for_fullrun": True, "free_data_coverage": {"known_gaps": []}},
        require_data_readiness=True,
    )
    assert gate["valid"] is True
    assert gate["status"] == "ok"
    assert gate["trading_days_estimate"] >= 252 * 8


def test_window_gate_rejects_short_actual_equity_curve_even_if_metrics_years_pass() -> None:
    gate = evaluate_window_gate(
        {"start_date": "2018-06-01", "end_date": "2026-06-12", "years": 8.03},
        equity_window={"exists": True, "trading_day_count": 1200, "start_date": "2018-06-01", "end_date": "2026-06-12"},
        data_readiness={"status": "ready", "ready_for_policy_replay": True, "ready_for_fullrun": True, "free_data_coverage": {"known_gaps": []}},
        require_data_readiness=True,
    )
    assert gate["valid"] is False
    assert "broker_ledger_trading_days_below_8y" in gate["reasons"]


def test_window_gate_rejects_missing_data_readiness_when_required() -> None:
    gate = evaluate_window_gate(
        {"start_date": "2018-06-01", "end_date": "2026-06-12", "years": 8.03},
        equity_window={"exists": True, "trading_day_count": 2025, "start_date": "2018-06-01", "end_date": "2026-06-12"},
        require_data_readiness=True,
    )
    assert gate["valid"] is False
    assert "data_readiness_summary_missing" in gate["reasons"]


if __name__ == "__main__":
    test_window_gate_rejects_short_run()
    test_window_gate_accepts_8_year_run()
    test_window_gate_rejects_short_actual_equity_curve_even_if_metrics_years_pass()
    test_window_gate_rejects_missing_data_readiness_when_required()
    print("account_evaluation_window_gate_smoke: PASS")
