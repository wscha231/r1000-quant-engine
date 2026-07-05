#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_latest_price_date_audit import stale_trading_days_between  # noqa: E402
from tools.verify_alphaops_fullrun_readiness import evaluate  # noqa: E402


def test_ready_price_audit_emits_fullrun_command() -> None:
    payload = evaluate(
        {
            "status": "ok",
            "stale_price_review": False,
            "stale_trading_days": 0,
            "stale_trading_days_threshold": 2,
            "latest_cached_bar_date": "2026-06-29",
            "benchmark_anchor_date": "2026-06-29",
            "audit_date": "2026-06-29",
            "per_ticker": {"SPY": "2026-06-29", "QQQ": "2026-06-29"},
        },
        today=pd.Timestamp("2026-06-29"),
    )
    assert payload["fullrun_ready"] is True
    assert payload["status"] == "ready"
    assert payload["next_action"] == "dispatch_full_rebuild_manual"
    assert "PHASE_MAIN_FAST_CRASH_HEDGE_ENABLED" not in payload["fullrun_command"]
    assert "PHASE_CONCENTRATED_CASHFUNDED_EARLY_ENTRY_ENABLED" in payload["fullrun_command"]
    assert payload["policy_payload_binding"]["frozen_payload_match"] is True
    assert "$envJsonForGh = $envJson -replace" in payload["fullrun_command"]
    assert "experiment_env_json=$envJsonForGh" in payload["fullrun_command"]
    assert payload["required_price_tickers"] == ["QQQ", "SPY"]
    assert payload["production_promotion_allowed"] is False
    assert payload["production_promotion_blocked_by_pit_false"] is True
    assert payload["public_display_allowed"] is False
    assert payload["live_trading_enabled"] is False


def test_old_audit_blocks_fullrun_even_if_status_ok() -> None:
    payload = evaluate(
        {
            "status": "ok",
            "stale_price_review": False,
            "stale_trading_days": 0,
            "benchmark_anchor_date": "2026-06-24",
            "audit_date": "2026-06-24",
            "per_ticker": {"SPY": "2026-06-24"},
        },
        today=pd.Timestamp("2026-06-29"),
    )
    assert payload["fullrun_ready"] is False
    assert "audit_record_stale" in payload["blockers"]
    assert payload["fullrun_command"] == ""


def test_weekend_gap_does_not_stale_fresh_market_audit() -> None:
    payload = evaluate(
        {
            "status": "ok",
            "stale_price_review": False,
            "stale_trading_days": 1,
            "stale_trading_days_threshold": 2,
            "latest_cached_bar_date": "2026-07-02",
            "benchmark_anchor_date": "2026-07-02",
            "audit_date": "2026-07-02",
            "per_ticker": {"SPY": "2026-07-02", "QQQ": "2026-07-02"},
        },
        today=pd.Timestamp("2026-07-05"),
    )
    assert payload["fullrun_ready"] is True
    assert payload["price_audit"]["audit_record_age_days"] == 0
    assert payload["price_audit"]["audit_record_age_calendar"] == "XNYS"
    assert "audit_record_stale" not in payload["blockers"]


def test_good_friday_gap_uses_xnys_calendar_not_weekdays() -> None:
    payload = evaluate(
        {
            "status": "ok",
            "stale_price_review": False,
            "stale_trading_days": 2,
            "stale_trading_days_threshold": 2,
            "latest_cached_bar_date": "2026-04-01",
            "benchmark_anchor_date": "2026-04-01",
            "audit_date": "2026-04-01",
            "per_ticker": {"SPY": "2026-04-01", "QQQ": "2026-04-01"},
        },
        today=pd.Timestamp("2026-04-06"),
        max_audit_age_days=2,
    )
    assert payload["fullrun_ready"] is True
    assert payload["price_audit"]["audit_record_age_days"] == 2
    assert "audit_record_stale" not in payload["blockers"]


def test_thanksgiving_gap_uses_xnys_calendar_not_weekdays() -> None:
    payload = evaluate(
        {
            "status": "ok",
            "stale_price_review": False,
            "stale_trading_days": 2,
            "stale_trading_days_threshold": 2,
            "latest_cached_bar_date": "2026-11-25",
            "benchmark_anchor_date": "2026-11-25",
            "audit_date": "2026-11-25",
            "per_ticker": {"SPY": "2026-11-25", "QQQ": "2026-11-25"},
        },
        today=pd.Timestamp("2026-11-30"),
        max_audit_age_days=2,
    )
    assert payload["fullrun_ready"] is True
    assert payload["price_audit"]["audit_record_age_days"] == 2
    assert "audit_record_stale" not in payload["blockers"]


