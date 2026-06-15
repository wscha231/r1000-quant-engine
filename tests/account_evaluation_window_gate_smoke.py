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
    gate = evaluate_window_gate({"start_date": "2018-06-01", "end_date": "2026-06-12", "years": 8.03})
    assert gate["valid"] is True
    assert gate["status"] == "ok"
    assert gate["trading_days_estimate"] >= 252 * 8


if __name__ == "__main__":
    test_window_gate_rejects_short_run()
    test_window_gate_accepts_8_year_run()
    print("account_evaluation_window_gate_smoke: PASS")
