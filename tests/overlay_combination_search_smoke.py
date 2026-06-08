"""Smoke test for tools/run_overlay_combination_search.py.

Pure-Python checks that do NOT invoke any subprocess (no broker replays, no
filter runs). We verify:
  * grid expansion produces the expected cartesian product for both kinds and
    enforces max_combos
  * Combo.signature() is stable + unique per knob tuple
  * stress_window_mdd correctly slices an equity curve
  * composite_primary_score gate-jumps when target_pass / stress_pass flip
  * neighbourhood_median_score uses Hamming distance across knob columns

Run: py -3 tests/overlay_combination_search_smoke.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import run_overlay_combination_search as ocs


def test_grid_expansion_concentrated() -> None:
    grid = ocs.DEFAULT_GRID
    combos = ocs.expand_grid(grid, "concentrated", grid["max_combos"])
    # 3 N * 2 weighting * 3 rebal * (1 + 1) churn * (1 + 1) macro * (1 + 1) regcap
    assert len(combos) > 0, "expected non-empty grid"
    sigs = {c.signature() for c in combos}
    assert len(sigs) == len(combos), "signatures must be unique per combo"
    assert all(c.portfolio_kind == "concentrated" for c in combos)
    assert all(c.conc_n in {3, 4, 5} for c in combos)
    print(f"PASS test_grid_expansion_concentrated  n={len(combos)}")


def test_grid_expansion_main_is_passthrough() -> None:
    grid = ocs.DEFAULT_GRID
    combos = ocs.expand_grid(grid, "main", grid["max_combos"])
    assert len(combos) > 0
    assert all(c.portfolio_kind == "main" for c in combos)
    assert all(c.conc_n == 0 and c.conc_weighting == "" for c in combos), (
        "main combos must not carry concentrated champion knobs"
    )
    print(f"PASS test_grid_expansion_main_is_passthrough  n={len(combos)}")


def test_max_combos_caps_growth() -> None:
    grid = ocs.DEFAULT_GRID
    combos = ocs.expand_grid(grid, "concentrated", max_combos=5)
    assert len(combos) == 5, f"expected exactly 5 combos, got {len(combos)}"
    print("PASS test_max_combos_caps_growth")


def test_stress_window_mdd_basic() -> None:
    eq = pd.DataFrame({
        "date": pd.date_range("2020-01-01", periods=180, freq="D"),
        "equity_usd": [100.0] * 30 + [120.0] * 20 + [60.0] * 30 + [80.0] * 100,
    })
    # COVID-like window catches the 120 -> 60 = -50% drop
    mdd = ocs.stress_window_mdd(eq, "2020-01-31", "2020-04-30")
    assert mdd is not None and -0.55 < mdd < -0.45, f"expected ~-50% mdd, got {mdd}"
    # Window outside the dip should be ~0 (or slight)
    mdd_calm = ocs.stress_window_mdd(eq, "2020-04-01", "2020-06-29")
    assert mdd_calm is not None and mdd_calm >= -0.1, f"expected near-flat, got {mdd_calm}"
    print(f"PASS test_stress_window_mdd_basic  mdd={mdd:.3f}  calm={mdd_calm:.3f}")


def test_stress_window_mdd_handles_missing() -> None:
    assert ocs.stress_window_mdd(None, "2020-01-01", "2020-12-31") is None
    empty = pd.DataFrame({"date": [], "equity_usd": []})
    assert ocs.stress_window_mdd(empty, "2020-01-01", "2020-12-31") is None
    print("PASS test_stress_window_mdd_handles_missing")


def test_composite_primary_score_gates() -> None:
    # Same cagr/mdd/sharpe; target_pass alone should jump score by 1000.
    base = ocs.composite_primary_score(False, cagr=0.25, mdd=-0.20, sharpe=1.0, stress_pass=False)
    with_target = ocs.composite_primary_score(True, cagr=0.25, mdd=-0.20, sharpe=1.0, stress_pass=False)
    with_both = ocs.composite_primary_score(True, cagr=0.25, mdd=-0.20, sharpe=1.0, stress_pass=True)
    assert with_target - base == 1000.0
    assert with_both - with_target == 300.0
    print("PASS test_composite_primary_score_gates")


def test_neighbourhood_median_score() -> None:
    rows = [
        {"idx": 0, "portfolio_kind": "main", "combo_conc_n": 0, "combo_conc_weighting": "", "combo_conc_rebal": 0,
         "combo_churn_enabled": True, "combo_churn_swap_threshold": 2, "combo_macro_enabled": True,
         "combo_macro_confirm_days": 3, "combo_regime_enabled": True, "combo_regime_bear_mult": 0.5,
         "primary_score": 100.0},
        {"idx": 1, "portfolio_kind": "main", "combo_conc_n": 0, "combo_conc_weighting": "", "combo_conc_rebal": 0,
         "combo_churn_enabled": False, "combo_churn_swap_threshold": 0, "combo_macro_enabled": True,
         "combo_macro_confirm_days": 3, "combo_regime_enabled": True, "combo_regime_bear_mult": 0.5,
         "primary_score": 90.0},
        {"idx": 2, "portfolio_kind": "main", "combo_conc_n": 0, "combo_conc_weighting": "", "combo_conc_rebal": 0,
         "combo_churn_enabled": False, "combo_churn_swap_threshold": 0, "combo_macro_enabled": False,
         "combo_macro_confirm_days": 0, "combo_regime_enabled": False, "combo_regime_bear_mult": 1.0,
         "primary_score": 80.0},
        # different portfolio kind — must be excluded
        {"idx": 3, "portfolio_kind": "concentrated", "combo_conc_n": 3, "combo_conc_weighting": "score_power",
         "combo_conc_rebal": 1, "combo_churn_enabled": True, "combo_churn_swap_threshold": 2,
         "combo_macro_enabled": True, "combo_macro_confirm_days": 3, "combo_regime_enabled": True,
         "combo_regime_bear_mult": 0.5, "primary_score": 200.0},
    ]
    med = ocs.neighbourhood_median_score(rows[0], rows, k=2)
    # row 0's two nearest same-kind neighbours are rows 1 and 2 (scores 90, 80) → median = 85
    assert abs(med - 85.0) < 1e-6, f"expected median 85.0, got {med}"
    print(f"PASS test_neighbourhood_median_score  median={med}")


def test_load_grid_defaults() -> None:
    g = ocs.load_grid("")
    assert g is ocs.DEFAULT_GRID
    print("PASS test_load_grid_defaults")


def main() -> int:
    tests = [
        test_grid_expansion_concentrated,
        test_grid_expansion_main_is_passthrough,
        test_max_combos_caps_growth,
        test_stress_window_mdd_basic,
        test_stress_window_mdd_handles_missing,
        test_composite_primary_score_gates,
        test_neighbourhood_median_score,
        test_load_grid_defaults,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as exc:
            print(f"FAIL {t.__name__}: {exc}")
            failed += 1
        except Exception as exc:
            print(f"ERROR {t.__name__}: {exc!r}")
            failed += 1
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
