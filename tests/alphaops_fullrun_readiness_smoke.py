#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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
    assert "PHASE_AI_CAPEX_MOMENTUM_TILT_ENABLED" in payload["fullrun_command"]
    assert "PHASE_MAIN_FAST_CRASH_HEDGE_ENABLED" in payload["fullrun_command"]
    assert "PHASE_CONCENTRATED_CASHFUNDED_EARLY_ENTRY_ENABLED" in payload["fullrun_command"]
    assert payload["production_promotion_allowed"] is False


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


if __name__ == "__main__":
    test_ready_price_audit_emits_fullrun_command()
    test_old_audit_blocks_fullrun_even_if_status_ok()
    test_future_dated_price_blocks_fullrun()
    print("alphaops_fullrun_readiness_smoke: PASS")
