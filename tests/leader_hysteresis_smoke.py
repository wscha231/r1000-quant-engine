#!/usr/bin/env python3
"""Smoke for Stage T3 leader hysteresis (compute_conviction_hold_bonus).

Covers: toggle OFF (unchanged strict gate + flat bonus), toggle ON sigma-gate
(the default merged behaviour — healthy held names handicapped by
new_entry_sigma * sigma(score), broken held names by broken_replace_sigma),
the legacy flat-multiplier knob, env-var activation, and the substantial-
position floor.
"""
from __future__ import annotations

import math
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
    """5-row month with a well-defined score dispersion.

    score = [1.0, 0.8, 0.6, 0.4, 0.2] -> mean 0.6, population sigma sqrt(0.08).
    Conviction gate inputs chosen so that under the relaxed gate AAA/BBB/CCC
    are healthy held, DDD is broken held, EEE is not held.
    """
    return pd.DataFrame([
        {"ticker": "AAA", "score": 1.0, "minervini_momentum_alive_score": 0.5, "relative_strength_composite": 0.5, "broken_momentum_penalty": 0.0},
        {"ticker": "BBB", "score": 0.8, "minervini_momentum_alive_score": 0.0, "relative_strength_composite": 0.4, "broken_momentum_penalty": 0.0},
        {"ticker": "CCC", "score": 0.6, "minervini_momentum_alive_score": 0.5, "relative_strength_composite": -0.1, "broken_momentum_penalty": 0.0},
        {"ticker": "DDD", "score": 0.4, "minervini_momentum_alive_score": 0.5, "relative_strength_composite": 0.5, "broken_momentum_penalty": 0.6},
        {"ticker": "EEE", "score": 0.2, "minervini_momentum_alive_score": 0.5, "relative_strength_composite": 0.5, "broken_momentum_penalty": 0.0},
    ])


def _prev_w() -> dict[str, float]:
    return {"AAA": 0.05, "BBB": 0.04, "CCC": 0.03, "DDD": 0.05}


def _sigma() -> float:
    s = pd.Series([1.0, 0.8, 0.6, 0.4, 0.2])
    return float(s.std(ddof=0))


def _clear_env() -> None:
    os.environ.pop("PHASE_PHASE_T3_LEADER_HYSTERESIS_ENABLED", None)
    os.environ.pop("PHASE_T3_LEADER_HYSTERESIS_ENABLED", None)


def test_toggle_off_preserves_strict_gate_and_base_bonus() -> None:
    _clear_env()
    cfg = EngineConfig()
    cfg.phase_t3_leader_hysteresis_enabled = False
    bonus = compute_conviction_hold_bonus(_make_month(), _prev_w(), cfg)
    # Strict AND-AND-AND-AND: only AAA passes; flat 0.35 bonus.
    assert bonus.tolist() == [float(cfg.conviction_hold_seed_bonus), 0.0, 0.0, 0.0, 0.0]


def test_sigma_gate_default_handicaps_healthy_and_broken() -> None:
    _clear_env()
    cfg = EngineConfig()
    cfg.phase_t3_leader_hysteresis_enabled = True
    # sigma_gate default True, new_entry 0.75, broken 0.35.
    bonus = compute_conviction_hold_bonus(_make_month(), _prev_w(), cfg)
    sigma = _sigma()
    healthy = sigma * 0.75
    broken = sigma * 0.35
    # AAA/BBB/CCC healthy held -> 0.75 sigma; DDD broken held -> 0.35 sigma;
    # EEE not held -> 0.
    assert math.isclose(bonus.iloc[0], healthy, rel_tol=1e-9)
    assert math.isclose(bonus.iloc[1], healthy, rel_tol=1e-9)
    assert math.isclose(bonus.iloc[2], healthy, rel_tol=1e-9)
    assert math.isclose(bonus.iloc[3], broken, rel_tol=1e-9)
    assert bonus.iloc[4] == 0.0
    # The healthy handicap must exceed the broken one (broken is cheaper to replace).
    assert healthy > broken > 0.0


def test_flat_multiplier_knob_when_sigma_gate_off() -> None:
    _clear_env()
    cfg = EngineConfig()
    cfg.phase_t3_leader_hysteresis_enabled = True
    cfg.phase_t3_sigma_gate = False
    cfg.phase_t3_conviction_hold_bonus_multiplier = 4.0
    bonus = compute_conviction_hold_bonus(_make_month(), _prev_w(), cfg)
    expected = float(cfg.conviction_hold_seed_bonus) * 4.0
    # Relaxed gate (healthy held): AAA/BBB/CCC get the flat multiplied bonus;
    # DDD broken gets nothing in the flat-knob path; EEE not held -> 0.
    assert bonus.tolist() == [expected, expected, expected, 0.0, 0.0]


def test_either_env_var_spelling_activates_sigma_gate() -> None:
    # Both the double-PHASE form and the natural form must activate T3, so the
    # A/B run never silently no-ops on a human-typed env name.
    cfg = EngineConfig()
    cfg.phase_t3_leader_hysteresis_enabled = False  # cfg off
    healthy = _sigma() * 0.75
    for env_name in ("PHASE_PHASE_T3_LEADER_HYSTERESIS_ENABLED", "PHASE_T3_LEADER_HYSTERESIS_ENABLED"):
        _clear_env()
        os.environ[env_name] = "1"
        try:
            bonus = compute_conviction_hold_bonus(_make_month(), _prev_w(), cfg)
            assert math.isclose(bonus.iloc[1], healthy, rel_tol=1e-9), f"{env_name} did not activate T3"
        finally:
            _clear_env()


def test_no_prev_holdings_returns_zero_series() -> None:
    _clear_env()
    cfg = EngineConfig()
    cfg.phase_t3_leader_hysteresis_enabled = True
    assert compute_conviction_hold_bonus(_make_month(), None, cfg).tolist() == [0.0] * 5
    assert compute_conviction_hold_bonus(_make_month(), {}, cfg).tolist() == [0.0] * 5


def test_degenerate_sigma_falls_back_to_flat_bonus() -> None:
    _clear_env()
    cfg = EngineConfig()
    cfg.phase_t3_leader_hysteresis_enabled = True
    df = _make_month()
    df["score"] = 0.5  # zero dispersion -> degenerate sigma
    bonus = compute_conviction_hold_bonus(df, _prev_w(), cfg)
    # Fallback: healthy held get the flat conviction bonus, broken get half.
    assert math.isclose(bonus.iloc[0], float(cfg.conviction_hold_seed_bonus), rel_tol=1e-9)
    assert math.isclose(bonus.iloc[3], float(cfg.conviction_hold_seed_bonus) * 0.5, rel_tol=1e-9)


def test_substantial_position_threshold_excludes_tiny_prior_weights() -> None:
    _clear_env()
    cfg = EngineConfig()
    cfg.phase_t3_leader_hysteresis_enabled = True
    prev_w = {"AAA": 0.01, "BBB": 0.04}  # AAA below the 2% substantial floor
    bonus = compute_conviction_hold_bonus(_make_month(), prev_w, cfg)
    assert bonus.iloc[0] == 0.0  # AAA rejected by substantial gate
    assert bonus.iloc[1] > 0.0   # BBB still passes


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        print(f"PASS {fn.__name__}")
        fn()
    print(f"\n{len(tests)}/{len(tests)} passed")
