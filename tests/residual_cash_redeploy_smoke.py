"""Smoke test for tools/run_residual_cash_redeploy_filter.py.

Pure pandas, no subprocess. Verifies the crisis-aware redeploy:
  * NORMAL date with sub-industry headroom -> idle cash redeployed to ~0
  * NORMAL date where ALL names share one capped sub-industry -> cash bounded
    by the sub-industry cap (cannot over-deploy past the cap)
  * DEFENSE/CRISIS date -> cash PRESERVED untouched (the non-negotiable guard)
  * per-date weights always sum to 1.0
  * single-name cap respected

Run: python3 tests/residual_cash_redeploy_smoke.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "rcr", str(REPO / "tools" / "run_residual_cash_redeploy_filter.py")
)
rcr = importlib.util.module_from_spec(spec); spec.loader.exec_module(rcr)


def _sums_to_one(df: pd.DataFrame) -> None:
    for d, sub in df.groupby("rebalance_date"):
        s = float(sub["weight"].sum())
        assert abs(s - 1.0) < 1e-6, f"date {d}: weights sum to {s}"


def test_normal_date_redeploys_idle_cash_across_subindustries() -> None:
    # 3 names in DIFFERENT sub-industries, 25% each = 75% invested, 25% cash.
    # Single cap 0.30, sub cap 0.70, theme cap 1.0 -> headroom exists -> redeploy to ~0 cash.
    book = pd.DataFrame([
        {"rebalance_date": "2024-05-31", "ticker": "AAA", "weight": 0.25, "industry_group": "semis",
         "effective_single_weight_cap": 0.30, "subindustry_cap": 0.70, "theme_cap": 1.0, "crisis_state": "GREEN"},
        {"rebalance_date": "2024-05-31", "ticker": "BBB", "weight": 0.25, "industry_group": "software",
         "effective_single_weight_cap": 0.30, "subindustry_cap": 0.70, "theme_cap": 1.0, "crisis_state": "GREEN"},
        {"rebalance_date": "2024-05-31", "ticker": "CCC", "weight": 0.25, "industry_group": "energy",
         "effective_single_weight_cap": 0.30, "subindustry_cap": 0.70, "theme_cap": 1.0, "crisis_state": "GREEN"},
        {"rebalance_date": "2024-05-31", "ticker": "CASH", "weight": 0.25, "industry_group": "",
         "effective_single_weight_cap": 0.30, "subindustry_cap": 0.70, "theme_cap": 1.0, "crisis_state": "GREEN"},
    ])
    out, diag = rcr.apply_redeploy(book, portfolio_kind="concentrated", min_cash_floor=0.0)
    _sums_to_one(out)
    cash = float(out.loc[out["ticker"] == "CASH", "weight"].iloc[0])
    # Each name caps at 0.30; 3*0.30 = 0.90 max, so cash floors at 0.10 here.
    assert abs(cash - 0.10) < 1e-6, f"expected cash 0.10 (3x0.30 cap), got {cash}"
    assert diag["normal_dates_redeployed"] == 1 and diag["defense_dates_preserved"] == 0
    # No single name exceeds its 0.30 cap.
    assert out.loc[out["ticker"] != "CASH", "weight"].max() <= 0.30 + 1e-9
    print(f"PASS test_normal_date_redeploys_idle_cash_across_subindustries  cash={cash:.4f}")


def test_normal_date_single_subindustry_bounded_by_subcap() -> None:
    # All 3 names same sub-industry; sub cap 0.70 -> cannot deploy past 0.70 invested.
    book = pd.DataFrame([
        {"rebalance_date": "2024-06-30", "ticker": "AAA", "weight": 0.20, "industry_group": "storage",
         "effective_single_weight_cap": 0.30, "subindustry_cap": 0.70, "theme_cap": 1.0, "crisis_state": "WATCH"},
        {"rebalance_date": "2024-06-30", "ticker": "BBB", "weight": 0.20, "industry_group": "storage",
         "effective_single_weight_cap": 0.30, "subindustry_cap": 0.70, "theme_cap": 1.0, "crisis_state": "WATCH"},
        {"rebalance_date": "2024-06-30", "ticker": "CCC", "weight": 0.20, "industry_group": "storage",
         "effective_single_weight_cap": 0.30, "subindustry_cap": 0.70, "theme_cap": 1.0, "crisis_state": "WATCH"},
        {"rebalance_date": "2024-06-30", "ticker": "CASH", "weight": 0.40, "industry_group": "",
         "effective_single_weight_cap": 0.30, "subindustry_cap": 0.70, "theme_cap": 1.0, "crisis_state": "WATCH"},
    ])
    out, diag = rcr.apply_redeploy(book, portfolio_kind="concentrated", min_cash_floor=0.0)
    _sums_to_one(out)
    invested = float(out.loc[out["ticker"] != "CASH", "weight"].sum())
    cash = float(out.loc[out["ticker"] == "CASH", "weight"].iloc[0])
    # sub cap 0.70 binds: invested -> 0.70, cash -> 0.30 (down from 0.40, partial recovery)
    assert abs(invested - 0.70) < 1e-6, f"expected invested 0.70 (sub cap), got {invested}"
    assert abs(cash - 0.30) < 1e-6, f"expected cash 0.30, got {cash}"
    assert diag["total_cash_redeployed"] > 0.09  # recovered ~0.10
    print(f"PASS test_normal_date_single_subindustry_bounded_by_subcap  invested={invested:.4f} cash={cash:.4f}")


def test_defense_date_cash_preserved() -> None:
    book = pd.DataFrame([
        {"rebalance_date": "2020-03-31", "ticker": "AAA", "weight": 0.20, "industry_group": "semis",
         "effective_single_weight_cap": 0.30, "subindustry_cap": 0.70, "theme_cap": 1.0, "crisis_state": "CRISIS_DEFENSE"},
        {"rebalance_date": "2020-03-31", "ticker": "BBB", "weight": 0.15, "industry_group": "software",
         "effective_single_weight_cap": 0.30, "subindustry_cap": 0.70, "theme_cap": 1.0, "crisis_state": "CRISIS_DEFENSE"},
        {"rebalance_date": "2020-03-31", "ticker": "CASH", "weight": 0.65, "industry_group": "",
         "effective_single_weight_cap": 0.30, "subindustry_cap": 0.70, "theme_cap": 1.0, "crisis_state": "CRISIS_DEFENSE"},
    ])
    out, diag = rcr.apply_redeploy(book, portfolio_kind="concentrated", min_cash_floor=0.0)
    cash = float(out.loc[out["ticker"] == "CASH", "weight"].iloc[0])
    assert abs(cash - 0.65) < 1e-9, f"DEFENSE cash must be preserved at 0.65, got {cash}"
    assert diag["defense_dates_preserved"] == 1 and diag["normal_dates_redeployed"] == 0
    print(f"PASS test_defense_date_cash_preserved  cash={cash:.4f}")


def test_mixed_dates_only_normal_redeployed() -> None:
    book = pd.DataFrame([
        # normal date: redeploy
        {"rebalance_date": "2024-07-31", "ticker": "AAA", "weight": 0.30, "industry_group": "semis",
         "effective_single_weight_cap": 0.40, "subindustry_cap": 0.80, "theme_cap": 1.0, "crisis_state": "GREEN"},
        {"rebalance_date": "2024-07-31", "ticker": "BBB", "weight": 0.30, "industry_group": "software",
         "effective_single_weight_cap": 0.40, "subindustry_cap": 0.80, "theme_cap": 1.0, "crisis_state": "GREEN"},
        {"rebalance_date": "2024-07-31", "ticker": "CASH", "weight": 0.40, "industry_group": "",
         "effective_single_weight_cap": 0.40, "subindustry_cap": 0.80, "theme_cap": 1.0, "crisis_state": "GREEN"},
        # defense date: preserve
        {"rebalance_date": "2022-06-30", "ticker": "AAA", "weight": 0.20, "industry_group": "semis",
         "effective_single_weight_cap": 0.40, "subindustry_cap": 0.80, "theme_cap": 1.0, "crisis_state": "DEFENSE_REVIEW"},
        {"rebalance_date": "2022-06-30", "ticker": "CASH", "weight": 0.80, "industry_group": "",
         "effective_single_weight_cap": 0.40, "subindustry_cap": 0.80, "theme_cap": 1.0, "crisis_state": "DEFENSE_REVIEW"},
    ])
    out, diag = rcr.apply_redeploy(book, portfolio_kind="concentrated", min_cash_floor=0.0)
    _sums_to_one(out)
    n_cash = float(out.loc[(out["rebalance_date"].astype(str).str.startswith("2024-07")) & (out["ticker"] == "CASH"), "weight"].iloc[0])
    d_cash = float(out.loc[(out["rebalance_date"].astype(str).str.startswith("2022-06")) & (out["ticker"] == "CASH"), "weight"].iloc[0])
    # normal: AAA+BBB cap at 0.40 each = 0.80, cash floors at 0.20
    assert abs(n_cash - 0.20) < 1e-6, f"normal cash expected 0.20, got {n_cash}"
    assert abs(d_cash - 0.80) < 1e-9, f"defense cash preserved 0.80, got {d_cash}"
    assert diag["normal_dates_redeployed"] == 1 and diag["defense_dates_preserved"] == 1
    print(f"PASS test_mixed_dates_only_normal_redeployed  normal_cash={n_cash:.4f} defense_cash={d_cash:.4f}")


def test_min_cash_floor_respected() -> None:
    book = pd.DataFrame([
        {"rebalance_date": "2024-08-31", "ticker": "AAA", "weight": 0.20, "industry_group": "semis",
         "effective_single_weight_cap": 0.50, "subindustry_cap": 0.90, "theme_cap": 1.0, "crisis_state": "GREEN"},
        {"rebalance_date": "2024-08-31", "ticker": "BBB", "weight": 0.20, "industry_group": "software",
         "effective_single_weight_cap": 0.50, "subindustry_cap": 0.90, "theme_cap": 1.0, "crisis_state": "GREEN"},
        {"rebalance_date": "2024-08-31", "ticker": "CASH", "weight": 0.60, "industry_group": "",
         "effective_single_weight_cap": 0.50, "subindustry_cap": 0.90, "theme_cap": 1.0, "crisis_state": "GREEN"},
    ])
    out, diag = rcr.apply_redeploy(book, portfolio_kind="concentrated", min_cash_floor=0.05)
    cash = float(out.loc[out["ticker"] == "CASH", "weight"].iloc[0])
    # caps allow full deploy (0.50 each); floor holds cash at 0.05.
    assert abs(cash - 0.05) < 1e-6, f"expected cash floor 0.05, got {cash}"
    print(f"PASS test_min_cash_floor_respected  cash={cash:.4f}")


def test_unannotated_historical_book_uses_documented_normal_boundary() -> None:
    book = pd.DataFrame(
        [
            {
                "rebalance_date": "2024-09-30",
                "ticker": "AAA",
                "weight": 0.30,
                "industry_group": "semis",
                "effective_single_weight_cap": 0.50,
                "subindustry_cap": 0.90,
                "theme_cap": 1.0,
            },
            {
                "rebalance_date": "2024-09-30",
                "ticker": "BBB",
                "weight": 0.30,
                "industry_group": "software",
                "effective_single_weight_cap": 0.50,
                "subindustry_cap": 0.90,
                "theme_cap": 1.0,
            },
            {"rebalance_date": "2024-09-30", "ticker": "CASH", "weight": 0.40},
        ]
    )
    out, diag = rcr.apply_redeploy(
        book,
        portfolio_kind="concentrated",
        min_cash_floor=0.0,
    )
    assert diag["normal_dates_redeployed"] == 1
    assert diag["defense_dates_preserved"] == 0
    assert float(out.loc[out["ticker"].eq("CASH"), "weight"].iloc[0]) < 0.40
    assert rcr.is_defense_date("MYSTERY_STATE") is True


def main() -> int:
    tests = [
        test_normal_date_redeploys_idle_cash_across_subindustries,
        test_normal_date_single_subindustry_bounded_by_subcap,
        test_defense_date_cash_preserved,
        test_mixed_dates_only_normal_redeployed,
        test_min_cash_floor_respected,
        test_unannotated_historical_book_uses_documented_normal_boundary,
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
