#!/usr/bin/env python3
"""Smoke for Stage T3 leader hysteresis (compute_conviction_hold_bonus).

Verifies the env+cfg toggle, the relaxed-gate logic, and the bonus
multiplier without exercising the full build_target_portfolio loop.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd


REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from r1000_config import EngineConfig  # noqa: E402
from r1000_signals import compute_conviction_hold_bonus  # noqa: E402


def _make_month() -> pd.DataFrame:
    """Synthesize a 5-row month. Three rows are prev-held; only one passes
    the strict AND-AND-AND-AND gate. With the relaxed gate, two of the
    prev-held rows pass."""
    return pd.DataFrame([
        # Prev-held + ALL conditions met (strict pass).
        {
            "ticker": "AAA",
            "minervini_momentum_alive_score": 0.5,  # > 0.3
            "relative_strength_composite": 0.5,    # > 0.0
            "broken_momentum_penalty": 0.0,        # < 0.3
        },
        # Prev-held + only RS strong (strict fails because momentum_alive < 0.3,
        # relaxed passes because rs_strong + not_broken + substantial all OK).
        {
            "ticker": "BBB",
            "minervini_momentum_alive_score": 0.0,
            "relative_strength_composite": 0.4,
            "broken_momentum_penalty": 0.0,
        },
        # Prev-held + only momentum_alive (strict fails because rs_strong = False,
        # relaxed passes).
        {
            "ticker": "CCC",
            "minervini_momentum_alive_score": 0.5,
            "relative_strength_composite": -0.1,
            "broken_momentum_penalty": 0.0,
        },
        # Prev-held but broken_momentum_penalty too high (both gates reject).
        {
            "ticker": "DDD",
            "minervini_momentum_alive_score": 0.5,
            "relative_strength_composite": 0.5,
            "broken_momentum_penalty": 0.6,
        },
        # Not prev-held at all.
        {
            "ticker": "EEE",
            "minervini_momentum_alive_score": 0.5,
            "relative_strength_composite": 0.5,
            "broken_momentum_penalty": 0.0,
        },
    ])


def _prev_w() -> dict[str, float]:
    return {"AAA": 0.05, "BBB": 0.04, "CCC": 0.03, "DDD": 0.05}


def _clear_env() -> None:
    os.environ.pop("PHASE_PHASE_T3_LEADER_HYSTERESIS_ENABLED", None)


def test_toggle_off_preserves_strict_gate_and_base_bonus() -> None:
    _clear_env()
    cfg = EngineConfig()
    cfg.phase_t3_leader_hysteresis_enabled = False
    bonus = compute_conviction_hold_bonus(_make_month(), _prev_w(), cfg)
    # Strict: only AAA passes (BBB, CCC fail one of momentum/rs; DDD broken).
    assert bonus.tolist() == [
        float(cfg.conviction_hold_seed_bonus),  # AAA
        0.0,  # BBB
        0.0,  # CCC
        0.0,  # DDD
        0.0,  # EEE (not prev-held)
    ]


def test_toggle_on_relaxes_gate_and_multiplies_bonus() -> None:
    _clear_env()
    cfg = EngineConfig()
    cfg.phase_t3_leader_hysteresis_enabled = True
    cfg.phase_t3_conviction_hold_bonus_multiplier = 4.0
    cfg.phase_t3_relax_conviction_gate = True
    bonus = compute_conviction_hold_bonus(_make_month(), _prev_w(), cfg)
    expected = float(cfg.conviction_hold_seed_bonus) * 4.0
    # Relaxed gate: AAA, BBB, CCC all pass (DDD still rejected, EEE not prev-held).
    assert bonus.tolist() == [expected, expected, expected, 0.0, 0.0]


def test_env_var_alone_activates_toggle() -> None:
    _clear_env()
    cfg = EngineConfig()
    cfg.phase_t3_leader_hysteresis_enabled = False  # cfg off
    os.environ["PHASE_PHASE_T3_LEADER_HYSTERESIS_ENABLED"] = "1"  # env on
    try:
        bonus = compute_conviction_hold_bonus(_make_month(), _prev_w(), cfg)
        expected = float(cfg.conviction_hold_seed_bonus) * 4.0
        assert bonus.iloc[1] == expected  # BBB only passes under relaxed gate
    finally:
        _clear_env()


def test_no_prev_holdings_returns_zero_series() -> None:
    _clear_env()
    cfg = EngineConfig()
    cfg.phase_t3_leader_hysteresis_enabled = True
    bonus = compute_conviction_hold_bonus(_make_month(), None, cfg)
    assert bonus.tolist() == [0.0] * 5
    bonus_empty = compute_conviction_hold_bonus(_make_month(), {}, cfg)
    assert bonus_empty.tolist() == [0.0] * 5


def test_strict_gate_when_relax_flag_false() -> None:
    _clear_env()
    cfg = EngineConfig()
    cfg.phase_t3_leader_hysteresis_enabled = True
    cfg.phase_t3_relax_conviction_gate = False  # strict gate even when enabled
    cfg.phase_t3_conviction_hold_bonus_multiplier = 4.0
    bonus = compute_conviction_hold_bonus(_make_month(), _prev_w(), cfg)
    expected = float(cfg.conviction_hold_seed_bonus) * 4.0
    # Only AAA passes the strict AND-AND-AND-AND gate -- multiplier still
    # applies because t3_enabled is true.
    assert bonus.tolist() == [expected, 0.0, 0.0, 0.0, 0.0]


def test_substantial_position_threshold_excludes_tiny_prior_weights() -> None:
    _clear_env()
    cfg = EngineConfig()
    cfg.phase_t3_leader_hysteresis_enabled = True
    cfg.phase_t3_relax_conviction_gate = True
    # AAA prev weight at 1% — below the 2% substantial floor.
    prev_w = {"AAA": 0.01, "BBB": 0.04}
    bonus = compute_conviction_hold_bonus(_make_month(), prev_w, cfg)
    assert bonus.iloc[0] == 0.0  # AAA rejected by substantial gate
    assert bonus.iloc[1] > 0.0   # BBB still passes


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            print(f"PASS {name}")
            fn()
    print("\n6/6 passed")