def test_payload_mismatch_blocks_fullrun_identity() -> None:
    payload = evaluate(
        {
            "status": "ok",
            "stale_price_review": False,
            "stale_trading_days": 0,
            "benchmark_anchor_date": "2026-06-29",
            "latest_cached_bar_date": "2026-06-29",
            "audit_date": "2026-06-29",
            "per_ticker": {"SPY": "2026-06-29", "QQQ": "2026-06-29"},
        },
        env_payload={"R1000_MAIN_POST_SELECTION_TOP_N": "15"},
        today=pd.Timestamp("2026-06-29"),
    )
    assert payload["fullrun_ready"] is False
    assert "frozen_policy_payload_mismatch" in payload["blockers"]
    assert payload["policy_payload_binding"]["frozen_payload_match"] is False
    assert payload["fullrun_command"] == ""


def test_price_audit_stale_days_uses_xnys_holidays() -> None:
    assert stale_trading_days_between(pd.Timestamp("2026-07-02"), pd.Timestamp("2026-07-06")) == 1
    assert stale_trading_days_between(pd.Timestamp("2026-04-01"), pd.Timestamp("2026-04-06")) == 2
    assert stale_trading_days_between(pd.Timestamp("2026-11-25"), pd.Timestamp("2026-11-30")) == 2


def test_future_dated_price_blocks_fullrun() -> None:
    payload = evaluate(
        {
            "status": "ok",
            "stale_price_review": False,
            "stale_trading_days": 0,
            "benchmark_anchor_date": "2026-06-29",
            "audit_date": "2026-06-29",
            "per_ticker": {"SPY": "2026-06-30"},
        },
        today=pd.Timestamp("2026-06-29"),
    )
    assert payload["fullrun_ready"] is False
    assert "future_dated_prices" in payload["blockers"]


def test_missing_hedge_price_blocks_fullrun_when_hedge_env_enabled() -> None:
    payload = evaluate(
        {
            "status": "ok",
            "stale_price_review": False,
            "stale_trading_days": 0,
            "benchmark_anchor_date": "2026-06-29",
            "latest_cached_bar_date": "2026-06-29",
            "audit_date": "2026-06-29",
            "per_ticker": {"SPY": "2026-06-29", "QQQ": "2026-06-29"},
        },
        env_payload={"PHASE_MAIN_FAST_CRASH_HEDGE_ENABLED": "1"},
        today=pd.Timestamp("2026-06-29"),
    )
    assert payload["fullrun_ready"] is False
    assert "missing_required_env_price_tickers" in payload["blockers"]
    assert payload["missing_required_price_tickers"] == ["SH"]
    assert payload["fullrun_command"] == ""


def test_non_required_missing_ticker_does_not_block_fullrun() -> None:
    payload = evaluate(
        {
            "status": "ok",
            "stale_price_review": False,
            "stale_trading_days": 0,
            "benchmark_anchor_date": "2026-06-29",
            "latest_cached_bar_date": "2026-06-29",
            "audit_date": "2026-06-29",
            "missing_tickers": ["PAGS"],
            "per_ticker": {"SPY": "2026-06-29", "QQQ": "2026-06-29"},
        },
        today=pd.Timestamp("2026-06-29"),
    )
    assert payload["fullrun_ready"] is True
    assert "missing_required_env_price_tickers" not in payload["blockers"]


def test_custom_required_hedge_ticker_blocks_if_missing() -> None:
    payload = evaluate(
        {
            "status": "ok",
            "stale_price_review": False,
            "stale_trading_days": 0,
            "benchmark_anchor_date": "2026-06-29",
            "latest_cached_bar_date": "2026-06-29",
            "audit_date": "2026-06-29",
            "per_ticker": {"SPY": "2026-06-29", "QQQ": "2026-06-29", "SH": "2026-06-29"},
        },
        env_payload={
            "PHASE_MAIN_FAST_CRASH_HEDGE_ENABLED": "1",
            "R1000_MAIN_FAST_CRASH_HEDGE_TICKER": "PSQ",
        },
        today=pd.Timestamp("2026-06-29"),
    )
    assert payload["fullrun_ready"] is False
    assert payload["missing_required_price_tickers"] == ["PSQ"]


if __name__ == "__main__":
    test_ready_price_audit_emits_fullrun_command()
    test_old_audit_blocks_fullrun_even_if_status_ok()
    test_weekend_gap_does_not_stale_fresh_market_audit()
    test_good_friday_gap_uses_xnys_calendar_not_weekdays()
    test_thanksgiving_gap_uses_xnys_calendar_not_weekdays()
    test_payload_mismatch_blocks_fullrun_identity()
    test_price_audit_stale_days_uses_xnys_holidays()
    test_future_dated_price_blocks_fullrun()
    test_missing_hedge_price_blocks_fullrun_when_hedge_env_enabled()
    test_non_required_missing_ticker_does_not_block_fullrun()
    test_custom_required_hedge_ticker_blocks_if_missing()
    print("alphaops_fullrun_readiness_smoke: PASS")
