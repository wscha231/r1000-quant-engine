#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_alphaops_vnext_policy_replay import apply_concentrated_whipsaw_sell_throttle  # noqa: E402


ENV_KEY = "PHASE_CONCENTRATED_WHIPSAW_SELL_THROTTLE_ENABLED"


def base_rows() -> list[dict[str, object]]:
    return [
        {
            "ticker": "KEEP",
            "weight": 0.05,
            "target_weight": 0.05,
            "prior_weight": 0.20,
            "holding_state": "HOLD",
            "hold_replace_decision": "keep_prior_holding",
            "leader_tier": "DUAL_LEADER",
            "rs_benchmark_3m": 0.10,
            "rs_benchmark_6m": 0.15,
            "price_above_ma200": 1.0,
            "actual_results_score": 0.60,
            "crisis_state": "GREEN",
            "primary_lane": "MARKET_LEADER",
            "selection_reason": "baseline",
        },
        {
            "ticker": "FUND1",
            "weight": 0.25,
            "target_weight": 0.25,
            "prior_weight": 0.0,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "leader_tier": "DUAL_LEADER",
            "rs_benchmark_3m": 0.20,
            "rs_benchmark_6m": 0.30,
            "price_above_ma200": 1.0,
            "actual_results_score": 0.0,
            "crisis_state": "GREEN",
            "primary_lane": "MARKET_LEADER",
        },
        {
            "ticker": "FUND2",
            "weight": 0.20,
            "target_weight": 0.20,
            "prior_weight": 0.0,
            "holding_state": "NEW",
            "hold_replace_decision": "new_entry",
            "leader_tier": "SECTOR_LEADER",
            "rs_benchmark_3m": 0.10,
            "rs_benchmark_6m": 0.20,
            "price_above_ma200": 1.0,
            "actual_results_score": 0.0,
            "crisis_state": "GREEN",
            "primary_lane": "MARKET_LEADER",
        },
        {"ticker": "CASH", "weight": 0.50, "target_weight": 0.50, "primary_lane": "CASH"},
    ]


def total(rows: list[dict[str, object]]) -> float:
    return round(sum(float(row.get("weight", 0.0) or 0.0) for row in rows), 10)


def by_ticker(rows: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    return {str(row.get("ticker")): row for row in rows}


def test_default_off_noop() -> None:
    os.environ.pop(ENV_KEY, None)
    rows = base_rows()
    out = apply_concentrated_whipsaw_sell_throttle(rows, "concentrated")
    assert out == rows


def test_main_noop_even_when_enabled() -> None:
    os.environ[ENV_KEY] = "1"
    try:
        rows = base_rows()
        out = apply_concentrated_whipsaw_sell_throttle(rows, "main")
        assert out == rows
    finally:
        os.environ.pop(ENV_KEY, None)


def test_enabled_preserves_gross_and_throttles_intact_prior_leader() -> None:
    os.environ[ENV_KEY] = "1"
    try:
        rows = base_rows()
        before_total = total(rows)
        before_cash = by_ticker(rows)["CASH"]["weight"]
        out = apply_concentrated_whipsaw_sell_throttle(rows, "concentrated")
        after = by_ticker(out)

        assert total(out) == before_total
        assert after["CASH"]["weight"] == before_cash
        assert round(float(after["KEEP"]["weight"]), 10) == 0.13
        assert after["KEEP"]["concentrated_whipsaw_sell_throttle_status"] == "applied"
        assert after["FUND1"]["concentrated_whipsaw_sell_throttle_status"] == "funding_source"
        assert after["FUND2"]["concentrated_whipsaw_sell_throttle_status"] == "funding_source"
        assert "|concentrated_whipsaw_sell_throttle" in str(after["KEEP"]["selection_reason"])
    finally:
        os.environ.pop(ENV_KEY, None)


def test_enabled_blocks_when_actual_results_not_positive() -> None:
    os.environ[ENV_KEY] = "1"
    try:
        rows = base_rows()
        rows[0]["actual_results_score"] = 0.0
        out = apply_concentrated_whipsaw_sell_throttle(rows, "concentrated")
        after = by_ticker(out)
        assert after["KEEP"]["weight"] == 0.05
        assert after["KEEP"]["concentrated_whipsaw_sell_throttle_status"] == "not_candidate"
        assert after["KEEP"]["concentrated_whipsaw_sell_throttle_predicate"] == "actual_results_not_positive"
    finally:
        os.environ.pop(ENV_KEY, None)


if __name__ == "__main__":
    test_default_off_noop()
    test_main_noop_even_when_enabled()
    test_enabled_preserves_gross_and_throttles_intact_prior_leader()
    test_enabled_blocks_when_actual_results_not_positive()
    print("concentrated_whipsaw_sell_throttle_smoke: PASS")
