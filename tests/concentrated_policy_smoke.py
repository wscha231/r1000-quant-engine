#!/usr/bin/env python3
"""Smoke checks for concentrated sleeve policy audit helpers."""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from r1000_concentrated_policy import (
    audit_concentrated_portfolio,
    entry_gate_flags,
    entry_quality_proxy,
    risk_gate_flags,
)


def test_entry_quality_fallback_from_gate_pass() -> None:
    row = {
        "ticker": "WIN",
        "concentrated_entry_quality_gate_pass": True,
        "price_above_ma50": 1,
        "price_above_ma200": 1,
        "theme_phase_primary": "maturing",
    }
    score, source = entry_quality_proxy(row)
    flags = entry_gate_flags(row)
    assert score >= 0.70
    assert source == "concentrated_entry_quality_gate_pass"
    assert all(flags.values()), flags


def test_entry_quality_fallback_blocks_weak_rows() -> None:
    row = {
        "ticker": "WEAK",
        "price_above_ma50": 1,
        "price_above_ma200": 1,
        "theme_phase_primary": "maturing",
    }
    score, source = entry_quality_proxy(row)
    flags = entry_gate_flags(row)
    assert source == "fallback_proxy"
    assert score < 0.70
    assert flags["price_above_ma50_ok"]
    assert flags["price_above_ma200_ok"]
    assert not flags["entry_quality_ok"]


def test_audit_surfaces_entry_quality_source() -> None:
    holdings = [
        {
            "ticker": "WIN",
            "weight": 0.20,
            "sector": "Technology",
            "price_above_ma50": 1,
            "price_above_ma200": 1,
            "concentrated_entry_quality_gate_pass": True,
            "fundamental_reliability_score": 0.8,
            "rs_acceleration_score": 0.1,
        }
    ]
    audit = audit_concentrated_portfolio(holdings, regime_state="neutral")
    row = audit["rows"][0]
    assert row["entry_gate_pass"] is True
    assert row["entry_quality_proxy"] >= 0.70
    assert row["entry_quality_source"] == "concentrated_entry_quality_gate_pass"


def test_monster_early_override_allows_low_entry_quality() -> None:
    row = {
        "ticker": "MONSTER",
        "entry_quality_score": 0.20,
        "portfolio_monster_early_score": 0.80,
        "portfolio_risk_entry_block_score": 0.20,
        "price_above_ma50": 1,
        "price_above_ma200": 1,
        "theme_phase_primary": "early",
        "fundamental_reliability_score": 0.20,
        "rs_acceleration_score": -0.75,
    }
    entry_flags = entry_gate_flags(row)
    risk_flags = risk_gate_flags(row)
    assert entry_flags["entry_quality_ok"]
    assert all(entry_flags.values()), entry_flags
    assert risk_flags["rs_not_decaying"]
    assert risk_flags["fundamental_reliability_ok"]
    assert all(risk_flags.values()), risk_flags


def main() -> int:
    test_entry_quality_fallback_from_gate_pass()
    test_entry_quality_fallback_blocks_weak_rows()
    test_audit_surfaces_entry_quality_source()
    test_monster_early_override_allows_low_entry_quality()
    print("concentrated policy smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
