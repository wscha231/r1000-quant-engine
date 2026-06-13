#!/usr/bin/env python3
"""Smoke checks for dataset coverage audit sidecar."""
from __future__ import annotations

import sys
import shutil
import os
import uuid
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_dataset_coverage_audit import run


def test_dataset_coverage_audit_outputs_effective_cap_and_watchlist() -> None:
    tmp_base = Path(os.environ.get("R1000_TEST_TMPDIR", ROOT.parent / "_tmp"))
    root = tmp_base / f"tmp_dataset_coverage_audit_smoke_{uuid.uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)
    try:
        latest = root / "latest"
        reports = latest / "reports"
        enriched_dir = latest / "sec_enriched_candidate_replay"
        out = root / "audit"
        reports.mkdir(parents=True)
        enriched_dir.mkdir(parents=True)

        pd.DataFrame(
            [
                {
                    "ticker": "SNDK",
                    "feature_date": "2026-05-07",
                    "rebalance_date": "2026-05-07",
                    "universe_source": "current_constituents_proxy",
                    "market_cap_live": 200_000_000_000,
                    "mktcap": 199_000_000_000,
                    "revenues_ttm": 1.0,
                    "op_income_ttm": -1.0,
                    "eps_revision_score": 0.0,
                    "score": 2.0,
                    "portfolio_sleeve_label": "unassigned",
                    "portfolio_candidate_gate_label": "rejected",
                },
                {
                    "ticker": "WDC",
                    "feature_date": "2026-05-07",
                    "rebalance_date": "2026-05-07",
                    "universe_source": "current_constituents_proxy",
                    "market_cap_live": None,
                    "mktcap": 150_000_000_000,
                    "revenues_ttm": 1.0,
                    "op_income_ttm": 1.0,
                    "eps_revision_score": 0.5,
                    "score": 5.0,
                    "portfolio_sleeve_label": "future_winner",
                    "portfolio_candidate_gate_label": "future_relaxed",
                },
            ]
        ).to_csv(latest / "scored_latest.csv", index=False)

        pd.DataFrame(
            [
                {
                    "ticker": "SNDK",
                    "rebalance_date": "2026-03-31",
                    "mktcap": 180_000_000_000,
                    "market_cap_live": None,
                    "score": 1.5,
                    "portfolio_sleeve_label": "unassigned",
                }
            ]
        ).to_csv(reports / "candidate_replay_book.csv", index=False)
        (reports / "baseline_registry.json").write_text('{"git_commit":"test"}\n', encoding="utf-8")
        pd.DataFrame(
            [
                {
                    "ticker": "SNDK",
                    "rebalance_date": "2026-03-31",
                    "source_universe": "current_constituents_proxy_static_seed",
                    "sec_13f_smart_money_score": 1.2,
                    "latest_13f_available_from": "2026-03-15",
                    "evidence_fusion_score": 0.7,
                }
            ]
        ).to_csv(enriched_dir / "candidate_replay_book_sec_enriched.csv", index=False)
        (enriched_dir / "summary.json").write_text(
            '{"status":"ok","rows_with_13f_evidence":1,"coverage_13f_ratio":1.0,"research_only":true}\n',
            encoding="utf-8",
        )

        payload = run(latest, out, ["SNDK", "WDC", "INTC"])
        assert payload["status"] == "completed"
        assert payload["latest_scored_rows"] == 2
        assert payload["sec_enriched_candidate_present"] is True
        assert payload["sec_enriched_candidate_rows"] == 1
        assert payload["sec_enriched_evidence_summary"]["rows_with_13f_evidence"] == 1
        assert (out / "dataset_coverage_audit.json").exists()
        assert (out / "dataset_coverage_audit_watchlist.csv").exists()

        coverage = pd.read_csv(out / "dataset_coverage_audit_coverage.csv")
        effective = coverage[
            (coverage["scope"] == "historical_candidate_book")
            & (coverage["column"] == "effective_market_cap_usd")
        ].iloc[0]
        assert float(effective["numeric_ratio"]) == 1.0
        evidence = coverage[
            (coverage["scope"] == "sec_enriched_candidate_book")
            & (coverage["column"] == "sec_13f_smart_money_score")
        ].iloc[0]
        assert float(evidence["nonzero_ratio"]) == 1.0

        watch = pd.read_csv(out / "dataset_coverage_audit_watchlist.csv")
        sndk = watch[watch["ticker"].eq("SNDK")].iloc[0]
        assert bool(sndk["in_latest_scored"])
        assert sndk["likely_gap"] == "selection_gate_or_rank_rejected"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main() -> int:
    test_dataset_coverage_audit_outputs_effective_cap_and_watchlist()
    print("dataset coverage audit smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
