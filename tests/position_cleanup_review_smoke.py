#!/usr/bin/env python3
from __future__ import annotations

import tempfile
from argparse import Namespace
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_position_cleanup_review import build_review


def test_position_cleanup_review_flags_dust_and_projection() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "latest"
        (latest / "operating_snapshot").mkdir(parents=True)
        pd.DataFrame(
            [
                {
                    "portfolio_kind": "main",
                    "ticker": "DUST",
                    "current_weight": 0.003,
                    "current_shares": 1,
                    "daily_review_action": "EXIT_REVIEW",
                },
                {
                    "portfolio_kind": "main",
                    "ticker": "HOLD",
                    "current_weight": 0.004,
                    "current_shares": 1,
                    "daily_review_action": "SHAKEOUT_GUARD",
                },
                {
                    "portfolio_kind": "main",
                    "ticker": "ADD",
                    "current_weight": 0.004,
                    "current_shares": 1,
                    "daily_review_action": "",
                },
                {
                    "portfolio_kind": "concentrated",
                    "ticker": "SMALL",
                    "current_weight": 0.04,
                    "current_shares": 2,
                    "daily_review_action": "EXIT_REVIEW",
                },
            ]
        ).to_csv(latest / "operating_snapshot" / "current_operating_holdings_latest.csv", index=False)
        pd.DataFrame(
            [
                {"ticker": "DUST", "weight": 0.002},
                {"ticker": "HOLD", "weight": 0.002},
                {"ticker": "ADD", "weight": 0.02},
                {"ticker": "NEW", "weight": 0.03},
            ]
        ).to_csv(latest / "portfolio_latest.csv", index=False)
        pd.DataFrame([{"ticker": "SMALL", "weight": 0.03}, {"ticker": "BIG", "weight": 0.5}]).to_csv(
            latest / "concentrated_portfolio_latest.csv",
            index=False,
        )

        payload = build_review(Namespace(latest_run=str(latest), output_dir=str(root / "out"), main_dust_threshold=0.005, main_min_target_weight=0.01, emerging_min_target_weight=0.0075, concentrated_min_target_weight=0.08))
        out = root / "out"
        report = pd.read_csv(out / "dust_positions_report.csv")
        actions = dict(zip(report["ticker"], report["cleanup_action"]))
        assert actions["DUST"] == "FULL_EXIT_REVIEW"
        assert actions["HOLD"] == "HOLD_REVIEW"
        assert actions["ADD"] == "INCREASE_TO_MEANINGFUL_WEIGHT_REVIEW"
        assert actions["SMALL"] == "FULL_EXIT_REVIEW"
        assert actions["NEW"] == "NEW_POSITION_REVIEW"
        projected = pd.read_csv(out / "projected_holdings_after_ready_orders.csv")
        assert "projected_weight_after_cleanup_review" in projected.columns
        orders = pd.read_csv(out / "dust_cleanup_orders.csv")
        assert {"FULL_EXIT_REVIEW", "INCREASE_TO_MEANINGFUL_WEIGHT_REVIEW", "NEW_POSITION_REVIEW"} <= set(orders["cleanup_action"])
        assert payload["production_activation_allowed"] is False


if __name__ == "__main__":
    test_position_cleanup_review_flags_dust_and_projection()
    print("position_cleanup_review_smoke: PASS")
