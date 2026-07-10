#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_free_data_selection_overlay import build_overlay, parse_args, run  # noqa: E402


def test_overlay_promotes_confirmed_forward_evidence_and_penalizes_delisted() -> None:
    scored = pd.DataFrame(
        [
            {"ticker": "AAA", "score": 10.0, "concentrated_score": 1.0},
            {"ticker": "BBB", "score": 9.8, "concentrated_score": 0.98},
            {"ticker": "CCC", "score": 10.1, "concentrated_score": 1.01},
        ]
    )
    signals = pd.DataFrame(
        [
            {
                "ticker": "BBB",
                "available_from": "2026-07-09",
                "estimate_revision_confirmed": 1.0,
                "estimate_revision_replacement_gate_pass": 1.0,
                "est_eps_revision_breadth": 1.0,
                "est_eps_revision_30d": 0.2,
                "est_dispersion_change_30d": -0.2,
                "has_forward_estimate": 1.0,
            }
        ]
    )
    listing = pd.DataFrame(
        [
            {"symbol": "CCC", "status": "Delisted", "delisting_date": "2026-01-01"},
            {"symbol": "AAA", "status": "Active", "delisting_date": ""},
            {"symbol": "BBB", "status": "Active", "delisting_date": ""},
        ]
    )
    earnings = pd.DataFrame(
        [
            {"ticker": "BBB", "event_date": "2026-06-30", "estimated_eps": 1.0, "actual_eps": 1.2},
        ]
    )
    ranked, summary = build_overlay(
        scored,
        decision_date=pd.Timestamp("2026-07-10"),
        signals=signals,
        listing=listing,
        earnings_calendar=earnings,
        top_n=2,
    )
    assert summary["status"] == "completed"
    bbb = ranked[ranked["ticker"] == "BBB"].iloc[0]
    aaa = ranked[ranked["ticker"] == "AAA"].iloc[0]
    assert bbb["free_data_forward_estimate_score"] > aaa["free_data_forward_estimate_score"]
    ccc = ranked[ranked["ticker"] == "CCC"].iloc[0]
    assert bool(ccc["free_data_lifecycle_risk"]) is True
    assert ccc["free_data_selection_score"] < ranked.iloc[0]["free_data_selection_score"]


def test_cli_writes_research_only_outputs() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        scored = root / "scored.csv"
        signals = root / "signals.parquet"
        listing = root / "listing.parquet"
        earnings = root / "earnings.parquet"
        out = root / "out"
        pd.DataFrame([{"ticker": "AAA", "score": 1.0}, {"ticker": "BBB", "score": 2.0}]).to_csv(scored, index=False)
        pd.DataFrame([{"ticker": "BBB", "available_from": "2026-07-09", "has_forward_estimate": 1.0}]).to_parquet(signals, index=False)
        pd.DataFrame([{"symbol": "AAA", "status": "Active"}]).to_parquet(listing, index=False)
        pd.DataFrame([{"ticker": "BBB", "event_date": "2026-07-01", "estimated_eps": 1.0, "actual_eps": 1.1}]).to_parquet(earnings, index=False)
        args = parse_args()
        args.scored = str(scored)
        args.estimate_signals = str(signals)
        args.listing_status = str(listing)
        args.earnings_calendar = str(earnings)
        args.decision_date = "2026-07-10"
        args.output_dir = str(out)
        args.top_n = 1
        summary = run(args)
        assert summary["production_promotion_allowed"] is False
        assert summary["historical_backtest_acceptance_allowed"] is False
        assert (out / "ranked_universe.csv").exists()
        assert (out / "selected_candidates.csv").exists()
        assert (out / "report.md").exists()


def main() -> None:
    test_overlay_promotes_confirmed_forward_evidence_and_penalizes_delisted()
    test_cli_writes_research_only_outputs()
    print(json.dumps({"status": "PASS", "tests": 2}, sort_keys=True))


if __name__ == "__main__":
    main()
