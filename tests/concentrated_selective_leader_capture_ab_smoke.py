#!/usr/bin/env python3
"""Smoke tests for concentrated selective leader capture A/B helpers."""
from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.run_concentrated_selective_leader_capture_ab import (  # noqa: E402
    classify_result,
    delta_metrics,
    summarize_selective_capture,
)


def test_delta_and_classification_require_applied_and_broker_window() -> None:
    base = {
        "metric_mode": "broker_ledger_next_close",
        "years": 7.05,
        "cagr": 0.46,
        "max_dd": -0.246,
        "sharpe": 1.4,
    }
    treatment = {
        "metric_mode": "broker_ledger_next_close",
        "years": 7.05,
        "cagr": 0.485,
        "max_dd": -0.249,
        "sharpe": 1.45,
    }
    summary = {
        "arms": {
            "baseline": {"metrics": {"main": base, "concentrated": base}},
            "selective_capture_on": {"metrics": {"main": base, "concentrated": treatment}},
        },
        "deltas": {
            "main": delta_metrics(base, base),
            "concentrated": delta_metrics(base, treatment),
        },
        "selective_capture_diagnostics": {"total_applied_count": 3},
    }
    assert classify_result(summary, min_years=7.0) == "research_pass"

    no_op = dict(summary)
    no_op["selective_capture_diagnostics"] = {"total_applied_count": 0}
    assert classify_result(no_op, min_years=7.0) == "no_op"

    invalid = dict(summary)
    invalid["arms"] = {
        "baseline": {"metrics": {"main": dict(base, years=6.9), "concentrated": base}},
        "selective_capture_on": {"metrics": {"main": base, "concentrated": treatment}},
    }
    assert classify_result(invalid, min_years=7.0) == "blocked_invalid_window"


def test_summarize_selective_capture_counts_target_and_reject_applied() -> None:
    with TemporaryDirectory() as td:
        root = Path(td)
        pd.DataFrame(
            [
                {
                    "rebalance_date": "2026-01-31",
                    "ticker": "HIT",
                    "concentrated_selective_leader_capture_applied": True,
                    "concentrated_selective_leader_capture_reason": "rs3_ge_20pct_pit_leader_gap_credit",
                    "concentrated_selective_leader_capture_gap_credit": 0.07,
                    "rs_spy_3m": 0.25,
                },
                {
                    "rebalance_date": "2026-02-28",
                    "ticker": "MISS",
                    "concentrated_selective_leader_capture_applied": False,
                    "concentrated_selective_leader_capture_reason": "rs_spy_3m_below_0.20",
                },
            ]
        ).to_csv(root / "official_concentrated_target_book.csv", index=False)
        pd.DataFrame(
            [
                {
                    "rebalance_date": "2026-03-31",
                    "ticker": "TRY",
                    "portfolio_kind": "concentrated",
                    "concentrated_selective_leader_capture_applied": True,
                    "concentrated_selective_leader_capture_reason": "rs3_ge_20pct_pit_leader_gap_credit",
                    "concentrated_selective_leader_capture_gap_credit": 0.07,
                    "rejection_reason": "hold_replace_threshold_not_met",
                    "rs_spy_3m": 0.30,
                },
                {
                    "rebalance_date": "2026-03-31",
                    "ticker": "MAIN",
                    "portfolio_kind": "main",
                    "concentrated_selective_leader_capture_applied": True,
                    "concentrated_selective_leader_capture_reason": "should_be_filtered",
                },
            ]
        ).to_csv(root / "rejected_by_reason.csv", index=False)

        payload = summarize_selective_capture(root)
        assert payload["target_applied_count"] == 1
        assert payload["reject_applied_count"] == 1
        assert payload["total_applied_count"] == 2
        assert payload["target_samples"][0]["ticker"] == "HIT"
        assert payload["reject_samples"][0]["ticker"] == "TRY"


def main() -> int:
    test_delta_and_classification_require_applied_and_broker_window()
    test_summarize_selective_capture_counts_target_and_reject_applied()
    print("concentrated_selective_leader_capture_ab_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
