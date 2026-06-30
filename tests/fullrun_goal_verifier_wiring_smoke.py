#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_sidecar_invokes_goal_verifier_after_account_evaluation() -> None:
    script = (ROOT / "tools" / "run_full_rebuild_sidecars.py").read_text(encoding="utf-8")
    account = "python tools/run_account_evaluation.py --latest-run outputs --output-dir outputs/account_evaluation"
    verifier = "python tools/verify_alphaops_goal_artifact.py --latest-run outputs --target-dir outputs/alphaops_vnext --output-dir outputs/goal_verifier"
    cadence = "python tools/run_alphaops_operating_cadence_status.py --latest-run outputs --output-dir outputs/operating_cadence_status"
    rs_screen = "python tools/run_rs_2w_entry_timing_screen.py --target-book outputs/alphaops_vnext/official_concentrated_target_book.csv --price-cache cache_prices --output-dir outputs/rs_2w_entry_timing_screen"
    assert account in script
    assert verifier in script
    assert cadence in script
    assert rs_screen in script
    assert script.index(account) < script.index(verifier)
    assert script.index(verifier) < script.index(cadence)
    assert script.index(cadence) < script.index(rs_screen)
    assert "outputs/full_rebuild_logs/goal_verifier.log" in script
    assert "outputs/full_rebuild_logs/operating_cadence_status.log" in script
    assert "outputs/full_rebuild_logs/rs_2w_entry_timing_screen.log" in script


def test_fullrun_artifact_uploads_goal_verifier_outputs() -> None:
    workflow = (ROOT / ".github" / "workflows" / "full_rebuild_manual.yml").read_text(encoding="utf-8")
    assert "outputs/goal_verifier/" in workflow
    assert "outputs/operating_cadence_status/" in workflow
    assert "outputs/rs_2w_entry_timing_screen/" in workflow
    assert "outputs/full_rebuild_logs/goal_verifier.log" in workflow
    assert "outputs/full_rebuild_logs/operating_cadence_status.log" in workflow
    assert "outputs/full_rebuild_logs/rs_2w_entry_timing_screen.log" in workflow


if __name__ == "__main__":
    test_sidecar_invokes_goal_verifier_after_account_evaluation()
    test_fullrun_artifact_uploads_goal_verifier_outputs()
    print("fullrun_goal_verifier_wiring_smoke: PASS")
