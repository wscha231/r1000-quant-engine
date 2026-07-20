#!/usr/bin/env python3
"""Focused helper checks for the bounded P6 broker evaluator."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.evaluate_run287_sector_rs_materialization import (  # noqa: E402
    behavior_delta,
    delta,
)


def main() -> int:
    control = pd.DataFrame([
        {"rebalance_date": pd.Timestamp("2024-01-31"), "ticker": "AAA", "weight": 0.6},
        {"rebalance_date": pd.Timestamp("2024-01-31"), "ticker": "CASH", "weight": 0.4},
    ])
    treatment = pd.DataFrame([
        {"rebalance_date": pd.Timestamp("2024-01-31"), "ticker": "BBB", "weight": 0.6},
        {"rebalance_date": pd.Timestamp("2024-01-31"), "ticker": "CASH", "weight": 0.4},
    ])
    audit = behavior_delta(control, treatment)
    assert audit["changed_decision_count"] == 1
    assert abs(audit["total_one_way_weight_delta"] - 0.6) <= 1e-12
    assert abs(audit["average_control_cash"] - 0.4) <= 1e-12
    assert delta({"cagr": 0.2}, {"cagr": 0.1}, "cagr") == 0.1
    print("run287_sector_rs_materialization_evaluation_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
