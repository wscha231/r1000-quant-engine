#!/usr/bin/env python3
"""Synthetic checks for same-close selector provenance."""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import audit_run287_same_close_selector_snapshot as audit  # noqa: E402


def run(root: Path, rows: list[dict[str, object]], name: str) -> tuple[dict, pd.DataFrame]:
    candidate = root / f"{name}.csv"
    session = root / "session.json"
    output = root / name
    pd.DataFrame(rows).to_csv(candidate, index=False)
    session.write_text(json.dumps({"session_date": "2026-07-16"}), encoding="utf-8")
    result = audit.build(
        argparse.Namespace(
            contract=str(ROOT / "docs" / "run287_same_close_selector_snapshot_contract_v1.json"),
            candidate_book=str(candidate),
            session_json=str(session),
            recorded_at_utc="2026-07-17T04:30:00Z",
            source_run_id="synthetic",
            source_commit_sha="abc",
            output_dir=str(output),
        )
    )
    return result, pd.read_csv(output / "selector_snapshot_readiness.csv")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="run287-selector-provenance-") as raw:
        root = Path(raw)
        legacy, legacy_rows = run(
            root,
            [
                {"ticker": "AAA", "daily_candidate_source": "outputs/portfolio_latest.csv", "rebalance_date": "2026-07-16"},
                {"ticker": "BBB", "daily_candidate_source": "outputs/concentrated_portfolio_latest.csv", "rebalance_date": "2026-05-08", "feature_date": "2026-05-08"},
            ],
            "legacy",
        )
        assert legacy["status"] == audit.BLOCKED_STATUS
        main_row = legacy_rows.set_index("portfolio_kind").loc["main"]
        assert main_row["signal_date_coverage"] == 0.0
        assert "missing_signal_provenance" in main_row["blockers"]
        concentrated = legacy_rows.set_index("portfolio_kind").loc["concentrated"]
        assert "signal_not_same_close" in concentrated["blockers"]

        ready, ready_rows = run(
            root,
            [
                {
                    "portfolio_kind": "main",
                    "ticker": "CCC",
                    "signal_source_date": "2026-07-16",
                    "valuation_close_date": "2026-07-16",
                    "same_close_rank_recomputed": True,
                    "selector_selected": True,
                    "decision_feature_complete_bool": True,
                    "final_rank": 1,
                },
                {
                    "portfolio_kind": "concentrated",
                    "ticker": "DDD",
                    "signal_source_date": "2026-07-16",
                    "valuation_close_date": "2026-07-16",
                    "same_close_rank_recomputed": True,
                    "selector_selected": True,
                    "decision_feature_complete_bool": True,
                    "final_rank": 1,
                },
            ],
            "ready",
        )
        assert ready["status"] == audit.READY_STATUS
        assert bool(ready_rows["same_close_selector_ready"].all())
        assert ready["target_books_mutated"] is False
        assert ready["orders_generated"] is False

    print("run287_same_close_selector_snapshot_smoke: PASS")


if __name__ == "__main__":
    main()
