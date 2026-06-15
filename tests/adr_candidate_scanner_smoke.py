#!/usr/bin/env python3
"""Smoke test for review-only ADR candidate scanner."""
from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.run_adr_candidate_scanner import run  # noqa: E402


def test_adr_candidate_scanner_outputs_review_artifact_without_yaml_mutation() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        yaml_path = root / "adr_universe.yaml"
        yaml_path.write_text("- ticker: BABA\n", encoding="utf-8")
        before = yaml_path.read_text(encoding="utf-8")
        candidates = root / "candidates.csv"
        pd.DataFrame(
            [
                {"ticker": "BABA", "exchange": "NYSE", "is_adr": True, "last_price": 80, "avg_volume_20d": 2_000_000, "market_cap": 100_000_000_000, "alpaca_tradable": True},
                {"ticker": "TSM", "exchange": "NYSE", "is_adr": True, "last_price": 170, "avg_volume_20d": 9_000_000, "market_cap": 700_000_000_000, "alpaca_tradable": True},
            ]
        ).to_csv(candidates, index=False)
        out = root / "out"
        summary = run(
            Namespace(
                price_cache=str(root / "cache_prices"),
                adr_universe=str(yaml_path),
                candidate_csv=str(candidates),
                output_dir=str(out),
                min_price=5.0,
                min_dollar_volume=5_000_000.0,
                min_market_cap=1_000_000_000.0,
                scan_price_cache=False,
                max_files=100,
            )
        )
        assert summary["production_mutation_allowed"] is False
        assert summary["review_add_count"] == 1
        assert summary["manual_review_required"] is True
        assert summary["proposed_add_count"] == 1
        assert yaml_path.read_text(encoding="utf-8") == before
        review = pd.read_csv(out / "adr_candidate_review.csv")
        assert set(review["candidate_status"]) == {"already_listed", "review_add"}
        assert (out / "adr_candidate_review.md").exists()
        manifest = json.loads((out / "adr_universe_update_manifest.json").read_text(encoding="utf-8"))
        assert manifest["production_mutation_allowed"] is False
        assert manifest["manual_review_required"] is True
        assert manifest["proposed_additions"][0]["ticker"] == "TSM"
        fragment = (out / "adr_universe_additions.yaml").read_text(encoding="utf-8")
        assert "ticker: TSM" in fragment
        assert "ADR_REVIEW_REQUIRED" in fragment


if __name__ == "__main__":
    test_adr_candidate_scanner_outputs_review_artifact_without_yaml_mutation()
    print("adr_candidate_scanner_smoke: PASS")
