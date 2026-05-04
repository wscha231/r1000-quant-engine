#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        latest = tmp / "latest_run"
        out = tmp / "winner_lifecycle"
        scored_cols = [
            "ticker",
            "Name",
            "sector",
            "score",
            "portfolio_sleeve_label",
            "portfolio_future_winner_engine_score",
            "portfolio_core_compounder_engine_score",
            "portfolio_early_scout_engine_score",
            "mom_1m",
            "mom_3m",
            "mom_6m",
            "mom_12m",
            "relative_strength_composite",
            "entry_quality_score",
            "selection_confirmation_score",
            "price_above_ma50",
            "price_above_ma200",
        ]
        write_csv(
            latest / "scored_latest.csv",
            [
                {
                    "ticker": "NVDA",
                    "Name": "NVIDIA CORP",
                    "sector": "Information Technology",
                    "score": 5.2,
                    "portfolio_sleeve_label": "core_compounder",
                    "portfolio_future_winner_engine_score": 0.5,
                    "portfolio_core_compounder_engine_score": 0.95,
                    "portfolio_early_scout_engine_score": 0.3,
                    "mom_1m": 0.02,
                    "mom_3m": 0.03,
                    "mom_6m": -0.04,
                    "mom_12m": 0.80,
                    "relative_strength_composite": 0.15,
                    "entry_quality_score": 0.88,
                    "selection_confirmation_score": 1.0,
                    "price_above_ma50": 1,
                    "price_above_ma200": 1,
                },
                {
                    "ticker": "SNDK",
                    "Name": "SANDISK CORP",
                    "sector": "Information Technology",
                    "score": 1.3,
                    "portfolio_sleeve_label": "unassigned",
                    "portfolio_future_winner_engine_score": 0.82,
                    "portfolio_core_compounder_engine_score": -0.2,
                    "portfolio_early_scout_engine_score": 0.77,
                    "mom_1m": 0.70,
                    "mom_3m": 1.05,
                    "mom_6m": 4.80,
                    "mom_12m": 10.0,
                    "relative_strength_composite": 4.5,
                    "entry_quality_score": 0.0,
                    "selection_confirmation_score": 1.0,
                    "price_above_ma50": 1,
                    "price_above_ma200": 1,
                },
                {
                    "ticker": "CALM",
                    "Name": "CALM TEST",
                    "sector": "Consumer Staples",
                    "score": 2.0,
                    "portfolio_sleeve_label": "unassigned",
                    "portfolio_future_winner_engine_score": 0.1,
                    "portfolio_core_compounder_engine_score": 0.2,
                    "portfolio_early_scout_engine_score": 0.1,
                    "mom_1m": 0.01,
                    "mom_3m": 0.02,
                    "mom_6m": 0.03,
                    "mom_12m": 0.04,
                    "relative_strength_composite": 0.1,
                    "entry_quality_score": 0.5,
                    "selection_confirmation_score": 0.2,
                    "price_above_ma50": 1,
                    "price_above_ma200": 1,
                },
            ],
            scored_cols,
        )
        write_csv(
            latest / "portfolio_latest.csv",
            [
                {
                    "ticker": "NVDA",
                    "Name": "NVIDIA CORP",
                    "sector": "Information Technology",
                    "weight": 0.10,
                }
            ],
            ["ticker", "Name", "sector", "weight"],
        )
        write_csv(latest / "concentrated_portfolio_latest.csv", [], ["ticker", "Name", "sector", "weight"])

        result = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "tools" / "run_winner_lifecycle_reports.py"),
                "--latest-run",
                str(latest),
                "--output-dir",
                str(out),
                "--top-n",
                "10",
            ],
            cwd=REPO_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if result.returncode != 0:
            raise AssertionError(result.stdout)
        summary = json.loads((out / "winner_lifecycle_summary.json").read_text(encoding="utf-8"))
        assert summary["missed_winners"][0]["ticker"] == "SNDK"
        assert summary["stale_winners"][0]["ticker"] == "NVDA"
        assert summary["leadership_rotations"][0]["held_ticker"] == "NVDA"
        assert summary["leadership_rotations"][0]["challenger_ticker"] == "SNDK"
        assert (out / "system_policy_candidates.yaml").exists()
        assert "production_activation_allowed: false" in (out / "system_policy_candidates.yaml").read_text(encoding="utf-8")
    print("winner lifecycle smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
