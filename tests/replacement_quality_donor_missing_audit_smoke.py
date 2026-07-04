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

from tools.run_replacement_quality_donor_missing_audit import run  # noqa: E402


def write_csv(path: Path, rows: list[dict]) -> None:
    pd.DataFrame(rows).to_csv(path, index=False)


def test_donor_missing_audit_classifies_generated_book_gap() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        fixed_swaps = root / "fixed_swaps.csv"
        fixed_book = root / "fixed_book.csv"
        generated_book = root / "generated_book.csv"
        candidate_book = root / "candidate_book.csv"
        rejections = root / "rejections.csv"
        output = root / "out"

        write_csv(
            fixed_swaps,
            [
                {
                    "rebalance_date": "2026-01-31",
                    "added_ticker": "WIN",
                    "removed_ticker": "OLD",
                    "replacement_weight": 0.2,
                },
                {
                    "rebalance_date": "2026-02-28",
                    "added_ticker": "MISS",
                    "removed_ticker": "DONOR",
                    "replacement_weight": 0.3,
                },
            ],
        )
        write_csv(
            fixed_book,
            [
                {"rebalance_date": "2026-01-31", "ticker": "OLD", "weight": 0.2},
                {"rebalance_date": "2026-01-31", "ticker": "KEEP", "weight": 0.3},
                {"rebalance_date": "2026-02-28", "ticker": "DONOR", "weight": 0.3},
                {"rebalance_date": "2026-02-28", "ticker": "KEEP", "weight": 0.2},
            ],
        )
        write_csv(
            generated_book,
            [
                {
                    "rebalance_date": "2026-01-31",
                    "ticker": "WIN",
                    "weight": 0.2,
                    "concentrated_replacement_quality_applied": True,
                    "concentrated_replacement_quality_removed_ticker": "OLD",
                },
                {"rebalance_date": "2026-01-31", "ticker": "KEEP", "weight": 0.3},
                {"rebalance_date": "2026-02-28", "ticker": "OTHER", "weight": 0.3},
                {"rebalance_date": "2026-02-28", "ticker": "KEEP", "weight": 0.2},
            ],
        )
        write_csv(
            candidate_book,
            [
                {
                    "rebalance_date": "2026-01-31",
                    "ticker": "WIN",
                    "leader_rank_ex_ante": 4,
                    "revenue_growth": 0.2,
                },
                {
                    "rebalance_date": "2026-02-28",
                    "ticker": "MISS",
                    "leader_rank_ex_ante": 5,
                    "revenue_growth": 0.3,
                },
            ],
        )
        write_csv(
            rejections,
            [
                {
                    "rebalance_date": "2026-01-31",
                    "ticker": "WIN",
                    "portfolio_kind": "concentrated",
                    "rejection_reason": "hold_replace_threshold_not_met",
                    "replacement_test_weakest_ticker": "OLD",
                },
                {
                    "rebalance_date": "2026-02-28",
                    "ticker": "MISS",
                    "portfolio_kind": "concentrated",
                    "rejection_reason": "hold_replace_threshold_not_met",
                    "replacement_test_weakest_ticker": "DONOR",
                },
            ],
        )

        payload = run(
            argparse.Namespace(
                fixed_swaps=str(fixed_swaps),
                fixed_book=str(fixed_book),
                generated_book=str(generated_book),
                candidate_book=str(candidate_book),
                policy_rejections=str(rejections),
                output_dir=str(output),
            )
        )

        assert payload["status"] == "completed"
        assert payload["exact_hook_match_count"] == 1
        assert payload["generated_missing_fixed_donor_count"] == 1
        assert payload["classification_counts"]["exact_match"] == 1
        assert payload["classification_counts"]["generated_book_missing_fixed_donor"] == 1
        assert payload["fullrun_allowed"] is False
        assert payload["production_activation_allowed"] is False
        detail = pd.read_csv(output / "donor_missing_detail.csv")
        missing = detail[detail["classification"].eq("generated_book_missing_fixed_donor")].iloc[0]
        assert missing["added_ticker"] == "MISS"
        assert bool(missing["candidate_present"]) is True
        assert bool(missing["policy_rejection_exact"]) is True
        assert (output / "report.md").exists()
        assert json.loads((output / "summary.json").read_text(encoding="utf-8"))["status"] == "completed"


def main() -> int:
    test_donor_missing_audit_classifies_generated_book_gap()
    print("replacement_quality_donor_missing_audit_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
