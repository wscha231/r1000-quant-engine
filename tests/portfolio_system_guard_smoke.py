#!/usr/bin/env python3
"""Smoke tests for the portfolio system target guard."""
from __future__ import annotations

import sys
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.run_portfolio_system_guard import run  # noqa: E402


def test_portfolio_system_guard_reports_target_gaps() -> None:
    with TemporaryDirectory() as tmp:
        out_dir = Path(tmp) / "guard"
        result = run(
            Namespace(
                latest_run=str(REPO_ROOT / "cloud_results" / "full_rebuild" / "latest_global_alpha_universe"),
                output_dir=str(out_dir),
                main_cagr_target=0.25,
                main_max_dd_target=-0.20,
                concentrated_cagr_target=0.40,
                concentrated_max_dd_target=-0.22,
                strict_targets=False,
            )
        )
        assert result["overall_status"] == "blocked"
        assert result["targets_pass"] is False
        assert len(result["portfolio_status"]) == 2
        main = result["portfolio_status"][0]
        concentrated = result["portfolio_status"][1]
        assert main["portfolio"] == "main"
        assert concentrated["portfolio"] == "concentrated"
        assert main["cagr_gap_pp"] > 0
        assert concentrated["cagr_gap_pp"] > 0
        main_metric_check = next(row for row in result["error_checks"] if row["check"] == "main_metrics_available")
        assert main_metric_check["severity"] in {"ok", "warn"}
        assert (out_dir / "system_guard_report.md").exists()
        assert (out_dir / "target_gap.json").exists()


if __name__ == "__main__":
    test_portfolio_system_guard_reports_target_gaps()
    print("portfolio_system_guard_smoke: ok")
