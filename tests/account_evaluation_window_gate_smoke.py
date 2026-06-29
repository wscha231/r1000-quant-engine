#!/usr/bin/env python3
"""Smoke test for clean 7-year broker-ledger window gate."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from r1000_config import OFFICIAL_BACKTEST_WINDOW_YEARS, PROXY_8Y_10Y_EVIDENCE_BLOCKED  # noqa: E402
from tools.run_account_evaluation import evaluate_window_gate  # noqa: E402


WORKFLOW = REPO_ROOT / ".github" / "workflows" / "full_rebuild_manual.yml"


def test_config_locks_clean_7y_window() -> None:
    assert OFFICIAL_BACKTEST_WINDOW_YEARS == 7.0
    assert PROXY_8Y_10Y_EVIDENCE_BLOCKED is True


def test_window_gate_rejects_short_run() -> None:
    gate = evaluate_window_gate({"start_date": "2020-06-03", "end_date": "2026-06-12", "years": 6.03})
    assert gate["valid"] is False
    assert gate["status"] == "invalid_window"
    assert "broker_ledger_years_below_7" in gate["reasons"]


def test_window_gate_accepts_clean_7_year_run() -> None:
    gate = evaluate_window_gate(
        {"start_date": "2019-06-03", "evaluation_start_date": "2019-06-17", "end_date": "2026-06-12", "years": 7.03},
        equity_window={"exists": True, "trading_day_count": 1770, "start_date": "2019-06-28", "end_date": "2026-06-12"},
        data_readiness={"status": "ready", "ready_for_policy_replay": True, "ready_for_fullrun": True, "free_data_coverage": {"known_gaps": []}},
        require_data_readiness=True,
    )
    assert gate["valid"] is True
    assert gate["status"] == "ok"
    assert gate["trading_days_estimate"] >= 252 * 7
    assert gate["evaluation_start_date"] == "2019-06-17"
    assert gate["broker_start_evaluation_drift_days"] == 11
    assert gate["evidence_window_label"] == "research_7y"
    assert gate["production_promotion_allowed"] is False


def test_window_gate_rejects_broker_start_later_than_evaluation_start() -> None:
    gate = evaluate_window_gate(
        {"start_date": "2019-06-17", "evaluation_start_date": "2019-06-17", "end_date": "2026-06-12", "years": 7.03},
        equity_window={"exists": True, "trading_day_count": 1770, "start_date": "2020-05-01", "end_date": "2026-06-12"},
        data_readiness={"status": "ready", "ready_for_policy_replay": True, "ready_for_fullrun": True, "free_data_coverage": {"known_gaps": []}},
        require_data_readiness=True,
    )
    assert gate["valid"] is False
    assert gate["status"] == "invalid_window"
    assert gate["broker_start_evaluation_drift_days"] > gate["max_broker_start_evaluation_drift_days"]
    assert "broker_start_later_than_evaluation_start" in gate["reasons"]


def test_window_gate_allows_small_month_end_alignment_drift() -> None:
    gate = evaluate_window_gate(
        {"start_date": "2019-06-17", "evaluation_start_date": "2019-06-17", "end_date": "2026-06-12", "years": 7.03},
        equity_window={"exists": True, "trading_day_count": 1770, "start_date": "2019-07-19", "end_date": "2026-06-12"},
        data_readiness={"status": "ready", "ready_for_policy_replay": True, "ready_for_fullrun": True, "free_data_coverage": {"known_gaps": []}},
        require_data_readiness=True,
    )
    assert gate["valid"] is True
    assert gate["broker_start_evaluation_drift_days"] == 32
    assert "broker_start_later_than_evaluation_start" not in gate["reasons"]


def test_window_gate_rejects_dirty_8_year_proxy_window() -> None:
    gate = evaluate_window_gate(
        {"start_date": "2018-06-01", "end_date": "2026-06-12", "years": 8.03},
        equity_window={"exists": True, "trading_day_count": 2025, "start_date": "2018-06-01", "end_date": "2026-06-12"},
        data_readiness={"status": "ready", "ready_for_policy_replay": True, "ready_for_fullrun": True, "free_data_coverage": {"known_gaps": []}},
        require_data_readiness=True,
    )
    assert gate["valid"] is False
    assert "proxy_8y_10y_evidence_blocked_until_pit_universe_clean" in gate["reasons"]


def test_window_gate_accepts_pit_clean_8_year_window() -> None:
    gate = evaluate_window_gate(
        {"start_date": "2018-06-01", "end_date": "2026-06-12", "years": 8.03, "pit_universe_label_clean": True},
        equity_window={"exists": True, "trading_day_count": 2025, "start_date": "2018-06-01", "end_date": "2026-06-12"},
        data_readiness={"status": "ready", "ready_for_policy_replay": True, "ready_for_fullrun": True, "free_data_coverage": {"known_gaps": []}},
        require_data_readiness=True,
    )
    assert gate["valid"] is True
    assert gate["status"] == "ok"
    assert gate["evidence_window_label"] == "pit_clean_long_window"


def test_window_gate_rejects_short_actual_equity_curve_even_if_metrics_years_pass() -> None:
    gate = evaluate_window_gate(
        {"start_date": "2019-06-03", "end_date": "2026-06-12", "years": 7.03},
        equity_window={"exists": True, "trading_day_count": 1200, "start_date": "2018-06-01", "end_date": "2026-06-12"},
        data_readiness={"status": "ready", "ready_for_policy_replay": True, "ready_for_fullrun": True, "free_data_coverage": {"known_gaps": []}},
        require_data_readiness=True,
    )
    assert gate["valid"] is False
    assert "broker_ledger_trading_days_below_7y" in gate["reasons"]


def test_window_gate_uses_calendar_days_when_equity_curve_omits_cash_only_rows() -> None:
    gate = evaluate_window_gate(
        {"start_date": "2019-06-03", "end_date": "2026-06-12", "years": 7.03},
        equity_window={
            "exists": True,
            "equity_curve_observed_day_count": 1714,
            "calendar_trading_day_count": 1770,
            "trading_day_count": 1770,
            "start_date": "2019-06-03",
            "end_date": "2026-06-12",
        },
        data_readiness={"status": "ready", "ready_for_policy_replay": True, "ready_for_fullrun": True, "free_data_coverage": {"known_gaps": []}},
        require_data_readiness=True,
    )
    assert gate["valid"] is True
    assert gate["equity_curve_observed_day_count"] == 1714
    assert gate["calendar_trading_day_count"] == 1770
    assert gate["actual_trading_days"] == 1770
    assert "broker_ledger_trading_days_below_7y" not in gate["reasons"]


def test_window_classification_valid_7y_for_clean_run() -> None:
    gate = evaluate_window_gate(
        {"start_date": "2019-06-03", "evaluation_start_date": "2019-06-17", "end_date": "2026-06-12", "years": 7.03},
        equity_window={"exists": True, "trading_day_count": 1770, "start_date": "2019-06-28", "end_date": "2026-06-12"},
        data_readiness={"status": "ready", "ready_for_policy_replay": True, "ready_for_fullrun": True, "free_data_coverage": {"known_gaps": []}},
        require_data_readiness=True,
    )
    assert gate["valid"] is True
    assert gate["window_classification"] == "valid_7y"
    assert gate["research_acceptable"] is True


def test_window_classification_research_tolerance_for_near_7y_run() -> None:
    # 6.95y / 1751 trading days: production-invalid (years/days below 7.0y) but the ONLY
    # blockers are the year band -> research_7y_tolerance, research_acceptable True.
    gate = evaluate_window_gate(
        {"start_date": "2019-07-15", "evaluation_start_date": "2019-07-15", "end_date": "2026-06-12", "years": 6.95},
        equity_window={"exists": True, "trading_day_count": 1751, "start_date": "2019-07-15", "end_date": "2026-06-12"},
        data_readiness={"status": "ready", "ready_for_policy_replay": True, "ready_for_fullrun": True, "free_data_coverage": {"known_gaps": []}},
        require_data_readiness=True,
    )
    assert gate["valid"] is False  # production gate stays strict
    assert gate["status"] == "invalid_window"
    assert "broker_ledger_years_below_7" in gate["reasons"]
    assert gate["window_classification"] == "research_7y_tolerance"
    assert gate["research_acceptable"] is True


def test_window_classification_invalid_below_tolerance_floor() -> None:
    gate = evaluate_window_gate(
        {"start_date": "2020-01-02", "evaluation_start_date": "2020-01-02", "end_date": "2026-06-12", "years": 6.50},
        equity_window={"exists": True, "trading_day_count": 1638, "start_date": "2020-01-02", "end_date": "2026-06-12"},
        data_readiness={"status": "ready", "ready_for_policy_replay": True, "ready_for_fullrun": True, "free_data_coverage": {"known_gaps": []}},
        require_data_readiness=True,
    )
    assert gate["valid"] is False
    assert gate["window_classification"] == "invalid_window"
    assert gate["research_acceptable"] is False


def test_window_classification_not_tolerance_when_non_band_reason_present() -> None:
    # 6.95y but data_readiness missing -> a non-band blocker -> NOT research tolerance.
    gate = evaluate_window_gate(
        {"start_date": "2019-07-15", "evaluation_start_date": "2019-07-15", "end_date": "2026-06-12", "years": 6.95},
        equity_window={"exists": True, "trading_day_count": 1751, "start_date": "2019-07-15", "end_date": "2026-06-12"},
        require_data_readiness=True,
    )
    assert gate["window_classification"] == "invalid_window"
    assert gate["research_acceptable"] is False
    assert "data_readiness_summary_missing" in gate["reasons"]


def test_window_classification_proxy_long_window_blocked_and_pit_clean_long() -> None:
    blocked = evaluate_window_gate(
        {"start_date": "2018-06-01", "end_date": "2026-06-12", "years": 8.03},
        equity_window={"exists": True, "trading_day_count": 2025, "start_date": "2018-06-01", "end_date": "2026-06-12"},
        data_readiness={"status": "ready", "ready_for_policy_replay": True, "ready_for_fullrun": True, "free_data_coverage": {"known_gaps": []}},
        require_data_readiness=True,
    )
    assert blocked["window_classification"] == "proxy_long_window_blocked"
    assert blocked["research_acceptable"] is False
    clean = evaluate_window_gate(
        {"start_date": "2018-06-01", "end_date": "2026-06-12", "years": 8.03, "pit_universe_label_clean": True},
        equity_window={"exists": True, "trading_day_count": 2025, "start_date": "2018-06-01", "end_date": "2026-06-12"},
        data_readiness={"status": "ready", "ready_for_policy_replay": True, "ready_for_fullrun": True, "free_data_coverage": {"known_gaps": []}},
        require_data_readiness=True,
    )
    assert clean["window_classification"] == "pit_clean_long_window"
    assert clean["research_acceptable"] is True


def test_window_gate_rejects_missing_data_readiness_when_required() -> None:
    gate = evaluate_window_gate(
        {"start_date": "2019-06-03", "end_date": "2026-06-12", "years": 7.03},
        equity_window={"exists": True, "trading_day_count": 1770, "start_date": "2019-06-03", "end_date": "2026-06-12"},
        require_data_readiness=True,
    )
    assert gate["valid"] is False
    assert "data_readiness_summary_missing" in gate["reasons"]


def test_workflow_rejects_long_window_without_pit_label() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "default: '7'" in text
    assert "pit_universe_label_clean" in text
    assert "proxy 8Y/10Y evidence is blocked until PIT universe is clean" in text
    assert "years > 7.05 and not pit_clean" in text


if __name__ == "__main__":
    test_config_locks_clean_7y_window()
    test_window_gate_rejects_short_run()
    test_window_gate_accepts_clean_7_year_run()
    test_window_gate_rejects_broker_start_later_than_evaluation_start()
    test_window_gate_allows_small_month_end_alignment_drift()
    test_window_gate_rejects_dirty_8_year_proxy_window()
    test_window_gate_accepts_pit_clean_8_year_window()
    test_window_gate_rejects_short_actual_equity_curve_even_if_metrics_years_pass()
    test_window_gate_uses_calendar_days_when_equity_curve_omits_cash_only_rows()
    test_window_classification_valid_7y_for_clean_run()
    test_window_classification_research_tolerance_for_near_7y_run()
    test_window_classification_invalid_below_tolerance_floor()
    test_window_classification_not_tolerance_when_non_band_reason_present()
    test_window_classification_proxy_long_window_blocked_and_pit_clean_long()
    test_window_gate_rejects_missing_data_readiness_when_required()
    test_workflow_rejects_long_window_without_pit_label()
    print("account_evaluation_window_gate_smoke: PASS")
