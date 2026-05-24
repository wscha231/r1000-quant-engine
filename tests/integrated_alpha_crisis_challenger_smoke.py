#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from run_integrated_alpha_crisis_challenger import (  # noqa: E402
    COST_BPS_GRID,
    GOVERNOR_MODES,
    HOLD_VS_REPLACE_MODES,
    evaluate_gates,
    pick_best_and_verdict,
    replay_combo,
    run_grid,
)


def test_integrated_challenger_is_g1_research_only_counterfactual() -> None:
    eq = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-31", periods=24, freq="ME"),
            "return": [0.01] * 10 + [-0.08, -0.06, 0.03, 0.02] + [0.01] * 10,
            "cash_weight": [0.05] * 24,
        }
    )
    features = pd.DataFrame(index=eq["date"])
    features["crisis_score"] = 0.05
    features.loc[features.index[10:12], "crisis_score"] = 0.85

    replayed = replay_combo(eq, features, "off", "normal", 60.0, "date", "return", "cash_weight")
    assert "governed_return" in replayed.columns
    assert replayed["governed_return"].iloc[0] < eq["return"].iloc[0]

    grid, _replays = run_grid(eq, features, "date", "return", "cash_weight", "main")
    assert len(grid) == len(GOVERNOR_MODES) * len(HOLD_VS_REPLACE_MODES) * len(COST_BPS_GRID)
    baseline = grid[
        grid["governor"].eq("off")
        & grid["hold_vs_replace"].eq("off")
        & grid["cost_bps_annual"].eq(0.0)
    ].iloc[0]
    assert abs(float(baseline["delta_cagr_pp"])) < 1e-9

    gate = evaluate_gates(pd.Series({"delta_cagr_pp": 0.0, "delta_mdd_pp": 5.0, "delta_sharpe": 0.0}), {"dCAGR_pp_min": -0.5, "dMDD_pp_min": 5.0, "dSharpe_min": -0.05})
    assert gate["all_pass"] is True

    verdict = pick_best_and_verdict(
        grid,
        gates={"dCAGR_pp_min": -0.5, "dMDD_pp_min": 5.0, "dSharpe_min": -0.05, "bootstrap_ci_dCAGR_lower_min": -1.0},
        a1a2={"A1_passed": None, "A2_passed": None, "status": "data_pending"},
        bootstrap_iter=20,
    )
    assert verdict["verdict"] in {"PARTIAL", "REJECT"}
    assert verdict["gate_details"]["a1a2_pass"] is False


if __name__ == "__main__":
    test_integrated_challenger_is_g1_research_only_counterfactual()
    print("integrated_alpha_crisis_challenger_smoke: PASS")
