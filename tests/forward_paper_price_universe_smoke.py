#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.build_forward_paper_price_universe import build  # noqa: E402


def ranked_fixture() -> pd.DataFrame:
    rows = []
    for rank in range(1, 101):
        rows.append(
            {
                "ticker": f"T{rank:03d}",
                "free_data_selection_rank": rank,
                "free_data_base_selection_rank": 101 - rank,
                "free_data_selection_score": 101 - rank,
                "free_data_selection_label": "research_only_latest_overlay",
                "has_forward_estimate": int(rank <= 10),
                "free_data_forward_estimate_evidence_present": rank <= 10,
                "estimate_revision_confirmed": rank <= 10,
            }
        )
    return pd.DataFrame(rows)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ranked = root / "ranked.csv"
        ranked_fixture().to_csv(ranked, index=False)
        status = root / "status.csv"
        pd.DataFrame(
            [
                {"ticker": "OLD", "outcome_21d_status": "completed", "outcome_63d_status": "completed", "outcome_126d_status": "pending_not_elapsed"},
                {"ticker": "DONE", "outcome_21d_status": "completed", "outcome_63d_status": "completed", "outcome_126d_status": "completed"},
            ]
        ).to_csv(status, index=False)
        output = root / "price_universe.csv"
        summary = build(
            ranked_universe=ranked,
            current_status=status,
            output_csv=output,
            summary_json=root / "summary.json",
        )
        assert summary["status"] == "READY_FOR_BOUNDED_PRICE_REFRESH", summary
        assert summary["cohort_audit"]["cohort_counts"]["base_top30"] == 30
        assert summary["cohort_audit"]["cohort_counts"]["overlay_top30"] == 30
        assert summary["cohort_audit"]["cohort_counts"]["matched_control_ranks31_60"] == 30
        tickers = set(pd.read_csv(output)["ticker"])
        assert "SPY" in tickers
        assert "OLD" in tickers
        assert "DONE" not in tickers
        assert summary["price_universe_unique_ticker_count"] == len(tickers)
        assert summary["historical_signal_backfill_allowed"] is False
        assert summary["portfolio_mutation_allowed"] is False

        broken = ranked_fixture().drop(columns=["free_data_base_selection_rank"])
        broken_path = root / "broken.csv"
        broken.to_csv(broken_path, index=False)
        blocked_output = root / "blocked.csv"
        blocked = build(
            ranked_universe=broken_path,
            current_status=status,
            output_csv=blocked_output,
            summary_json=root / "blocked.json",
        )
        assert blocked["status"] == "BLOCKED_INCOMPLETE_COHORT"
        assert "contemporaneous_base_selection_rank_required" in blocked["blockers"]
        assert not blocked_output.exists()

    print("forward_paper_price_universe_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
