#!/usr/bin/env python3
"""Synthetic smoke test for fixed-control Run287 policy attribution."""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import audit_run287_policy_attribution as audit  # noqa: E402


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="run287-attribution-") as tmp_raw:
        tmp = Path(tmp_raw)
        tickers = ["AAA", "BBB", "CCC", "DDD"]
        selected = [True, True, False, False]
        returns = [0.20, 0.10, 0.05, 0.00]
        frame = pd.DataFrame(
            {
                "decision_date": ["2026-01-02"] * 4,
                "ticker": tickers,
                "portfolio_kind": ["main"] * 4,
                "scenario": ["strict"] * 4,
                "sector": ["Technology", "Industrials", "Technology", "Industrials"],
                "mktcap": [100, 90, 95, 85],
                "vol_252d": [0.20, 0.30, 0.21, 0.29],
                "published_rank": [1, 2, 3, 4],
                "published_ranking_eligible": [True] * 4,
                "published_score": [4.0, 3.0, 2.0, 1.0],
                "selector_selected": selected,
                "prior_holding": [True, True, False, False],
                "hold_replace_decision": ["hold", "replace", "", ""],
                "advisory_weight": [0.45, 0.45, 0.0, 0.0],
                "advisory_cash_weight": [0.10] * 4,
                "operating_target_weight": [0.44, 0.44, 0.0, 0.0],
                "simulated_fill_weight": [0.435, 0.435, 0.0, 0.0],
                "simulated_fill_shares": [4, 4, 0, 0],
                "advisory_to_operating_weight_delta": [-0.01, -0.01, 0.0, 0.0],
                "operating_to_fill_weight_delta": [-0.005, -0.005, 0.0, 0.0],
                "paper_cash_reconciliation_error_usd": [0.0] * 4,
                "path_reconciliation_status": ["SYNTHETIC_EXACT"] * 4,
                "outcome_63d_status": ["completed"] * 4,
                "outcome_63d_ticker_total_return": returns,
                "outcome_63d_spy_total_return": [0.04] * 4,
            }
        )
        current = tmp / "current_status.parquet"
        frame.to_parquet(current, index=False)
        args = argparse.Namespace(
            ledger_dir=str(tmp), current_status=str(current), output_dir=str(tmp),
            generated_at_utc="2026-07-16T00:00:00Z",
        )
        result = audit.run(args)
        assert result["status"] == "READY_POLICY_ATTRIBUTION_REVIEW_ONLY", result
        assert result["cash_reconciliation_within_one_cent"]
        selection = pd.read_csv(tmp / "selection_attribution.csv")
        row = selection.loc[selection["horizon_sessions"].eq(63)].iloc[0]
        assert row["matched_pair_count"] == 2
        assert row["selection_spread"] > 0
        execution = pd.read_csv(tmp / "execution_attribution.csv")
        assert execution.iloc[0]["status"] == "RECONCILED_REVIEW_ONLY"
        assert not result["model_mutated"]
        assert not result["target_books_mutated"]
        assert not result["orders_generated"]
        assert not result["live_trading_enabled"]
    print("run287_policy_attribution_smoke: PASS")


if __name__ == "__main__":
    main()
