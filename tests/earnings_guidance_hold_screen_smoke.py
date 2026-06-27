#!/usr/bin/env python3
from __future__ import annotations

import tempfile
from argparse import Namespace
from pathlib import Path

import pandas as pd

import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.run_earnings_guidance_hold_screen as screen  # noqa: E402


def test_primary_candidate_requires_is_oos_positive_sample() -> None:
    rows = []
    for i in range(40):
        date = "2020-01-31" if i < 32 else "2025-01-31"
        rows.append(
            {
                "portfolio": "concentrated",
                "ticker": f"T{i}",
                "prior_rebalance_date": date,
                "drop_rebalance_date": date,
                "audit_matched": True,
                "pit_leader_hold_candidate": True,
                "premature_sell_excess_126d": 0.10 if i % 2 == 0 else 0.02,
                "positive_excess_126d": True,
            }
        )
    book_rows = [
        {
            "rebalance_date": row["prior_rebalance_date"],
            "ticker": row["ticker"],
            "actual_results_score": 0.5,
            "event_reaction_score": 0.2,
            "eps_revision_score": 0.0,
            "selection_confirmation_score": 0.7,
            "leader_tier": "DUAL_LEADER",
            "holding_state": "HOLD",
        }
        for row in rows
    ]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "outputs"
        target = latest / "alphaops_vnext" / "official_concentrated_target_book.csv"
        drops = root / "hold_duration_leak_screen" / "drop_leak_rows.csv"
        target.parent.mkdir(parents=True)
        drops.parent.mkdir(parents=True)
        pd.DataFrame(book_rows).to_csv(target, index=False)
        pd.DataFrame(rows).to_csv(drops, index=False)
        payload = screen.run(
            Namespace(
                latest_run=str(latest),
                output_dir=str(root / "screen"),
                portfolio="concentrated",
                target_book="",
                drop_rows="",
            )
        )

        assert payload["primary_candidate"]["evaluation"]["screen_pass"] is True
        assert payload["primary_candidate"]["summaries"]["full"]["rows"] == 40
        assert payload["primary_candidate"]["summaries"]["oos"]["rows"] == 8
        assert (root / "screen" / "summary.json").exists()
        assert (root / "screen" / "primary_candidate_rows.csv").exists()


def test_negative_oos_blocks_hook_design() -> None:
    rows = []
    for i in range(40):
        date = "2020-01-31" if i < 32 else "2025-01-31"
        rows.append(
            {
                "portfolio": "concentrated",
                "ticker": f"T{i}",
                "prior_rebalance_date": date,
                "drop_rebalance_date": date,
                "audit_matched": True,
                "pit_leader_hold_candidate": True,
                "premature_sell_excess_126d": 0.05 if i < 32 else -0.10,
                "positive_excess_126d": i < 32,
            }
        )
    book_rows = [
        {"rebalance_date": row["prior_rebalance_date"], "ticker": row["ticker"], "actual_results_score": 1.0}
        for row in rows
    ]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "outputs"
        target = latest / "alphaops_vnext" / "official_concentrated_target_book.csv"
        drops = root / "hold_duration_leak_screen" / "drop_leak_rows.csv"
        target.parent.mkdir(parents=True)
        drops.parent.mkdir(parents=True)
        pd.DataFrame(book_rows).to_csv(target, index=False)
        pd.DataFrame(rows).to_csv(drops, index=False)
        payload = screen.run(
            Namespace(
                latest_run=str(latest),
                output_dir=str(root / "screen"),
                portfolio="concentrated",
                target_book="",
                drop_rows="",
            )
        )

        assert payload["primary_candidate"]["evaluation"]["screen_pass"] is False
        assert payload["primary_candidate"]["evaluation"]["gates"]["oos_mean_positive"] is False
        assert payload["primary_candidate"]["evaluation"]["next_action"] == "do_not_design_hook"


if __name__ == "__main__":
    test_primary_candidate_requires_is_oos_positive_sample()
    test_negative_oos_blocks_hook_design()
    print("earnings_guidance_hold_screen_smoke: PASS")
