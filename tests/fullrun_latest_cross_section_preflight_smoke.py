#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import run_fullrun_latest_cross_section_preflight as preflight  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def fixture(root: Path) -> argparse.Namespace:
    latest = root / "outputs"
    reports = latest / "reports"
    cache = root / "cache_prices"
    reports.mkdir(parents=True)
    cache.mkdir()
    valuation_date = "2026-07-31"
    available = "2026-07-31T20:00:00Z"
    scored = pd.DataFrame(
        {
            "rebalance_date": [valuation_date, valuation_date],
            "valuation_price_cutoff_date": [valuation_date, valuation_date],
            "feature_available_from": [available, available],
            "ticker": ["AAA", "BBB"],
            "ranking_eligible": [True, True],
        }
    )
    scored.to_csv(latest / "scored_latest.csv", index=False)
    pd.concat(
        [
            scored.assign(rebalance_date="2026-06-30", valuation_price_cutoff_date="2026-06-30", feature_available_from="2026-06-30T20:00:00Z"),
            scored,
        ],
        ignore_index=True,
    ).to_csv(reports / "candidate_replay_book.csv", index=False)
    scored.iloc[[0]].assign(weight=1.0).to_csv(latest / "portfolio_latest.csv", index=False)
    scored.iloc[[1]].assign(weight=1.0).to_csv(
        latest / "concentrated_portfolio_latest.csv", index=False
    )
    for ticker in ("AAA", "BBB"):
        pd.DataFrame(
            {"Close": [100.0], "Adj Close": [100.0], "Volume": [1_000_000]},
            index=pd.DatetimeIndex([valuation_date]),
        ).to_parquet(cache / px_cache_name(ticker))
    return argparse.Namespace(
        latest_run=str(latest),
        price_cache=str(cache),
        valuation_date=valuation_date,
        decision_time_utc="2026-08-01T03:00:00Z",
        output_dir=str(root / "preflight"),
        min_scored_rows=2,
        strict=True,
    )


def test_latest_cross_section_is_exact_close_and_hash_recorded() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        args = fixture(root)
        ready = preflight.build(args)
        assert ready["ready"] is True
        assert ready["monthly_rebalance_due"] is True
        assert ready["current_fullrun_cross_section_recomputed"] is True
        assert ready["current_fullrun_target_proposals_recomputed"] is True
        assert ready["same_close_daily_selector_recomputed"] is False
        assert ready["coverage"]["exact_close_coverage_ratio"] == 1.0
        assert all(item["sha256"] for item in ready["artifacts"].values())

        scored_path = root / "outputs" / "scored_latest.csv"
        scored = pd.read_csv(scored_path)
        scored.loc[0, "feature_available_from"] = "2026-07-31T21:00:00Z"
        scored.to_csv(scored_path, index=False)
        blocked = preflight.build(args)
        assert blocked["ready"] is False
        assert any(
            item.startswith("scored_latest_feature_available_from_close_mismatch_rows")
            for item in blocked["contract_failures"]
        )

        args.decision_time_utc = ""
        try:
            preflight.build(args)
        except ValueError as exc:
            assert "cannot be blank" in str(exc)
        else:
            raise AssertionError("blank decision_time_utc must fail closed")


if __name__ == "__main__":
    test_latest_cross_section_is_exact_close_and_hash_recorded()
    print("fullrun_latest_cross_section_preflight_smoke: PASS")
