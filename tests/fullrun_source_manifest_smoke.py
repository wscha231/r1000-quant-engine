#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import verify_fullrun_source_manifest as verifier


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def git_blob_sha256(root: Path, relative: str) -> str:
    return hashlib.sha256(
        subprocess.check_output(["git", "show", f"HEAD:{relative}"], cwd=root)
    ).hexdigest()


def fixture(root: Path) -> tuple[argparse.Namespace, Path]:
    git(root, "init")
    git(root, "config", "user.email", "run287@example.invalid")
    git(root, "config", "user.name", "Run287 Test")
    (root / ".gitattributes").write_bytes(b"requirements_github.txt text\n")
    source = root / "requirements_github.txt"
    source.write_text("pandas==2.2.0\n", encoding="utf-8")
    manifest = root / "manifests" / "fullrun" / "approved.json"
    manifest.parent.mkdir(parents=True)
    scope = {
        "universe_mode": "global_alpha_universe",
        "backtest_years": 7,
        "pit_universe_label_clean": False,
        "skip_collector": True,
        "fast_mode": True,
        "leader_rescue_mode": "latest_only",
        "sidecar_profile": "operating_minimal",
        "artifact_profile": "minimal",
        "gdrive_sync_mode": "minimal",
        "portfolio_policy": "integrated_shadow",
        "approved_target_policy_path": "outputs/promotion_review/approved_target_policy.json",
        "decision_time_utc": "2026-08-01T20:00:00+00:00",
        "experiment_env": {},
    }
    manifest.write_text(
        json.dumps(
            {
                "schema_version": verifier.SCHEMA_VERSION,
                "status": verifier.READY_STATUS,
                "approval_scope": scope,
                "resolved_session_date": "2026-07-31",
                "tracked_inputs": {
                    "requirements": {
                        "path": "requirements_github.txt",
                        "sha256": hashlib.sha256(b"pandas==2.2.0\n").hexdigest(),
                    }
                },
                "research_only": True,
                "production_activation_allowed": False,
                "live_trading_enabled": False,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    git(root, "add", ".")
    git(root, "commit", "-m", "fixture")
    args = argparse.Namespace(
        manifest="manifests/fullrun/approved.json",
        expected_sha256=git_blob_sha256(root, "manifests/fullrun/approved.json"),
        expected_commit_sha=git(root, "rev-parse", "HEAD"),
        universe_mode="global_alpha_universe",
        backtest_years="7",
        pit_universe_label_clean="false",
        skip_collector="true",
        fast_mode="true",
        leader_rescue_mode="latest_only",
        sidecar_profile="operating_minimal",
        artifact_profile="minimal",
        gdrive_sync_mode="minimal",
        portfolio_policy="integrated_shadow",
        approved_target_policy_path="outputs/promotion_review/approved_target_policy.json",
        decision_time_utc="2026-08-01T20:00:00Z",
        experiment_env_json="",
        resolved_session_date="2026-07-31",
        output="outputs/fullrun_source_manifest_verification.json",
    )
    return args, source


def test_manifest_binds_scope_commit_session_and_tracked_inputs() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        original_root = verifier.REPO_ROOT
        try:
            verifier.REPO_ROOT = root
            args, source = fixture(root)
            ready = verifier.verify(args)
            assert ready["ready"] is True
            assert ready["contract_failures"] == []
            assert ready["manifest"]["hash_basis"] == "git_blob_bytes"

            source.write_bytes(b"pandas==2.2.0\r\n")
            eol_translated = verifier.verify(args)
            assert eol_translated["ready"] is True
            assert (
                eol_translated["tracked_inputs"]["requirements"]["git_blob_sha256"]
                != eol_translated["tracked_inputs"]["requirements"]["worktree_sha256"]
            )

            source.write_text("pandas==9.9.9\n", encoding="utf-8")
            changed = verifier.verify(args)
            assert changed["ready"] is False
            assert "tracked_input_worktree_modified:requirements" in changed["contract_failures"]

            git(root, "checkout", "--", "requirements_github.txt")
            args.resolved_session_date = "2026-07-30"
            wrong_session = verifier.verify(args)
            assert wrong_session["ready"] is False
            assert "resolved_session_date_mismatch" in wrong_session["contract_failures"]
        finally:
            verifier.REPO_ROOT = original_root


if __name__ == "__main__":
    test_manifest_binds_scope_commit_session_and_tracked_inputs()
    print("fullrun_source_manifest_smoke: PASS")
