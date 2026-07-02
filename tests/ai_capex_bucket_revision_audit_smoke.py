#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_ai_capex_bucket_revision_audit import run  # noqa: E402


class Args:
    pass


def test_bucket_audit_outputs_exposure_contribution_and_missed_candidates() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        target = root / "target.csv"
        cand = root / "candidate.csv"
        pd.DataFrame(
            [
                {
                    "rebalance_date": "2026-01-31",
                    "ticker": "MU",
                    "Name": "Micron",
                    "industry_group": "Semiconductors",
                    "selection_reason": "memory hbm datacenter",
                    "weight": 0.30,
                    "rs_benchmark_3m": 0.12,
                    "actual_results_score": 1.0,
                    "period_forward_return": 0.20,
                },
                {
                    "rebalance_date": "2026-01-31",
                    "ticker": "CASH",
                    "Name": "Cash",
                    "weight": 0.70,
                },
            ]
        ).to_csv(target, index=False)
        pd.DataFrame(
            [
                {
                    "rebalance_date": "2026-01-31",
                    "ticker": "WDC",
                    "Name": "Western Digital",
                    "industry_group": "Storage",
                    "selection_reason": "enterprise ssd nand datacenter storage",
                    "score": 9.0,
                    "rs_benchmark_3m": 0.15,
                    "actual_results_score": 1.0,
                    "period_forward_return": 0.10,
                },
                {
                    "rebalance_date": "2026-01-31",
                    "ticker": "MU",
                    "Name": "Micron",
                    "industry_group": "Semiconductors",
                    "selection_reason": "already selected",
                    "score": 8.0,
                    "rs_benchmark_3m": 0.12,
                },
            ]
        ).to_csv(cand, index=False)
        args = Args()
        args.target_book = str(target)
        args.candidate_book = str(cand)
        args.output_dir = str(root / "out")
        args.top_missed_per_date = 5
        payload = run(args)
        assert payload["status"] == "completed"
        assert payload["ai_selected_row_count"] >= 1
        assert payload["missed_candidate_count"] >= 1
        exposure = pd.read_csv(root / "out" / "bucket_exposure_by_rebalance.csv")
        contribution = pd.read_csv(root / "out" / "bucket_contribution.csv")
        missed = pd.read_csv(root / "out" / "missed_bucket_candidates.csv")
        assert not exposure.empty
        assert not contribution.empty
        assert "WDC" in set(missed["ticker"])
        assert payload["used_forward_return_in_ranking"] is False


def main() -> int:
    test_bucket_audit_outputs_exposure_contribution_and_missed_candidates()
    print("ai_capex_bucket_revision_audit_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
