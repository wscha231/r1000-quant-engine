#!/usr/bin/env python3
"""Smoke test for the current-selection audit sidecar."""
from __future__ import annotations

import csv
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from tools.run_selection_audit import run  # noqa: E402


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


def main() -> int:
    with TemporaryDirectory() as td:
        root = Path(td)
        latest = root / "latest"
        reports = latest / "reports"
        _write_csv(
            reports / "candidate_replay_book.csv",
            [
                {
                    "rebalance_date": "2026-04-30",
                    "ticker": "AAA",
                    "Name": "Selected Leader",
                    "score": 4.0,
                    "concentrated_score": 3.5,
                    "portfolio_monster_early_score": 0.10,
                    "portfolio_candidate_minimum_pass": True,
                    "portfolio_risk_entry_block_score": 0.10,
                    "portfolio_stale_mega_leader_score": 0.10,
                },
                {
                    "rebalance_date": "2026-04-30",
                    "ticker": "BBB",
                    "Name": "Omitted Monster",
                    "score": 3.7,
                    "concentrated_score": 3.9,
                    "portfolio_monster_early_score": 0.80,
                    "portfolio_candidate_minimum_pass": True,
                    "portfolio_risk_entry_block_score": 0.20,
                    "portfolio_stale_mega_leader_score": 0.00,
                },
                {
                    "rebalance_date": "2026-04-30",
                    "ticker": "CCC",
                    "Name": "Blocked Candidate",
                    "score": 3.6,
                    "concentrated_score": 2.0,
                    "portfolio_monster_early_score": 0.20,
                    "portfolio_candidate_minimum_pass": False,
                    "portfolio_risk_entry_block_score": 0.10,
                    "portfolio_stale_mega_leader_score": 0.00,
                    "portfolio_candidate_gate_label": "minimum_block",
                },
            ],
        )
        _write_csv(latest / "portfolio_latest.csv", [{"ticker": "AAA", "weight": 0.40}])
        _write_csv(latest / "concentrated_portfolio_latest.csv", [{"ticker": "AAA", "weight": 0.50}])
        _write_csv(
            reports / "main_monthly_weights.csv",
            [
                {"rebalance_date": "2026-02-27", "ticker": "AAA", "weight": 0.30},
                {"rebalance_date": "2026-03-31", "ticker": "AAA", "weight": 0.35},
            ],
        )
        _write_csv(
            reports / "concentrated_strategy_holdings.csv",
            [{"rebalance_date": "2026-03-31", "ticker": "AAA", "weight": 0.50}],
        )
        out_dir = root / "out"
        summary = run(latest, out_dir, top_n=10)
        assert summary["status"] == "completed", summary
        assert summary["current_main_count"] == 1, summary
        assert summary["current_concentrated_count"] == 1, summary
        buckets = summary["decision_bucket_counts"]
        assert buckets.get("selected_both", 0) == 1, summary
        assert buckets.get("omitted_monster_candidate", 0) == 1, summary
        assert (out_dir / "current_selected_audit.csv").exists()
        omitted = (out_dir / "omitted_high_potential_candidates.csv").read_text(encoding="utf-8")
        assert "BBB" in omitted
        hist = (out_dir / "historical_hold_persistence.csv").read_text(encoding="utf-8")
        assert "months_held_main" in hist
    print("selection audit smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
