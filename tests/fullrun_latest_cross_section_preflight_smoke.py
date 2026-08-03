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
    pipeline_source = (ROOT / "r1000_pipeline.py").read_text(encoding="utf-8")
    operational_view = pipeline_source[
        pipeline_source.index("def _build_operational_view(") :
        pipeline_source.index("def _enrich_with_live_state(")
    ]
    for column in (
        '"rebalance_date"',
        '"valuation_price_cutoff_date"',
        '"feature_available_from"',
    ):
        assert column in operational_view, column
    producer_block = pipeline_source[
        pipeline_source.index(
            "portfolio_latest = _annotate_output_frame(portfolio_latest"
        ) : pipeline_source.index(
            "top30_operational = _build_operational_view(top30"
        )
    ]
    assert (
        "portfolio_latest = attach_decision_time_provenance(portfolio_latest)"
        in producer_block
    )

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
        assert all(
            item["ready"] for item in ready["target_proposal_audits"].values()
        )

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

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        args = fixture(root)
        main_path = root / "outputs" / "portfolio_latest.csv"
        main = pd.read_csv(main_path)
        main.loc[0, "ticker"] = "ZZZ"
        main.to_csv(main_path, index=False)
        blocked = preflight.build(args)
        audit = blocked["target_proposal_audits"]["main_target_proposal"]
        assert audit["ready"] is False
        assert audit["ineligible_or_unexpected_tickers"] == ["ZZZ"]
        assert audit["missing_exact_close_tickers"] == ["ZZZ"]

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        args = fixture(root)
        main_path = root / "outputs" / "portfolio_latest.csv"
        main = pd.read_csv(main_path)
        main.loc[0, "feature_available_from"] = "2026-07-31T21:00:00Z"
        main.to_csv(main_path, index=False)
        blocked = preflight.build(args)
        assert any(
            item.startswith(
                "main_target_proposal_feature_available_from_close_mismatch_rows"
            )
            for item in blocked["contract_failures"]
        )

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        args = fixture(root)
        main_path = root / "outputs" / "portfolio_latest.csv"
        main = pd.read_csv(main_path)
        pd.concat([main, main], ignore_index=True).to_csv(main_path, index=False)
        blocked = preflight.build(args)
        assert "main_target_proposal_duplicate_tickers:1" in blocked["contract_failures"]

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        args = fixture(root)
        scored_path = root / "outputs" / "scored_latest.csv"
        scored = pd.read_csv(scored_path).drop(columns=["ranking_eligible"])
        scored.to_csv(scored_path, index=False)
        blocked = preflight.build(args)
        assert "scored_latest_missing_columns:ranking_eligible" in blocked[
            "contract_failures"
        ]

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        args = fixture(root)
        pd.DataFrame(
            {"Close": [0.0], "Adj Close": [0.0], "Volume": [1_000_000]},
            index=pd.DatetimeIndex(["2026-07-31"]),
        ).to_parquet(root / "cache_prices" / px_cache_name("AAA"))
        blocked = preflight.build(args)
        assert "eligible_ticker_exact_close_missing:1" in blocked["contract_failures"]
        assert blocked["target_proposal_audits"]["main_target_proposal"][
            "missing_exact_close_tickers"
        ] == ["AAA"]


if __name__ == "__main__":
    test_latest_cross_section_is_exact_close_and_hash_recorded()
    print("fullrun_latest_cross_section_preflight_smoke: PASS")
