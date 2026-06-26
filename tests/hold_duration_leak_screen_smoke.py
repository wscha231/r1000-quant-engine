#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_hold_duration_leak_screen import drop_rows_for_portfolio, summarize_drops  # noqa: E402


def test_drop_rows_join_premature_audit_and_mark_pit_candidate() -> None:
    book = pd.DataFrame(
        [
            {
                "rebalance_date": "2021-05-31",
                "ticker": "KEEP",
                "weight": 0.2,
                "alphaops_vnext_score": 2.0,
                "holding_state": "HOLD",
                "hold_replace_decision": "keep_prior_holding",
                "leader_tier": "DUAL_LEADER",
                "primary_lane": "MARKET_LEADER",
                "rs_benchmark_3m": 0.10,
                "rs_benchmark_6m": 0.20,
                "price_above_ma200": 1.0,
                "price_above_ma50": 1.0,
            },
            {
                "rebalance_date": "2021-06-30",
                "ticker": "NEW",
                "weight": 0.2,
            },
        ]
    )
    book["rebalance_date"] = pd.to_datetime(book["rebalance_date"]).dt.normalize()
    audit = pd.DataFrame(
        [
            {
                "portfolio": "concentrated",
                "ticker": "KEEP",
                "sell_date": "2021-07-01",
                "leader_state_at_exit": "EXIT_REPLACE",
                "sold_forward_return_126d": 0.30,
                "same_day_replacement_return_126d": 0.10,
                "premature_sell_excess_126d": 0.20,
                "premature_sell_candidate": True,
            }
        ]
    )
    audit["sell_date"] = pd.to_datetime(audit["sell_date"]).dt.normalize()

    rows = drop_rows_for_portfolio(book, audit, "concentrated")

    assert len(rows) == 1
    row = rows[0]
    assert row["ticker"] == "KEEP"
    assert row["audit_matched"] is True
    assert row["pit_leader_hold_candidate"] is True
    assert row["positive_excess_126d"] is True
    assert row["premature_sell_excess_126d"] == 0.20


def test_summarize_drops_reports_candidate_base_rate() -> None:
    rows = [
        {
            "portfolio": "main",
            "audit_matched": True,
            "positive_excess_126d": True,
            "pit_leader_hold_candidate": True,
            "premature_sell_excess_126d": 0.10,
            "prior_leader_tier": "DUAL_LEADER",
            "prior_holding_state": "HOLD",
        },
        {
            "portfolio": "main",
            "audit_matched": True,
            "positive_excess_126d": False,
            "pit_leader_hold_candidate": True,
            "premature_sell_excess_126d": -0.05,
            "prior_leader_tier": "DUAL_LEADER",
            "prior_holding_state": "HOLD",
        },
    ]
    summary = summarize_drops(rows, "main")

    assert summary["dropped_rows"] == 2
    assert summary["pit_leader_hold_candidate_rows"] == 2
    assert summary["pit_leader_hold_candidate_positive_rate"] == 0.5
    assert abs(summary["pit_leader_hold_candidate_mean_excess_126d"] - 0.025) < 1e-9
    assert summary["pit_leader_hold_candidate_verdict"] == "candidate_mixed_or_negative"


if __name__ == "__main__":
    test_drop_rows_join_premature_audit_and_mark_pit_candidate()
    test_summarize_drops_reports_candidate_base_rate()
    print("hold_duration_leak_screen_smoke passed")
