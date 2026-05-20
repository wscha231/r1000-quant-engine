#!/usr/bin/env python3
"""Smoke checks for semiannual SEC 13F manager reselection candidates."""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_sec_13f_manager_reselection import run  # noqa: E402


def test_manager_reselection_is_research_only_and_uses_repo_evidence() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        universe = root / "managers.csv"
        alpha = root / "13f_manager_alpha.csv"
        holdings = root / "holdings.csv"
        out = root / "out"
        candidate_universe = root / "managers_candidate.csv"

        pd.DataFrame(
            [
                {
                    "label": "GOOD",
                    "manager_name": "Good Manager LP",
                    "cik10": "12345",
                    "active": "true",
                    "verified_cik": "true",
                    "user_priority": "10",
                },
                {
                    "label": "WEAK",
                    "manager_name": "Weak Manager LP",
                    "cik10": "54321",
                    "active": "true",
                    "verified_cik": "true",
                    "user_priority": "20",
                },
            ]
        ).to_csv(universe, index=False)
        pd.DataFrame(
            [
                {
                    "manager_cik": "0000012345",
                    "manager_name": "Good Manager LP",
                    "observations": 30,
                    "avg_excess_return": 0.05,
                    "hit_rate_excess_positive": 0.70,
                    "manager_quality_score": 0.82,
                },
                {
                    "manager_cik": "0000054321",
                    "manager_name": "Weak Manager LP",
                    "observations": 30,
                    "avg_excess_return": -0.02,
                    "hit_rate_excess_positive": 0.35,
                    "manager_quality_score": 0.20,
                },
            ]
        ).to_csv(alpha, index=False)
        pd.DataFrame(
            [
                {
                    "manager_cik": "0000012345",
                    "manager_name": "Good Manager LP",
                    "ticker_mapped": "AAPL",
                    "report_period": "2026-03-31",
                    "available_from": "2026-05-15T00:00:00+00:00",
                    "accepted_at": "2026-05-15T00:00:00+00:00",
                    "shares": 1000,
                    "market_value_usd": 200_000_000,
                },
                {
                    "manager_cik": "0000054321",
                    "manager_name": "Weak Manager LP",
                    "ticker_mapped": "MSFT",
                    "report_period": "2026-03-31",
                    "available_from": "2026-05-15T00:00:00+00:00",
                    "accepted_at": "2026-05-15T00:00:00+00:00",
                    "shares": 1000,
                    "market_value_usd": 10_000_000,
                },
            ]
        ).to_csv(holdings, index=False)

        payload = run(
            argparse.Namespace(
                manager_universe=str(universe),
                manager_alpha=str(alpha),
                holdings=str(holdings),
                output_dir=str(out),
                output_candidate_universe=str(candidate_universe),
                extra="",
                max_managers=10,
                min_observations=10,
                review_interval_days=183,
            )
        )

        assert payload["status"] == "completed"
        assert payload["production_activation_allowed"] is False
        assert payload["active_manager_universe_changed"] is False
        assert candidate_universe.exists()
        summary = json.loads((out / "manager_reselection_summary.json").read_text(encoding="utf-8"))
        assert summary["review_interval_days"] == 183
        candidates = pd.read_csv(out / "manager_reselection_candidates.csv", dtype=str)
        assert str(candidates.iloc[0]["manager_cik"]).zfill(10) == "0000012345"
        assert candidates.iloc[0]["reselection_action"] in {"candidate_include", "keep_active"}


if __name__ == "__main__":
    test_manager_reselection_is_research_only_and_uses_repo_evidence()
    print("sec_13f_manager_reselection_smoke: PASS")
