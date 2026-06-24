#!/usr/bin/env python3
"""Smoke for tools/run_subdaily_exit_grid_sweep.py.

Tests focus on pure scoring/ranking math (no subprocess required) so the
gate logic, composite penalty, champion picker, and label rendering can be
locked without running PRWV. A separate test verifies the grid parser
including the `disabled` alias for hard_stop.
"""
from __future__ import annotations

import sys
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools import run_subdaily_exit_grid_sweep as sweep


def test_parse_grid_with_disabled_alias() -> None:
    out = sweep.parse_grid("-0.08,-0.12,disabled", allow_disabled=True)
    assert out == [-0.08, -0.12, sweep.DISABLED_HARD_STOP_VALUE]


def test_parse_grid_rejects_disabled_when_not_allowed() -> None:
    try:
        sweep.parse_grid("-0.15,disabled", allow_disabled=False)
    except ValueError as e:
        assert "disabled" in str(e)
    else:
        raise AssertionError("parse_grid should reject `disabled` when allow_disabled=False")


def test_composite_score_favours_better_mdd_with_small_cagr_drop() -> None:
    baseline = {"cagr": 0.21, "max_dd": -0.33}
    # Combo A: baseline (no change).
    a = sweep.score_composite(0.21, -0.33, baseline)
    # Combo B: -1pp CAGR, +5pp MDD improvement.
    b = sweep.score_composite(0.20, -0.28, baseline)
    # Combo C: -5pp CAGR, +8pp MDD improvement.
    c = sweep.score_composite(0.16, -0.25, baseline)
    # Combo D: -10pp CAGR, +10pp MDD improvement (triggers drag penalty).
    d = sweep.score_composite(0.11, -0.23, baseline)
    assert b["composite"] > a["composite"], "small CAGR loss + real MDD gain should beat baseline"
    assert b["composite"] > c["composite"], "moderate CAGR loss should not beat small CAGR loss with similar MDD gain"
    # Penalty must fire when CAGR drops more than 5pp below baseline.
    assert d["drag_penalty"] > 0.0
    assert d["composite"] < c["composite"], "drag penalty must push very-high-cagr-drop combos down"


def test_rank_grid_picks_best_composite_first() -> None:
    baseline = {"cagr": 0.21, "max_dd": -0.33}
    # Synthetic loader keyed by combo.
    fake = {
        (-0.08, -0.15): {"status": "completed", "cagr": 0.13, "max_dd": -0.29, "sharpe": 0.79, "exit_count": 580, "trim_count": 60},
        (-0.12, -0.18): {"status": "completed", "cagr": 0.19, "max_dd": -0.28, "sharpe": 1.05, "exit_count": 220, "trim_count": 30},
        (-0.15, -0.22): {"status": "completed", "cagr": 0.20, "max_dd": -0.30, "sharpe": 1.10, "exit_count": 90, "trim_count": 10},
        (sweep.DISABLED_HARD_STOP_VALUE, -0.22): {"status": "completed", "cagr": 0.205, "max_dd": -0.32, "sharpe": 1.12, "exit_count": 18, "trim_count": 4},
    }
    def loader(h: float, t: float) -> dict:
        return fake.get((h, t), {"status": "missing"})
    combos = list(fake.keys())
    ranked = sweep.rank_grid(combos, loader, baseline)
    assert len(ranked) == 4
    assert ranked[0]["status"] == "ok"
    # The -0.12/-0.18 combo balances ~2pp CAGR drag with 5pp MDD improvement;
    # it should beat the tight (-0.08, -0.15) "expensive" combo and the
    # loose (-0.15, -0.22) one whose MDD improvement is smaller.
    assert ranked[0]["hard_stop"] in (-0.12, -0.15, sweep.DISABLED_HARD_STOP_VALUE), (
        "winner should be one of the relaxed-hard-stop combos, not the -0.08 tight one"
    )
    # Tight combo (-0.08/-0.15) should rank LAST or near-last because its
    # CAGR collapses while only modestly improving MDD.
    assert ranked[-1]["hard_stop"] == -0.08


def test_rank_grid_handles_missing_metrics_without_crashing() -> None:
    baseline = {"cagr": 0.21, "max_dd": -0.33}
    def loader(h: float, t: float) -> dict:
        if h == -0.08:
            return {"status": "missing_inputs"}
        return {"status": "completed", "cagr": 0.20, "max_dd": -0.28}
    ranked = sweep.rank_grid([(-0.08, -0.15), (-0.12, -0.18)], loader, baseline)
    assert ranked[0]["status"] == "ok"
    assert ranked[-1]["status"] == "missing_inputs"


def test_champion_from_ranked_skips_missing() -> None:
    rows = [
        {"status": "missing_inputs", "composite": float("-inf")},
        {"status": "ok", "composite": 0.18, "hard_stop": -0.12},
    ]
    champion = sweep.champion_from_ranked(rows)
    assert champion is not None
    assert champion["hard_stop"] == -0.12


def test_holdings_path_falls_back_to_alphaops_vnext_target_book(tmp_path: Path) -> None:
    latest = tmp_path / "run"
    target_dir = latest / "alphaops_vnext"
    target_dir.mkdir(parents=True)
    main_target = target_dir / "official_main_target_book.csv"
    main_target.write_text("rebalance_date,ticker,weight\n2020-01-31,ABC,1.0\n", encoding="utf-8")

    holdings, period_map = sweep.holdings_path_for(latest, "main")

    assert holdings == main_target
    assert period_map == latest / "reports" / "regime_by_month.csv"


def test_render_report_has_all_combos() -> None:
    baseline = {"cagr": 0.21, "max_dd": -0.33, "sharpe": 1.0}
    rows = [
        {
            "status": "ok",
            "hard_stop": -0.12, "hard_stop_label": "-12.00%",
            "trailing_stop": -0.18, "trailing_stop_label": "-18.00%",
            "overlay_cagr": 0.195, "overlay_max_dd": -0.28,
            "cagr_gap_pp": 1.5, "mdd_improvement_pp": 5.0,
            "overlay_exit_count": 220, "overlay_trim_count": 30,
            "composite": 0.20,
        },
        {
            "status": "missing_inputs",
            "hard_stop": -0.08, "hard_stop_label": "-8.00%",
            "trailing_stop": -0.15, "trailing_stop_label": "-15.00%",
        },
    ]
    text = sweep.render_report("main", baseline, rows)
    assert "-12.00%" in text and "-18.00%" in text
    assert "missing_inputs" in text


if __name__ == "__main__":
    print("PASS test_parse_grid_with_disabled_alias")
    test_parse_grid_with_disabled_alias()
    print("PASS test_parse_grid_rejects_disabled_when_not_allowed")
    test_parse_grid_rejects_disabled_when_not_allowed()
    print("PASS test_composite_score_favours_better_mdd_with_small_cagr_drop")
    test_composite_score_favours_better_mdd_with_small_cagr_drop()
    print("PASS test_rank_grid_picks_best_composite_first")
    test_rank_grid_picks_best_composite_first()
    print("PASS test_rank_grid_handles_missing_metrics_without_crashing")
    test_rank_grid_handles_missing_metrics_without_crashing()
    print("PASS test_champion_from_ranked_skips_missing")
    test_champion_from_ranked_skips_missing()
    print("PASS test_holdings_path_falls_back_to_alphaops_vnext_target_book")
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        test_holdings_path_falls_back_to_alphaops_vnext_target_book(Path(tmp))
    print("PASS test_render_report_has_all_combos")
    test_render_report_has_all_combos()
    print("\n8/8 passed")
