#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_earnings_data_inventory import main  # noqa: E402


def test_inventory_separates_actuals_proxy_and_empty_true_feed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        sec = root / "companyfacts.zip"
        sec.write_bytes(b"not-a-real-zip-but-inventory-only")
        feed = root / "earnings_revisions.csv"
        pd.DataFrame(
            columns=[
                "ticker",
                "fiscal_period",
                "estimate_date",
                "available_from",
                "eps_estimate",
                "revenue_estimate",
                "guidance_direction",
                "source",
                "source_type",
            ]
        ).to_csv(feed, index=False)
        candidate = root / "candidate.csv"
        pd.DataFrame(
            [
                {
                    "ticker": "AAA",
                    "revenues_ttm": 100.0,
                    "eps_growth_yoy": 0.2,
                    "actual_results_score": 0.8,
                    "eps_revision_score": 0.4,
                },
                {"ticker": "BBB", "revenues_ttm": 0.0, "actual_results_score": 0.0},
            ]
        ).to_csv(candidate, index=False)
        out = root / "out"

        old_argv = sys.argv[:]
        try:
            sys.argv = [
                "run_earnings_data_inventory.py",
                "--sec-companyfacts",
                str(sec),
                "--earnings-feed",
                str(feed),
                "--pit-signals",
                str(root / "missing.parquet"),
                "--candidate-book",
                str(candidate),
                "--as-of",
                "2026-07-01",
                "--output-dir",
                str(out),
            ]
            assert main() == 0
        finally:
            sys.argv = old_argv

        payload = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        assert payload["research_only"] is True, payload
        assert payload["production_activation_allowed"] is False, payload
        assert payload["actuals_managed"] is True, payload
        assert payload["proxy_scores_present"] is True, payload
        assert payload["true_revision_guidance_ready"] is False, payload
        labels = payload["service_label_contract"]
        assert labels["actuals_confirmed"]["revision_confirmed"] is False, labels
        assert labels["analyst_revision_confirmed"]["revision_confirmed"] is True, labels
        assert labels["company_guidance_confirmed"]["guidance_confirmed"] is True, labels
        assert labels["proxy_score_diagnostic_only"]["revision_confirmed"] is False, labels
        assert payload["raw_feed"]["status"] == "blocked", payload
        assert payload["raw_feed"]["reason"] == "no_nonempty_evidence_columns", payload
        candidate_summary = payload["candidate_books"][0]
        assert "actual_results_score" in candidate_summary["proxy_score_columns_present"], candidate_summary
        assert candidate_summary["contains_true_revision_guidance_feed"] is False, candidate_summary
        assert (out / "earnings_data_layers.csv").exists()
        assert (out / "report.md").exists()


def main_smoke() -> int:
    test_inventory_separates_actuals_proxy_and_empty_true_feed()
    print("earnings_data_inventory_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main_smoke())
