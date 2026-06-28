#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_alphaops_vnext_policy_replay import apply_main_ai_capex_momentum_tilt  # noqa: E402


def _weighted() -> list[dict[str, object]]:
    return [
        {
            "ticker": "MEM",
            "Name": "Memory Leader",
            "sector": "Information Technology",
            "industry_group": "Semiconductor Memory",
            "theme": "HBM memory tight supply",
            "target_weight": 0.10,
            "weight": 0.10,
            "effective_single_weight_cap": 0.12,
            "rs_benchmark_3m": 0.20,
        },
        {
            "ticker": "NET",
            "Name": "Networking Leader",
            "sector": "Information Technology",
            "industry_group": "Communication Equipment",
            "theme": "AI ethernet networking",
            "target_weight": 0.10,
            "weight": 0.10,
            "effective_single_weight_cap": 0.12,
            "rs_benchmark_3m": 0.18,
        },
        {
            "ticker": "OTHER",
            "Name": "Other Stock",
            "sector": "Industrials",
            "industry_group": "Machinery",
            "target_weight": 0.20,
            "weight": 0.20,
            "effective_single_weight_cap": 0.50,
            "rs_benchmark_3m": -0.02,
        },
    ]


def test_default_off_returns_exact_input() -> None:
    os.environ.pop("PHASE_AI_CAPEX_MOMENTUM_TILT_ENABLED", None)
    rows = _weighted()
    out = apply_main_ai_capex_momentum_tilt(rows, "main")
    assert out == rows


def test_enabled_main_only_preserves_gross_and_increases_ai_weights() -> None:
    old = os.environ.get("PHASE_AI_CAPEX_MOMENTUM_TILT_ENABLED")
    os.environ["PHASE_AI_CAPEX_MOMENTUM_TILT_ENABLED"] = "1"
    try:
        rows = _weighted()
        out = apply_main_ai_capex_momentum_tilt(rows, "main")
    finally:
        if old is None:
            os.environ.pop("PHASE_AI_CAPEX_MOMENTUM_TILT_ENABLED", None)
        else:
            os.environ["PHASE_AI_CAPEX_MOMENTUM_TILT_ENABLED"] = old

    before = sum(float(row["target_weight"]) for row in rows)
    after = sum(float(row["target_weight"]) for row in out)
    assert round(before, 10) == round(after, 10)
    mem = next(row for row in out if row["ticker"] == "MEM")
    net = next(row for row in out if row["ticker"] == "NET")
    other = next(row for row in out if row["ticker"] == "OTHER")
    assert float(mem["target_weight"]) > 0.10
    assert float(net["target_weight"]) > 0.10
    assert float(other["target_weight"]) < 0.20
    assert bool(mem["main_ai_capex_momentum_tilt_applied"])
    assert bool(net["main_ai_capex_momentum_tilt_applied"])


def test_concentrated_is_noop_even_when_enabled() -> None:
    old = os.environ.get("PHASE_AI_CAPEX_MOMENTUM_TILT_ENABLED")
    os.environ["PHASE_AI_CAPEX_MOMENTUM_TILT_ENABLED"] = "1"
    try:
        rows = _weighted()
        out = apply_main_ai_capex_momentum_tilt(rows, "concentrated")
    finally:
        if old is None:
            os.environ.pop("PHASE_AI_CAPEX_MOMENTUM_TILT_ENABLED", None)
        else:
            os.environ["PHASE_AI_CAPEX_MOMENTUM_TILT_ENABLED"] = old
    assert out == rows


if __name__ == "__main__":
    test_default_off_returns_exact_input()
    test_enabled_main_only_preserves_gross_and_increases_ai_weights()
    test_concentrated_is_noop_even_when_enabled()
    print("ai_capex_momentum_tilt_hook_smoke: PASS")
