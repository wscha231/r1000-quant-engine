#!/usr/bin/env python3
"""Smoke for the P0a bull-regime stock-weight floor in the regime_capacity
overlay (tools/run_alphaops_vnext_policy_replay.py).

The 27498401423 IS attribution tagged concentrated 2021/2023 as
structural_underinvestment_bull: 5 names at ~11.5% each (57% invested) in a
bull regime, dragging IS-CAGR to ~21%. This overlay lifts thinned bull books
to a floor via capped water-filling, default OFF (env-gated, A/B-measurable
by the performance ledger).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.run_alphaops_vnext_policy_replay import (  # noqa: E402
    apply_regime_capacity_overlay,
    capped_proportional_fill,
)


def _clear_env() -> None:
    for k in (
        "PHASE_REGIME_CAPACITY_BULL_FLOOR_ENABLED",
        "PHASE_BULL_FLOOR_ENABLED",
        "R1000_CONC_GROSS_CAP_FLOOR",
        "R1000_MAIN_GROSS_CAP_FLOOR",
    ):
        os.environ.pop(k, None)


def test_water_fill_reaches_floor_under_caps() -> None:
    # 5 names at 0.115 each = 0.575 invested. Floor 0.85, caps 0.30.
    out = capped_proportional_fill([0.115] * 5, 0.85, [0.30] * 5)
    assert abs(sum(out) - 0.85) < 1e-9
    # uniform inputs -> uniform outputs ~0.17 each, all under the 0.30 cap
    assert all(abs(x - 0.17) < 1e-6 for x in out)


def test_water_fill_respects_per_name_ceiling() -> None:
    # one big name near its cap should clamp; deficit redistributes to others
    out = capped_proportional_fill([0.28, 0.10, 0.10], 0.85, [0.30, 0.30, 0.30])
    assert out[0] <= 0.30 + 1e-9
    assert abs(sum(out) - 0.85) < 1e-9
    assert out[1] > 0.10 and out[2] > 0.10


def test_water_fill_caps_below_target_returns_max_achievable() -> None:
    # ceilings can only reach 0.60 total but target is 0.85
    out = capped_proportional_fill([0.10, 0.10], 0.85, [0.30, 0.30])
    assert abs(sum(out) - 0.60) < 1e-9


def test_water_fill_noop_when_already_above_target() -> None:
    out = capped_proportional_fill([0.45, 0.45], 0.85, [0.50, 0.50])
    assert out == [0.45, 0.45]


def _bull_book() -> pd.DataFrame:
    # one rebalance date, 5 names at 11.5% in a bull regime + a cash row
    rows = []
    for i in range(5):
        rows.append({
            "rebalance_date": "2021-05-28", "ticker": f"AAA{i}", "weight": 0.115,
            "target_weight": 0.115, "regime_state": "bull", "selection_reason": "lane",
            "effective_single_weight_cap": 0.30,
        })
    rows.append({
        "rebalance_date": "2021-05-28", "ticker": "CASH", "weight": 0.425,
        "target_weight": 0.425, "regime_state": "bull", "selection_reason": "cash",
        "effective_single_weight_cap": 1.0,
    })
    return pd.DataFrame(rows)


def test_overlay_off_by_default_leaves_thin_book() -> None:
    _clear_env()
    book = _bull_book()
    out, summary, audit = apply_regime_capacity_overlay(book, portfolio_kind="concentrated")
    assert summary["bull_floor_enabled"] is False
    stock = out[~out["ticker"].isin(["CASH", "__CASH__"])]
    assert abs(stock["weight"].sum() - 0.575) < 1e-6  # unchanged
    assert summary["rebalance_dates_bull_floor_lifted"] == 0


def test_overlay_on_lifts_bull_book_to_floor() -> None:
    _clear_env()
    os.environ["PHASE_REGIME_CAPACITY_BULL_FLOOR_ENABLED"] = "1"
    try:
        book = _bull_book()
        out, summary, audit = apply_regime_capacity_overlay(book, portfolio_kind="concentrated")
        assert summary["bull_floor_enabled"] is True
        assert summary["rebalance_dates_bull_floor_lifted"] == 1
        stock = out[~out["ticker"].isin(["CASH", "__CASH__"])]
        # conc floor is 0.85 -> invested lifts from 0.575 to 0.85, cash drops to 0.15
        assert abs(stock["weight"].sum() - 0.85) < 1e-6
        cash = out[out["ticker"].isin(["CASH", "__CASH__"])]
        assert abs(float(cash["weight"].sum()) - 0.15) < 1e-6
        assert (out["regime_capacity_bull_floor_applied"]).any()
    finally:
        _clear_env()


def test_overlay_respects_concentrated_floor_env_override() -> None:
    _clear_env()
    os.environ["PHASE_REGIME_CAPACITY_BULL_FLOOR_ENABLED"] = "1"
    os.environ["R1000_CONC_GROSS_CAP_FLOOR"] = "0.70"
    try:
        book = _bull_book()
        out, summary, audit = apply_regime_capacity_overlay(book, portfolio_kind="concentrated")
        assert summary["bull_floor_enabled"] is True
        assert summary["bull_floor"] == 0.70
        assert summary["bull_floor_source"] == "env:R1000_CONC_GROSS_CAP_FLOOR"
        assert summary["rebalance_dates_bull_floor_lifted"] == 1
        stock = out[~out["ticker"].isin(["CASH", "__CASH__"])]
        assert abs(stock["weight"].sum() - 0.70) < 1e-6
        cash = out[out["ticker"].isin(["CASH", "__CASH__"])]
        assert abs(float(cash["weight"].sum()) - 0.30) < 1e-6
    finally:
        _clear_env()


def test_overlay_does_not_lift_in_bear_regime() -> None:
    _clear_env()
    os.environ["PHASE_REGIME_CAPACITY_BULL_FLOOR_ENABLED"] = "1"
    try:
        book = _bull_book()
        book["regime_state"] = "bear"  # bear -> conc multiplier 0.50 dampens, no lift
        out, summary, audit = apply_regime_capacity_overlay(book, portfolio_kind="concentrated")
        assert summary["rebalance_dates_bull_floor_lifted"] == 0
        stock = out[~out["ticker"].isin(["CASH", "__CASH__"])]
        # bear dampening 0.50 on 0.575 -> ~0.2875 invested, cash up
        assert stock["weight"].sum() < 0.575
    finally:
        _clear_env()


def test_overlay_skips_book_already_above_floor() -> None:
    _clear_env()
    os.environ["PHASE_REGIME_CAPACITY_BULL_FLOOR_ENABLED"] = "1"
    try:
        rows = [{"rebalance_date": "2021-05-28", "ticker": f"B{i}", "weight": 0.18,
                 "target_weight": 0.18, "regime_state": "bull", "selection_reason": "lane",
                 "effective_single_weight_cap": 0.30} for i in range(5)]  # 0.90 invested
        book = pd.DataFrame(rows)
        out, summary, audit = apply_regime_capacity_overlay(book, portfolio_kind="concentrated")
        # 0.90 already above the 0.85 conc floor -> no lift
        assert summary["rebalance_dates_bull_floor_lifted"] == 0
    finally:
        _clear_env()


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(tests)}/{len(tests)} passed")
