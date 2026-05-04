#!/usr/bin/env python3
"""Smoke test for main cash-drag replay."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.run_main_cash_drag_replay import replay  # noqa: E402


def main() -> int:
    rows = []
    for date, a_ret, b_ret in [
        ("2024-01-31", 0.10, 0.05),
        ("2024-02-29", 0.08, -0.02),
        ("2024-03-31", 0.06, 0.01),
        ("2024-04-30", -0.03, 0.02),
    ]:
        rows.extend([
            {"rebalance_date": date, "ticker": "AAA", "weight": 0.40, "period_forward_return": a_ret},
            {"rebalance_date": date, "ticker": "BBB", "weight": 0.40, "period_forward_return": b_ret},
            {"rebalance_date": date, "ticker": "CASH", "weight": 0.20, "period_forward_return": 0.0},
        ])
    df = pd.DataFrame(rows)
    grid, payload = replay(df, cash_caps=[0.00, 0.05], single_caps=[0.60])
    assert not grid.empty
    assert payload["summary"]["production_activation_allowed"] is False
    best = payload["summary"]["best_by_cagr"]
    assert best["cash_cap"] == 0.0
    assert best["avg_cash_weight"] < payload["summary"]["base_metrics"]["avg_cash_weight"]
    assert best["delta_cagr_vs_base"] > 0.0
    print("main_cash_drag_replay_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
