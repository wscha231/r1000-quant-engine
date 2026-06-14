#!/usr/bin/env python3
"""Smoke for Tier-2 strengthened goal gates added on top of the headline
Tier-1 CAGR/MDD targets in `tools/run_account_evaluation.py`.

Run 27498401423 surfaced the headline blind spot: full-period CAGR 34.33%
Main / 44.57% Conc looked respectable, but the IS-only window (2019-06 to
2024-06) was 21.45% / 21.29% — i.e. the OOS slice was hiding an underperforming
engine. The Tier-2 gates close that: an IS-CAGR floor, an OOS/IS ratio cap,
a Sharpe floor, an avg-cash cap, and a recent-MDD floor.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.run_account_evaluation import (  # noqa: E402
    evaluate_strengthened_gates,
    strengthened_gate_for,
)


def _broker_metrics(
    *,
    is_cagr: float = 0.30,
    oos_cagr: float = 0.40,
    is_mdd: float = -0.22,
    oos_mdd: float = -0.20,
    sharpe: float = 1.40,
    avg_cash: float = 0.30,
) -> dict:
    return {
        "sharpe": sharpe,
        "avg_cash_weight": avg_cash,
        "windows": {
            "is": {"cagr": is_cagr, "max_dd": is_mdd},
            "oos": {"cagr": oos_cagr, "max_dd": oos_mdd},
            "oos2": {"cagr": (is_cagr + oos_cagr) / 2, "max_dd": oos_mdd},
        },
    }


def test_clean_run_passes_all_tier2_checks() -> None:
    gate = strengthened_gate_for("concentrated")
    bm = _broker_metrics(is_cagr=0.45, oos_cagr=0.60, sharpe=1.60, avg_cash=0.35)
    res = evaluate_strengthened_gates(bm, gate)
    assert res["passing"], res["failing"]
    assert res["failing"] == []


def test_is_cagr_below_floor_fails() -> None:
    gate = strengthened_gate_for("concentrated")  # is_cagr_min 0.30
    bm = _broker_metrics(is_cagr=0.21, oos_cagr=1.29, sharpe=1.40)
    res = evaluate_strengthened_gates(bm, gate)
    assert not res["passing"]
    assert "is_cagr_min" in res["failing"]
    # this is exactly the 27498401423 conc shape — IS 21.29% / OOS 129.36%
    # ratio is 6.14x which also fails the OOS/IS cap of 3.0x
    assert "oos_is_cagr_ratio_max" in res["failing"]


def test_oos_to_is_ratio_cap() -> None:
    gate = strengthened_gate_for("main")  # oos_is_cagr_ratio_max 3.0
    bm = _broker_metrics(is_cagr=0.20, oos_cagr=0.80, sharpe=1.30)
    res = evaluate_strengthened_gates(bm, gate)
    assert not res["passing"]
    assert "oos_is_cagr_ratio_max" in res["failing"]


def test_sharpe_floor() -> None:
    gate = strengthened_gate_for("main")  # sharpe_min 1.20
    bm = _broker_metrics(is_cagr=0.30, oos_cagr=0.50, sharpe=1.05)
    res = evaluate_strengthened_gates(bm, gate)
    assert not res["passing"]
    assert "sharpe_min" in res["failing"]


def test_avg_cash_cap() -> None:
    gate = strengthened_gate_for("concentrated")  # 0.55
    bm = _broker_metrics(is_cagr=0.40, oos_cagr=0.50, sharpe=1.50, avg_cash=0.62)
    res = evaluate_strengthened_gates(bm, gate)
    assert not res["passing"]
    assert "avg_cash_weight_max" in res["failing"]


def test_recent_mdd_floor() -> None:
    gate = strengthened_gate_for("concentrated")  # -0.25
    bm = _broker_metrics(is_cagr=0.40, oos_cagr=0.50, sharpe=1.50, oos_mdd=-0.32)
    res = evaluate_strengthened_gates(bm, gate)
    assert not res["passing"]
    assert "max_dd_recent_3y_min" in res["failing"]


def test_missing_windows_skips_ratio_check_gracefully() -> None:
    gate = strengthened_gate_for("main")
    bm = {"sharpe": 1.30, "avg_cash_weight": 0.30}
    res = evaluate_strengthened_gates(bm, gate)
    # No windows = None for IS — IS gate fails; ratio is None which passes
    assert "is_cagr_min" in res["failing"]
    assert "oos_is_cagr_ratio_max" not in res["failing"]


def test_run_27498401423_concentrated_matches_observed_shape() -> None:
    """Replay the actual numbers from run 27498401423 to lock the regression.

    Conc full 44.57% / IS 21.29% / OOS 129.36% / Sharpe 1.40 / avg_cash 42.37%
    / OOS MDD -23.03%. Must fail Tier-2 on is_cagr_min and oos_is_cagr_ratio_max.
    """
    gate = strengthened_gate_for("concentrated")
    bm = {
        "sharpe": 1.4015,
        "avg_cash_weight": 0.4237,
        "windows": {
            "is": {"cagr": 0.2129, "max_dd": -0.2588},
            "oos": {"cagr": 1.2936, "max_dd": -0.2303},
            "oos2": {"cagr": 0.7440, "max_dd": -0.2303},
        },
    }
    res = evaluate_strengthened_gates(bm, gate)
    assert not res["passing"]
    failing = set(res["failing"])
    assert "is_cagr_min" in failing
    assert "oos_is_cagr_ratio_max" in failing
    # Sharpe 1.40 == floor 1.40, cash 42% < 55%, recent_mdd -23% > -25% — pass
    assert "sharpe_min" not in failing
    assert "avg_cash_weight_max" not in failing
    assert "max_dd_recent_3y_min" not in failing


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(tests)}/{len(tests)} passed")
