#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_phase_g_liquidity_workflow_contains_required_gates() -> None:
    path = ROOT / ".github" / "workflows" / "phase_g_crisis_evidence_liquidity_replay.yml"
    text = path.read_text(encoding="utf-8")
    required = [
        "source_run_id",
        "run_long_crisis_learning",
        "Check overlapping research runs",
        "skipped_due_to_overlap",
        "run_long_crisis_dataset_builder.py",
        "run_long_crisis_threshold_search.py",
        "build_crisis_governed_target_books.py",
        "--cash-hard-gate",
        "best_thresholds.json",
        "--run-broker-replay",
        "Sync phase G outputs to Google Drive",
    ]
    missing = [item for item in required if item not in text]
    assert not missing, f"workflow missing required fragments: {missing}"


if __name__ == "__main__":
    test_phase_g_liquidity_workflow_contains_required_gates()
    print("phase_g_liquidity_workflow_smoke: PASS")
