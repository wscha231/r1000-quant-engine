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
    # All four main_top_n values (0, 6, 8, 10) must be represented.
    seen_top_n = {c.main_top_n for c in combos}
    assert seen_top_n == {0, 6, 8, 10}, f"expected {{0,6,8,10}}, got {seen_top_n}"
    # redeploy must be A/B'd (both False and True present).
    seen_rd = {c.redeploy for c in combos}
    assert seen_rd == {False, True}, f"expected redeploy {{False,True}}, got {seen_rd}"
    print(f"PASS test_grid_expansion_main_is_passthrough  n={len(combos)}  top_n={sorted(seen_top_n)}  redeploy={sorted(seen_rd)}")


def test_main_top_n_does_not_leak_to_concentrated() -> None:
    grid = ocs.DEFAULT_GRID
    combos = ocs.expand_grid(grid, "concentrated", grid["max_combos"])
    assert all(c.main_top_n == 0 for c in combos), "concentrated combos must NOT carry main_top_n"
    print(f"PASS test_main_top_n_does_not_leak_to_concentrated  n={len(combos)}")


def test_main_top_n_filter_keeps_top_n_and_rebuilds_cash() -> None:
    # Real test of the filter against a synthetic monthly book.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "topn",
        str(Path(__file__).resolve().parent.parent / "tools" / "run_main_top_n_concentration_filter.py"),
    )
    topn = importlib.util.module_from_spec(spec); spec.loader.exec_module(topn)
    book = pd.DataFrame([
        {"rebalance_date": "2024-01-31", "ticker": "AAA", "weight": 0.30, "sector": "X"},
        {"rebalance_date": "2024-01-31", "ticker": "BBB", "weight": 0.25, "sector": "X"},
        {"rebalance_date": "2024-01-31", "ticker": "CCC", "weight": 0.20, "sector": "Y"},
        {"rebalance_date": "2024-01-31", "ticker": "DDD", "weight": 0.10, "sector": "Y"},
        {"rebalance_date": "2024-01-31", "ticker": "EEE", "weight": 0.10, "sector": "Z"},
        {"rebalance_date": "2024-01-31", "ticker": "FFF", "weight": 0.05, "sector": "Z"},
        {"rebalance_date": "2024-02-29", "ticker": "AAA", "weight": 0.50, "sector": "X"},
        {"rebalance_date": "2024-02-29", "ticker": "BBB", "weight": 0.30, "sector": "X"},
        {"rebalance_date": "2024-02-29", "ticker": "CCC", "weight": 0.20, "sector": "Y"},
    ])
    filtered, decisions = topn.apply_top_n(book, top_n=3, keep_cash_floor=True)
    # Per date: only top-3 stocks + a CASH row, weights sum to 1.0
    for date, sub in filtered.groupby("rebalance_date"):
        stocks = sub[sub["ticker"] != "CASH"]
        cash = sub[sub["ticker"] == "CASH"]
        assert len(stocks) <= 3, f"date {date}: kept {len(stocks)} stocks, expected <=3"
        assert len(cash) == 1, f"date {date}: expected exactly 1 CASH row, got {len(cash)}"
        total = float(sub["weight"].sum())
        assert abs(total - 1.0) < 1e-6, f"date {date}: sum {total} != 1.0"
    # First date: stocks summed to 1.00, top-3 = 0.30+0.25+0.20 = 0.75 -> cash 0.25
    d1 = filtered[filtered["rebalance_date"].astype(str).str.startswith("2024-01")]
    cash_w = float(d1.loc[d1["ticker"] == "CASH", "weight"].iloc[0])
    assert abs(cash_w - 0.25) < 1e-6, f"date1 cash {cash_w} != 0.25"
    # Decisions log includes both dates
    assert len(decisions) == 2
    print("PASS test_main_top_n_filter_keeps_top_n_and_rebuilds_cash")


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
        test_main_top_n_does_not_leak_to_concentrated,
        test_main_top_n_filter_keeps_top_n_and_rebuilds_cash,
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
