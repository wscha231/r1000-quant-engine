#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_replacement_quality_event_reconciliation import run  # noqa: E402


def _write_csv(path: Path, rows: list[dict]) -> None:
    pd.DataFrame(rows).to_csv(path, index=False)


def _run(root: Path, hook_rows: list[dict], output_name: str = "out") -> dict:
    fixed = root / "fixed.csv"
    policy = root / "policy.csv"
    hook = root / "hook.csv"
    _write_csv(
        fixed,
        [
            {
                "rule": "rank_top15_and_revenue_ge10",
                "rebalance_date": "2026-01-31",
                "added_ticker": "WIN1",
                "removed_ticker": "OLD1",
                "leader_rank_ex_ante": 4,
                "revenue_growth": 0.25,
                "forward_labels_used_for_ranking": False,
            },
            {
                "rule": "rank_top15_and_revenue_ge10",
                "rebalance_date": "2026-02-28",
                "added_ticker": "WIN2",
                "removed_ticker": "OLD2",
                "leader_rank_ex_ante": 8,
                "revenue_growth": 0.20,
                "forward_labels_used_for_ranking": False,
            },
        ],
    )
    _write_csv(
        policy,
        [
            {
                "rebalance_date": "2026-01-31",
                "ticker": "WIN1",
                "portfolio_kind": "concentrated",
                "rejection_reason": "hold_replace_threshold_not_met",
                "replacement_test_weakest_ticker": "OLD1",
            },
            {
                "rebalance_date": "2026-02-28",
                "ticker": "WIN2",
                "portfolio_kind": "concentrated",
                "rejection_reason": "hold_replace_threshold_not_met",
                "replacement_test_weakest_ticker": "OLD2",
            },
            {
                "rebalance_date": "2026-03-31",
                "ticker": "EXTRA",
                "portfolio_kind": "concentrated",
                "rejection_reason": "hold_replace_threshold_not_met",
                "replacement_test_weakest_ticker": "OLD3",
            },
        ],
    )
    _write_csv(hook, hook_rows)
    return run(
        argparse.Namespace(
            fixed_swaps=str(fixed),
            policy_rejections=str(policy),
            hook_target_book=str(hook),
            output_dir=str(root / output_name),
            swap_count_tolerance_pct=0.10,
            max_swaps_per_date=1,
            rejection_reasons="hold_replace_threshold_not_met",
        )
    )


def test_event_reconciliation_passes_exact_subset() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        payload = _run(
            root,
            [
                {
                    "rebalance_date": "2026-01-31",
                    "ticker": "WIN1",
                    "concentrated_replacement_quality_applied": True,
                    "concentrated_replacement_quality_added_ticker": "WIN1",
                    "concentrated_replacement_quality_removed_ticker": "OLD1",
                    "concentrated_replacement_quality_source_rejection_reason": "hold_replace_threshold_not_met",
                    "concentrated_replacement_quality_leader_rank_ex_ante": 4,
                    "concentrated_replacement_quality_revenue_growth": 0.25,
                },
                {
                    "rebalance_date": "2026-02-28",
                    "ticker": "WIN2",
                    "concentrated_replacement_quality_applied": True,
                    "concentrated_replacement_quality_added_ticker": "WIN2",
                    "concentrated_replacement_quality_removed_ticker": "OLD2",
                    "concentrated_replacement_quality_source_rejection_reason": "hold_replace_threshold_not_met",
                    "concentrated_replacement_quality_leader_rank_ex_ante": 8,
                    "concentrated_replacement_quality_revenue_growth": 0.20,
                },
            ],
        )
        assert payload["status"] == "ready_for_event_matched_broker_ab"
        assert payload["blockers"] == []
        assert payload["event_reconciliation"]["exact_match_count"] == 2
        assert payload["event_reconciliation"]["hook_is_subset_of_fixed"] is True
        assert payload["production_activation_allowed"] is False
        assert (root / "out" / "event_diff.csv").exists()


def test_event_reconciliation_blocks_policy_only_and_future_available_from() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        payload = _run(
            root,
            [
                {
                    "rebalance_date": "2026-01-31",
                    "ticker": "WIN1",
                    "concentrated_replacement_quality_applied": True,
                    "concentrated_replacement_quality_added_ticker": "WIN1",
                    "concentrated_replacement_quality_removed_ticker": "OLD1",
                    "concentrated_replacement_quality_source_rejection_reason": "hold_replace_threshold_not_met",
                    "leader_rank_available_from": "2026-02-01",
                },
                {
                    "rebalance_date": "2026-03-31",
                    "ticker": "EXTRA",
                    "concentrated_replacement_quality_applied": True,
                    "concentrated_replacement_quality_added_ticker": "EXTRA",
                    "concentrated_replacement_quality_removed_ticker": "OLD3",
                    "concentrated_replacement_quality_source_rejection_reason": "hold_replace_threshold_not_met",
                },
            ],
            output_name="bad",
        )
        assert payload["status"] == "blocked"
        assert "hook_swaps_not_subset_of_fixed_book_counterfactual" in payload["blockers"]
        assert "hook_swap_count_outside_tolerance" not in payload["blockers"]
        assert "future_available_from" in payload["blockers"]
        assert payload["event_reconciliation"]["policy_only_hook_count"] == 1


def main() -> int:
    test_event_reconciliation_passes_exact_subset()
    test_event_reconciliation_blocks_policy_only_and_future_available_from()
    print("replacement_quality_event_reconciliation_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
