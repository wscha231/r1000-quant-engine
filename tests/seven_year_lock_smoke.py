#!/usr/bin/env python3
"""Smoke tests for the clean 7Y evidence-window lock."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from r1000_config import (  # noqa: E402
    OFFICIAL_BACKTEST_WINDOW_YEARS,
    PROXY_8Y_10Y_EVIDENCE_BLOCKED,
    PROXY_WINDOW_BLOCKER_REASON,
)
from tools.run_account_evaluation import evaluate_window_gate  # noqa: E402


WORKFLOW = REPO_ROOT / ".github" / "workflows" / "full_rebuild_manual.yml"


def ready_payload() -> dict:
    return {
        "status": "ready",
        "ready_for_policy_replay": True,
        "ready_for_fullrun": True,
        "free_data_coverage": {"known_gaps": []},
    }


def test_config_locks_clean_7y_and_blocks_proxy_windows() -> None:
    assert OFFICIAL_BACKTEST_WINDOW_YEARS == 7.0
    assert PROXY_8Y_10Y_EVIDENCE_BLOCKED is True
    assert PROXY_WINDOW_BLOCKER_REASON == "pit_universe_label_missing"


def test_clean_7y_window_passes_as_research_baseline() -> None:
    gate = evaluate_window_gate(
        {"start_date": "2019-06-03", "end_date": "2026-06-12", "years": 7.03},
        equity_window={"exists": True, "trading_day_count": 1770},
        data_readiness=ready_payload(),
        require_data_readiness=True,
    )
    assert gate["valid"] is True
    assert gate["evidence_window_label"] == "research_7y"
    assert gate["production_promotion_allowed"] is False


def test_dirty_8y_and_10y_proxy_windows_fail_without_pit_label() -> None:
    for years, start in ((8.03, "2018-06-01"), (10.01, "2016-06-01")):
        gate = evaluate_window_gate(
            {"start_date": start, "end_date": "2026-06-12", "years": years},
            equity_window={"exists": True, "trading_day_count": int(years * 252)},
            data_readiness=ready_payload(),
            require_data_readiness=True,
        )
        assert gate["valid"] is False
        assert "proxy_8y_10y_evidence_blocked_until_pit_universe_clean" in gate["reasons"]
        assert PROXY_WINDOW_BLOCKER_REASON in gate["reasons"]


def test_pit_clean_long_window_passes() -> None:
    gate = evaluate_window_gate(
        {"start_date": "2018-06-01", "end_date": "2026-06-12", "years": 8.03, "pit_universe_label_clean": True},
        equity_window={"exists": True, "trading_day_count": 2025},
        data_readiness=ready_payload(),
        require_data_readiness=True,
    )
    assert gate["valid"] is True
    assert gate["evidence_window_label"] == "pit_clean_long_window"


def test_workflow_rejects_long_window_without_pit_label() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "default: '7'" in text
    assert "pit_universe_label_clean" in text
    assert "proxy 8Y/10Y evidence is blocked until PIT universe is clean" in text
    assert "years > 7.05 and not pit_clean" in text


if __name__ == "__main__":
    test_config_locks_clean_7y_and_blocks_proxy_windows()
    test_clean_7y_window_passes_as_research_baseline()
    test_dirty_8y_and_10y_proxy_windows_fail_without_pit_label()
    test_pit_clean_long_window_passes()
    test_workflow_rejects_long_window_without_pit_label()
    print("seven_year_lock_smoke: PASS")
