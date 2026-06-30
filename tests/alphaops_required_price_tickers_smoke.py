#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.alphaops_required_price_tickers import parse_env_payload, required_price_tickers_for_env  # noqa: E402


def test_default_required_tickers() -> None:
    assert required_price_tickers_for_env({}) == ["QQQ", "SPY"]


def test_fast_crash_hedge_adds_sh() -> None:
    assert required_price_tickers_for_env({"PHASE_MAIN_FAST_CRASH_HEDGE_ENABLED": "1"}) == ["QQQ", "SH", "SPY"]


def test_custom_hedge_ticker_and_dedupe() -> None:
    tickers = required_price_tickers_for_env(
        {
            "PHASE_MAIN_FAST_CRASH_HEDGE_ENABLED": "true",
            "R1000_MAIN_FAST_CRASH_HEDGE_TICKER": "psq",
            "R1000_MAIN_FAST_CRASH_HEDGE_BENCHMARK": "qqq",
        }
    )
    assert tickers == ["PSQ", "QQQ", "SPY"]


def test_cash_removed() -> None:
    tickers = required_price_tickers_for_env(
        {
            "PHASE_MAIN_FAST_CRASH_HEDGE_ENABLED": "1",
            "R1000_MAIN_FAST_CRASH_HEDGE_TICKER": "CASH",
        }
    )
    assert tickers == ["QQQ", "SPY"]


def test_process_env_flag_is_supported() -> None:
    old = os.environ.get("PHASE_MAIN_FAST_CRASH_HEDGE_ENABLED")
    try:
        os.environ["PHASE_MAIN_FAST_CRASH_HEDGE_ENABLED"] = "1"
        assert required_price_tickers_for_env({}) == ["QQQ", "SH", "SPY"]
    finally:
        if old is None:
            os.environ.pop("PHASE_MAIN_FAST_CRASH_HEDGE_ENABLED", None)
        else:
            os.environ["PHASE_MAIN_FAST_CRASH_HEDGE_ENABLED"] = old


def test_powershell_escaped_json_payload() -> None:
    payload = parse_env_payload('{\\"PHASE_MAIN_FAST_CRASH_HEDGE_ENABLED\\":\\"1\\"}')
    assert required_price_tickers_for_env(payload) == ["QQQ", "SH", "SPY"]


def test_powershell_loose_json_payload() -> None:
    payload = parse_env_payload("{PHASE_MAIN_FAST_CRASH_HEDGE_ENABLED:1}")
    assert required_price_tickers_for_env(payload) == ["QQQ", "SH", "SPY"]


if __name__ == "__main__":
    test_default_required_tickers()
    test_fast_crash_hedge_adds_sh()
    test_custom_hedge_ticker_and_dedupe()
    test_cash_removed()
    test_process_env_flag_is_supported()
    test_powershell_escaped_json_payload()
    test_powershell_loose_json_payload()
    print("alphaops_required_price_tickers_smoke: PASS")
