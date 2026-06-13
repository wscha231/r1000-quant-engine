"""Smoke test for tools/run_gate_ablation_filter.py + run_gate_ablation_study.py.

Pure pandas, no subprocess. Drives the filter directly on a synthetic 2-date
book that mimics the operating target book's pre_<gate>_weight schema.

Run: python3 tests/gate_ablation_smoke.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, str(REPO / "tools" / f"{name}.py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


ablate = _load("run_gate_ablation_filter")
study = _load("run_gate_ablation_study")


def synth_book() -> pd.DataFrame:
    # Two rebalance dates, three stocks, two pre_<gate>_weight columns
    # (gateA cut AAA on date1; gateB cut BBB on date2). CCC was untouched.
    return pd.DataFrame([
        {"rebalance_date": "2024-01-31", "ticker": "AAA", "weight": 0.20,
         "pre_gateA_weight": 0.40, "pre_gateB_weight": 0.20, "pre_gateC_weight": 0.20},
        {"rebalance_date": "2024-01-31", "ticker": "BBB", "weight": 0.30,
         "pre_gateA_weight": 0.30, "pre_gateB_weight": 0.30, "pre_gateC_weight": 0.30},
        {"rebalance_date": "2024-01-31", "ticker": "CCC", "weight": 0.10,
         "pre_gateA_weight": 0.10, "pre_gateB_weight": 0.10, "pre_gateC_weight": 0.10},
        {"rebalance_date": "2024-01-31", "ticker": "CASH", "weight": 0.40,
         "pre_gateA_weight": 0.0, "pre_gateB_weight": 0.0, "pre_gateC_weight": 0.0},
        {"rebalance_date": "2024-02-29", "ticker": "AAA", "weight": 0.30,
         "pre_gateA_weight": 0.30, "pre_gateB_weight": 0.30, "pre_gateC_weight": 0.30},
        {"rebalance_date": "2024-02-29", "ticker": "BBB", "weight": 0.20,
         "pre_gateA_weight": 0.20, "pre_gateB_weight": 0.50, "pre_gateC_weight": 0.20},
        {"rebalance_date": "2024-02-29", "ticker": "CCC", "weight": 0.10,
         "pre_gateA_weight": 0.10, "pre_gateB_weight": 0.10, "pre_gateC_weight": 0.10},
        {"rebalance_date": "2024-02-29", "ticker": "CASH", "weight": 0.40,
         "pre_gateA_weight": 0.0, "pre_gateB_weight": 0.0, "pre_gateC_weight": 0.0},
    ])


def test_discover_pre_weight_cols() -> None:
    book = synth_book()
    cols = ablate.discover_pre_weight_cols(book.columns)
    assert cols == ["pre_gateA_weight", "pre_gateB_weight", "pre_gateC_weight"], cols
    print("PASS test_discover_pre_weight_cols")


def test_restore_single_gate_lifts_only_that_gates_rows() -> None:
    book = synth_book()
    filtered, diag = ablate.apply_gate_ablation(book, restore_gates=["gateA"])
    # AAA on date1 was cut 0.40 -> 0.20 by gateA; restoring -> 0.40.
    aaa_d1 = filtered[(filtered.ticker == "AAA") & (filtered.rebalance_date.astype(str).str.startswith("2024-01"))]
    assert abs(float(aaa_d1["weight"].iloc[0]) - 0.40) < 1e-6, aaa_d1["weight"].iloc[0]
    # BBB on date2 was cut by gateB, NOT gateA — gateA restore must leave it alone.
    bbb_d2 = filtered[(filtered.ticker == "BBB") & (filtered.rebalance_date.astype(str).str.startswith("2024-02"))]
    assert abs(float(bbb_d2["weight"].iloc[0]) - 0.20) < 1e-6, bbb_d2["weight"].iloc[0]
    # Per-date weights still sum to 1.0; date1 stock total went 0.20+0.30+0.10=0.60 -> 0.40+0.30+0.10=0.80, cash drops 0.40 -> 0.20.
    for d, sub in filtered.groupby("rebalance_date"):
        s = float(sub["weight"].sum())
        assert abs(s - 1.0) < 1e-6, f"date {d}: weights sum to {s}"
    cash_d1 = float(filtered.loc[(filtered.ticker == "CASH") & (filtered.rebalance_date.astype(str).str.startswith("2024-01")), "weight"].iloc[0])
    assert abs(cash_d1 - 0.20) < 1e-6, f"date1 cash expected 0.20 got {cash_d1}"
    assert diag["rows_lifted"] == 1 and abs(diag["total_weight_lifted"] - 0.20) < 1e-6, diag
    print(f"PASS test_restore_single_gate_lifts_only_that_gates_rows  cash_d1={cash_d1:.4f}")


def test_all_token_restores_every_gate() -> None:
    book = synth_book()
    filtered, diag = ablate.apply_gate_ablation(book, restore_gates=["ALL"])
    # date2 BBB: pre_gateB_weight=0.50 dominates -> BBB lifts to 0.50.
    bbb_d2 = float(filtered.loc[(filtered.ticker == "BBB") & (filtered.rebalance_date.astype(str).str.startswith("2024-02")), "weight"].iloc[0])
    assert abs(bbb_d2 - 0.50) < 1e-6, bbb_d2
    # date1 AAA: pre_gateA_weight=0.40 dominates -> AAA lifts to 0.40.
    aaa_d1 = float(filtered.loc[(filtered.ticker == "AAA") & (filtered.rebalance_date.astype(str).str.startswith("2024-01")), "weight"].iloc[0])
    assert abs(aaa_d1 - 0.40) < 1e-6, aaa_d1
    # All restored gates appear in diag.
    assert set(diag["restored_gates"]) == {"gateA", "gateB", "gateC"}, diag["restored_gates"]
    # Per-date sums still == 1.0.
    for d, sub in filtered.groupby("rebalance_date"):
        assert abs(float(sub["weight"].sum()) - 1.0) < 1e-6
    print("PASS test_all_token_restores_every_gate")


def test_renormalization_when_restored_stock_sum_exceeds_one() -> None:
    # Build a date where restoring would push stocks > 1.0; expect proportional
    # scaledown and zero cash.
    book = pd.DataFrame([
        {"rebalance_date": "2024-03-31", "ticker": "X", "weight": 0.10, "pre_g_weight": 0.80},
        {"rebalance_date": "2024-03-31", "ticker": "Y", "weight": 0.10, "pre_g_weight": 0.70},
        {"rebalance_date": "2024-03-31", "ticker": "CASH", "weight": 0.80, "pre_g_weight": 0.0},
    ])
    filtered, diag = ablate.apply_gate_ablation(book, restore_gates=["g"])
    x = float(filtered.loc[filtered.ticker == "X", "weight"].iloc[0])
    y = float(filtered.loc[filtered.ticker == "Y", "weight"].iloc[0])
    c = float(filtered.loc[filtered.ticker == "CASH", "weight"].iloc[0])
    # 0.80 + 0.70 = 1.50 -> scale by 1/1.5; X -> 0.5333, Y -> 0.4667
    assert abs(x - 0.80/1.50) < 1e-6 and abs(y - 0.70/1.50) < 1e-6, (x, y)
    assert abs(c - 0.0) < 1e-6, c
    assert abs(x + y + c - 1.0) < 1e-6
    print(f"PASS test_renormalization_when_restored_stock_sum_exceeds_one  x={x:.4f} y={y:.4f}")


def test_unknown_gate_name_is_recorded_not_raised() -> None:
    book = synth_book()
    filtered, diag = ablate.apply_gate_ablation(book, restore_gates=["does_not_exist", "gateA"])
    assert "does_not_exist" in diag["missing_gates"], diag
    # gateA still applied
    aaa_d1 = float(filtered.loc[(filtered.ticker == "AAA") & (filtered.rebalance_date.astype(str).str.startswith("2024-01")), "weight"].iloc[0])
    assert abs(aaa_d1 - 0.40) < 1e-6, aaa_d1
    print("PASS test_unknown_gate_name_is_recorded_not_raised")


def test_classification_thresholds() -> None:
    # CAGR_DRAG_HEAVY: cagr_lift > +1.0 AND mdd_change >= -1.0
    assert study.classify(1.5, -0.5) == "CAGR_DRAG_HEAVY"
    # PURE_DRAG: cagr_lift > +0.5 AND mdd_change >= -1.5 (but not heavy)
    assert study.classify(0.8, -1.2) == "PURE_DRAG"
    # EARNED: cagr_lift > 0 AND mdd_change <= -3.0
    assert study.classify(0.3, -4.0) == "EARNED"
    # PROTECTION: cagr_lift <= 0 AND mdd_change <= -1.0
    assert study.classify(-0.2, -2.0) == "PROTECTION"
    # NEUTRAL: small both axes
    assert study.classify(0.2, -0.3) == "NEUTRAL"
    print("PASS test_classification_thresholds")


def main() -> int:
    tests = [
        test_discover_pre_weight_cols,
        test_restore_single_gate_lifts_only_that_gates_rows,
        test_all_token_restores_every_gate,
        test_renormalization_when_restored_stock_sum_exceeds_one,
        test_unknown_gate_name_is_recorded_not_raised,
        test_classification_thresholds,
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
