#!/usr/bin/env python3
"""Smoke for concentrated T3 hysteresis helper (Stage T3 carried into the
concentrated backtester selector via `apply_concentrated_t3_hysteresis`).

Mirrors the Main `compute_conviction_hold_bonus` semantics:
- toggle OFF (default): no-op, pool returned unchanged
- toggle ON + prev_w: held names re-ranked with sigma-scaled bonus on
  concentrated_score, healthy = 0.75 sigma, broken = 0.35 sigma
- substantial-position floor (prev weight ≥ 2%)
- degenerate sigma / empty / no prev → no-op
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
from r1000_pipeline import apply_concentrated_t3_hysteresis  # noqa: E402


def _pool() -> pd.DataFrame:
    return pd.DataFrame([
        {"ticker": "NEW",  "score": 5.0, "concentrated_score": 5.0, "broken_momentum_penalty": 0.0},
        {"ticker": "HELD", "score": 4.0, "concentrated_score": 4.0, "broken_momentum_penalty": 0.0},
        {"ticker": "LOW",  "score": 3.0, "concentrated_score": 3.0, "broken_momentum_penalty": 0.0},
        {"ticker": "MIN",  "score": 2.0, "concentrated_score": 2.0, "broken_momentum_penalty": 0.0},
    ])


def _sigma(scores: list[float]) -> float:
    s = pd.Series(scores)
    return float(s.std(ddof=0))


def _clear_env() -> None:
    os.environ.pop("PHASE_PHASE_T3_LEADER_HYSTERESIS_ENABLED", None)
    os.environ.pop("PHASE_T3_LEADER_HYSTERESIS_ENABLED", None)


def test_toggle_off_returns_pool_unchanged() -> None:
    _clear_env()
    cfg = EngineConfig()
    cfg.phase_t3_leader_hysteresis_enabled = False
    out = apply_concentrated_t3_hysteresis(_pool(), {"HELD": 0.30}, cfg)
    assert out["ticker"].tolist() == ["NEW", "HELD", "LOW", "MIN"]
    assert out["concentrated_score"].tolist() == [5.0, 4.0, 3.0, 2.0]


def test_toggle_on_reranks_held_via_sigma_handicap() -> None:
    _clear_env()
    cfg = EngineConfig()
    cfg.phase_t3_leader_hysteresis_enabled = True
    out = apply_concentrated_t3_hysteresis(_pool(), {"HELD": 0.30}, cfg)
    sigma = _sigma([5, 4, 3, 2])
    # HELD's adjusted score: 4 + 0.75*sigma = 4 + 0.838 ≈ 4.84 (still below NEW=5)
    # So order: NEW, HELD, LOW, MIN; HELD's stored score has the bonus applied.
    assert out["ticker"].tolist() == ["NEW", "HELD", "LOW", "MIN"]
    held_row = out[out["ticker"] == "HELD"].iloc[0]
    assert math.isclose(held_row["concentrated_score"], 4.0 + 0.75 * sigma, rel_tol=1e-9)
    new_row = out[out["ticker"] == "NEW"].iloc[0]
    assert math.isclose(new_row["concentrated_score"], 5.0, rel_tol=1e-9)


def test_broken_held_gets_smaller_bonus_and_loses_to_fresh_candidate() -> None:
    _clear_env()
    cfg = EngineConfig()
    cfg.phase_t3_leader_hysteresis_enabled = True
    pool = pd.DataFrame([
        {"ticker": "NEW",    "score": 5.0, "concentrated_score": 5.0, "broken_momentum_penalty": 0.0},
        {"ticker": "NEW2",   "score": 4.5, "concentrated_score": 4.5, "broken_momentum_penalty": 0.0},
        {"ticker": "BROKEN", "score": 4.0, "concentrated_score": 4.0, "broken_momentum_penalty": 0.6},
        {"ticker": "LOW",    "score": 3.0, "concentrated_score": 3.0, "broken_momentum_penalty": 0.0},
    ])
    sigma = _sigma([5, 4.5, 4, 3])
    out = apply_concentrated_t3_hysteresis(pool, {"BROKEN": 0.30}, cfg)
    # BROKEN handicap: 0.35 * sigma; expected adjusted = 4 + 0.35*sigma ≈ 4.26.
    # Still loses to NEW2 (4.5). Order: NEW, NEW2, BROKEN, LOW.
    assert out["ticker"].tolist() == ["NEW", "NEW2", "BROKEN", "LOW"]
    broken_row = out[out["ticker"] == "BROKEN"].iloc[0]
    assert math.isclose(broken_row["concentrated_score"], 4.0 + 0.35 * sigma, rel_tol=1e-9)


def test_substantial_floor_excludes_tiny_prev_weights() -> None:
    _clear_env()
    cfg = EngineConfig()
    cfg.phase_t3_leader_hysteresis_enabled = True
    # HELD prev weight 1% — below the 2% substantial floor → no bonus.
    out = apply_concentrated_t3_hysteresis(_pool(), {"HELD": 0.01}, cfg)
    held_row = out[out["ticker"] == "HELD"].iloc[0]
    assert math.isclose(held_row["concentrated_score"], 4.0, rel_tol=1e-9)


def test_empty_prev_or_pool_is_noop() -> None:
    _clear_env()
    cfg = EngineConfig()
    cfg.phase_t3_leader_hysteresis_enabled = True
    assert apply_concentrated_t3_hysteresis(_pool(), None, cfg)["ticker"].tolist() == ["NEW", "HELD", "LOW", "MIN"]
    assert apply_concentrated_t3_hysteresis(_pool(), {}, cfg)["ticker"].tolist() == ["NEW", "HELD", "LOW", "MIN"]
    empty = _pool().iloc[0:0]
    assert apply_concentrated_t3_hysteresis(empty, {"HELD": 0.3}, cfg).empty


def test_either_env_spelling_activates() -> None:
    cfg = EngineConfig()
    cfg.phase_t3_leader_hysteresis_enabled = False
    sigma = _sigma([5, 4, 3, 2])
    for env_name in ("PHASE_PHASE_T3_LEADER_HYSTERESIS_ENABLED", "PHASE_T3_LEADER_HYSTERESIS_ENABLED"):
        _clear_env()
        os.environ[env_name] = "1"
        try:
            out = apply_concentrated_t3_hysteresis(_pool(), {"HELD": 0.30}, cfg)
            held_row = out[out["ticker"] == "HELD"].iloc[0]
            assert math.isclose(held_row["concentrated_score"], 4.0 + 0.75 * sigma, rel_tol=1e-9), env_name
        finally:
            _clear_env()


def test_degenerate_sigma_is_noop() -> None:
    _clear_env()
    cfg = EngineConfig()
    cfg.phase_t3_leader_hysteresis_enabled = True
    flat = pd.DataFrame([
        {"ticker": "A", "score": 1.0, "concentrated_score": 1.0, "broken_momentum_penalty": 0.0},
        {"ticker": "B", "score": 1.0, "concentrated_score": 1.0, "broken_momentum_penalty": 0.0},
    ])
    out = apply_concentrated_t3_hysteresis(flat, {"A": 0.30}, cfg)
    assert out["concentrated_score"].tolist() == [1.0, 1.0]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        print(f"PASS {fn.__name__}")
        fn()
    print(f"\n{len(tests)}/{len(tests)} passed")
