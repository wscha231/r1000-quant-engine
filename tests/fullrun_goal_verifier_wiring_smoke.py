#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_sidecar_invokes_goal_verifier_after_account_evaluation() -> None:
    script = (ROOT / "tools" / "run_full_rebuild_sidecars.py").read_text(encoding="utf-8")
    account = "python tools/run_account_evaluation.py --latest-run outputs --output-dir outputs/account_evaluation"
    verifier = "python tools/verify_alphaops_goal_artifact.py --latest-run outputs --target-dir outputs/alphaops_vnext --output-dir outputs/goal_verifier"
    assert account in script
    assert verifier in script
    assert script.index(account) < script.index(verifier)
    assert "outputs/full_rebuild_logs/goal_verifier.log" in script


def test_fullrun_artifact_uploads_goal_verifier_outputs() -> None:
    workflow = (ROOT / ".github" / "workflows" / "full_rebuild_manual.yml").read_text(encoding="utf-8")
    assert "outputs/goal_verifier/" in workflow
    assert "outputs/full_rebuild_logs/goal_verifier.log" in workflow


if __name__ == "__main__":
    test_sidecar_invokes_goal_verifier_after_account_evaluation()
    test_fullrun_artifact_uploads_goal_verifier_outputs()
    print("fullrun_goal_verifier_wiring_smoke: PASS")
