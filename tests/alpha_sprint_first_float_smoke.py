#!/usr/bin/env python3
"""Smoke test for r1000_alpha_sprint._first_float NaN/inf handling.

Regression guard: the pre-fix version returned safe_float(NaN, default)
= 0.0 immediately, which silently failed alpha_sprint's universe filter
(market_cap >= 1B, price >= 10) in every backtest month. This test
locks in the correct behavior: NaN/inf must fall through to the next
key in the tuple, genuine zero must be accepted as a real value, and
empty/None inputs must skip to the next key.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from r1000_alpha_sprint import _first_float  # noqa: E402


def test_nan_falls_through_to_next_key() -> None:
    out = _first_float({"market_cap_live": float("nan"), "mktcap": 41_953_802_631.5}, ("market_cap_live", "mktcap"))
    assert abs(out - 41_953_802_631.5) < 0.01, out


def test_inf_falls_through_to_next_key() -> None:
    out = _first_float({"market_cap_live": float("inf"), "mktcap": 41_953_802_631.5}, ("market_cap_live", "mktcap"))
    assert abs(out - 41_953_802_631.5) < 0.01, out


def test_none_falls_through() -> None:
    out = _first_float({"market_cap_live": None, "mktcap": 41_953_802_631.5}, ("market_cap_live", "mktcap"))
    assert abs(out - 41_953_802_631.5) < 0.01, out


def test_empty_string_falls_through() -> None:
    out = _first_float({"market_cap_live": "", "mktcap": 41_953_802_631.5}, ("market_cap_live", "mktcap"))
    assert abs(out - 41_953_802_631.5) < 0.01, out


def test_first_key_finite_used_when_present() -> None:
    out = _first_float({"market_cap_live": 5_000_000_000.0, "mktcap": 41_953_802_631.5}, ("market_cap_live", "mktcap"))
    assert abs(out - 5_000_000_000.0) < 0.01, out


def test_genuine_zero_accepted_not_fallback() -> None:
    # Distinguishes "value is genuinely 0" from "value is missing/NaN".
    out = _first_float({"market_cap_live": 0.0, "mktcap": 41_953_802_631.5}, ("market_cap_live", "mktcap"))
    assert out == 0.0, out


def test_unparseable_string_falls_through() -> None:
    out = _first_float({"market_cap_live": "badstring", "mktcap": 41_953_802_631.5}, ("market_cap_live", "mktcap"))
    assert abs(out - 41_953_802_631.5) < 0.01, out


def test_all_keys_unusable_returns_default() -> None:
    out = _first_float({"market_cap_live": float("nan"), "mktcap": None}, ("market_cap_live", "mktcap"))
    assert out == 0.0, out


def test_custom_default_returned_when_all_unusable() -> None:
    out = _first_float({"market_cap_live": float("nan")}, ("market_cap_live",), default=-1.0)
    assert out == -1.0, out


def test_three_key_fallback_chain() -> None:
    # Tier-3 fallback: live -> latest -> historical.
    row = {"market_cap_live": float("nan"), "market_cap_latest": float("nan"), "mktcap": 100.0}
    out = _first_float(row, ("market_cap_live", "market_cap_latest", "mktcap"))
    assert out == 100.0, out


def main() -> int:
    test_nan_falls_through_to_next_key()
    test_inf_falls_through_to_next_key()
    test_none_falls_through()
    test_empty_string_falls_through()
    test_first_key_finite_used_when_present()
    test_genuine_zero_accepted_not_fallback()
    test_unparseable_string_falls_through()
    test_all_keys_unusable_returns_default()
    test_custom_default_returned_when_all_unusable()
    test_three_key_fallback_chain()
    print("alpha_sprint_first_float_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
