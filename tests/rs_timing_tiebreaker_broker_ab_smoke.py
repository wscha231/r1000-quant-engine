#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_rs_timing_tiebreaker_broker_ab import build_arm_book, learn_is_threshold  # noqa: E402


def test_rs2w_tiebreaker_removes_failed_entry_to_cash() -> None:
    raw = pd.DataFrame(
        [
            {
                "rebalance_date": "2024-01-31",
                "ticker": "AAA",
                "portfolio_kind": "concentrated",
                "weight": 0.50,
                "target_weight": 0.50,
                "concentrated_cashfunded_early_entry_applied": False,
                "rs_benchmark_2w_tiebreaker": 0.0,
            },
            {
                "rebalance_date": "2024-01-31",
                "ticker": "BAD",
                "portfolio_kind": "concentrated",
                "weight": 0.05,
                "target_weight": 0.05,
                "concentrated_cashfunded_early_entry_applied": True,
                "rs_benchmark_2w_tiebreaker": -0.02,
                "rs_benchmark_2w_tiebreaker_coverage": True,
            },
            {
                "rebalance_date": "2024-01-31",
                "ticker": "CASH",
                "portfolio_kind": "concentrated",
                "weight": 0.45,
                "target_weight": 0.45,
                "concentrated_cashfunded_early_entry_applied": False,
                "rs_benchmark_2w_tiebreaker": 0.0,
            },
            {
                "rebalance_date": "2024-07-31",
                "ticker": "GOOD",
                "portfolio_kind": "concentrated",
                "weight": 0.05,
                "target_weight": 0.05,
                "concentrated_cashfunded_early_entry_applied": True,
                "rs_benchmark_2w_tiebreaker": 0.08,
                "rs_benchmark_2w_tiebreaker_coverage": True,
            },
            {
                "rebalance_date": "2024-07-31",
                "ticker": "CASH",
                "portfolio_kind": "concentrated",
                "weight": 0.95,
                "target_weight": 0.95,
                "concentrated_cashfunded_early_entry_applied": False,
                "rs_benchmark_2w_tiebreaker": 0.0,
            },
        ]
    )
    raw["rebalance_date"] = pd.to_datetime(raw["rebalance_date"])
    threshold = learn_is_threshold(raw, oos_start="2024-06-03")
    assert threshold == -0.02

    out, telemetry = build_arm_book(raw, arm="rs2w_positive", threshold=threshold)
    jan = out[pd.to_datetime(out["rebalance_date"]).dt.strftime("%Y-%m-%d").eq("2024-01-31")]
    assert "BAD" not in set(jan["ticker"].astype(str))
    cash = jan[jan["ticker"].astype(str).eq("CASH")].iloc[0]
    assert abs(float(cash["weight"]) - 0.50) < 1e-9
    removed = telemetry[telemetry["action"].eq("removed_to_cash")]
    assert len(removed) == 1
    assert removed.iloc[0]["ticker"] == "BAD"


if __name__ == "__main__":
    test_rs2w_tiebreaker_removes_failed_entry_to_cash()
    print("rs_timing_tiebreaker_broker_ab_smoke: PASS")
