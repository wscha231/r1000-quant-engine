#!/usr/bin/env python3
"""Smoke test for the fast orchestrator replay adapter."""
from __future__ import annotations

import sys
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.run_orchestrator_replay import run  # noqa: E402


def test_orchestrator_replay_records_missing_concentrated_monthly() -> None:
    with TemporaryDirectory() as tmp:
        result = run(
            Namespace(
                latest_run=str(REPO_ROOT / "tests" / "fixtures" / "run287_canonical_baseline"),
                output_dir=str(Path(tmp) / "orchestrator_replay"),
                concentrated_monthly="",
                target_n=5,
                weighting_mode="score_power",
                interval=1,
            )
        )
        assert result["status"] in {"completed", "blocked_missing_concentrated_monthly"}
        assert result["production_activation_allowed"] is False
        assert "unified_balanced" in result["metrics"]
        if result["status"] == "blocked_missing_concentrated_monthly":
            assert result["valid_for_promotion"] is False
            assert result["data_mode"] == "proxy_top_raw_score_within_main_holdings"


if __name__ == "__main__":
    test_orchestrator_replay_records_missing_concentrated_monthly()
    print("orchestrator_replay_smoke: ok")
