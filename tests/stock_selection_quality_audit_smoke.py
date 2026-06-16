#!/usr/bin/env python3
"""Smoke tests for Alpha Plane stock selection quality audit."""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from tools.run_stock_selection_quality_audit import run  # noqa: E402


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    with TemporaryDirectory() as td:
        root = Path(td)
        latest = root / "latest"
        reports = latest / "reports"
        candidate = reports / "candidate_replay_book.csv"
        target = reports / "operating_concentrated_target_book.csv"
        _write_csv(
            candidate,
            [
                {
                    "rebalance_date": "2026-05-31",
                    "ticker": "AAA",
                    "sector": "Software",
                    "theme": "AI software",
                    "relative_strength_composite": 0.95,
                    "oneil_leadership_score": 0.90,
                    "rs_spy_3m": 0.20,
                    "rs_qqq_3m": 0.12,
                    "rs_theme_3m": 0.08,
                    "evidence_fusion_score": 0.20,
                    "forward_63d_excess": -0.05,
                    "portfolio_candidate_minimum_pass": True,
                },
                {
                    "rebalance_date": "2026-05-31",
                    "ticker": "NVDA",
                    "sector": "Semiconductors",
                    "theme": "AI semiconductors",
                    "relative_strength_composite": 0.98,
                    "oneil_leadership_score": 0.97,
                    "rs_spy_3m": 0.30,
                    "rs_qqq_3m": 0.25,
                    "rs_theme_3m": 0.16,
                    "evidence_fusion_score": 0.10,
                    "forward_63d_excess": 0.22,
                    "portfolio_candidate_minimum_pass": True,
                },
                {
                    "rebalance_date": "2026-05-31",
                    "ticker": "EVID",
                    "sector": "Industrial",
                    "theme": "Other",
                    "relative_strength_composite": 0.05,
                    "oneil_leadership_score": 0.05,
                    "smart_money_shadow_score": 1.00,
                    "sec_form4_score": 1.00,
                    "etf_holdings_score": 1.00,
                    "forward_126d_excess": 0.90,
                    "portfolio_candidate_minimum_pass": True,
                },
                {
                    "rebalance_date": "2026-05-31",
                    "ticker": "EMRG",
                    "sector": "Healthcare",
                    "theme": "Emerging biotech",
                    "portfolio_sleeve_label": "Emerging",
                    "relative_strength_composite": 0.88,
                    "oneil_leadership_score": 0.86,
                    "fcf_margin": -0.40,
                    "portfolio_candidate_minimum_pass": True,
                },
            ],
        )
        _write_csv(
            target,
            [
                {"rebalance_date": "2026-05-31", "ticker": "AAA", "weight": 0.40},
                {"rebalance_date": "2026-05-31", "ticker": "CASH", "weight": 0.60},
            ],
        )
        before_candidate = _sha(candidate)
        before_target = _sha(target)
        out_dir = root / "out"
        summary = run(
            latest,
            out_dir,
            leaders_per_date=3,
            source_run_id="27516185696",
            source_commit_sha="abc123",
            source_branch="codex/alpha-plane-measurement-audits-20260615",
            source_artifact_name="user-operating-minimal-test",
        )
        assert summary["status"] == "completed", summary
        assert summary["production_mutation_allowed"] is False, summary
        assert summary["source_run_id"] == "27516185696", summary
        assert summary["source_of_truth_level"] == "GITHUB_ARTIFACT", summary
        assert summary["candidate_source_mode"] == "historical_candidate_replay", summary
        assert summary["historical_valid"] is True, summary
        assert summary["used_forward_return_in_ranking"] is False, summary
        assert _sha(candidate) == before_candidate, "candidate book was mutated"
        assert _sha(target) == before_target, "target book was mutated"

        selected = pd.read_csv(out_dir / "selected_names_audit.csv")
        missed = pd.read_csv(out_dir / "missed_leaders_audit.csv")
        available = pd.read_csv(out_dir / "selected_vs_available_leaders.csv")
        assert "source_commit_sha" in selected.columns
        assert "production_mutation_allowed" in selected.columns
        assert "AAA" in set(selected["ticker"])
        assert "used_forward_return_in_ranking" in selected.columns
        assert not selected["used_forward_return_in_ranking"].astype(bool).any()
        assert "NVDA" in set(missed["ticker"]), missed
        assert "EVID" not in set(missed["ticker"]), "evidence-only low-RS name became ex-ante missed leader"
        emrg = available[available["ticker"].eq("EMRG")]
        assert not emrg.empty, "negative-FCF Emerging candidate should remain auditable"
        assert "forward_63d_excess" in missed.columns

        capture = pd.read_csv(out_dir / "semiconductor_leader_capture.csv")
        assert not capture.empty
        payload = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
        assert payload["metric_mode"] == "broker_ledger_next_close"

        rank_out = root / "rank_out"
        run(latest, rank_out, leaders_per_date=4)
        rank_available = pd.read_csv(rank_out / "selected_vs_available_leaders.csv")
        assert int(rank_available.loc[rank_available["ticker"].eq("EVID"), "leader_rank_ex_ante"].iloc[0]) > int(
            rank_available.loc[rank_available["ticker"].eq("NVDA"), "leader_rank_ex_ante"].iloc[0]
        ), "forward return must not improve ex-ante leader rank"

        latest_only = root / "latest_only"
        latest_reports = latest_only / "reports"
        _write_csv(latest_only / "scored_latest.csv", list(pd.read_csv(candidate).to_dict("records")))
        _write_csv(
            latest_reports / "operating_concentrated_target_book.csv",
            [{"rebalance_date": "2026-05-31", "ticker": "AAA", "weight": 0.40}],
        )
        latest_out = root / "latest_out"
        latest_summary = run(latest_only, latest_out, leaders_per_date=3)
        assert latest_summary["status"] == "REVIEW_ONLY_LATEST_SOURCE", latest_summary
        assert latest_summary["candidate_source_mode"] == "latest_only", latest_summary
        assert latest_summary["historical_valid"] is False, latest_summary
        assert latest_summary["historical_audit_enabled"] is False, latest_summary
        latest_missed = pd.read_csv(latest_out / "missed_leaders_audit.csv")
        assert latest_missed.empty, latest_missed
    print("stock selection quality audit smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
