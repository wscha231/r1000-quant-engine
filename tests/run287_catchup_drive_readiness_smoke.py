#!/usr/bin/env python3
"""Behavioral and workflow checks for durable Run287 catch-up Drive gating."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "check_run287_catchup_drive_readiness.py"
WORKFLOW = (
    ROOT / ".github" / "workflows" / "daily_operating_selection_refresh.yml"
)

sys.path.insert(0, str(ROOT))
from tools.check_run287_catchup_drive_readiness import (  # noqa: E402
    ALLOWED_CANONICAL_STATES,
    evaluate_readiness,
)


def evaluate(
    *,
    phase: str,
    catchup: bool,
    auth: bool = False,
    ready: bool = False,
    rclone: bool = False,
    state: str = "",
) -> dict[str, object]:
    return evaluate_readiness(
        phase=phase,
        catchup_mode=catchup,
        auth_configured=auth,
        gdrive_ready=ready,
        rclone_available=rclone,
        canonical_state=state,
    )


def test_behavior_matrix() -> None:
    normal = evaluate(phase="authentication", catchup=False)
    assert normal["allowed"] is True
    assert normal["status"] == "READY_NON_CATCHUP_CACHE_ONLY"
    assert normal["github_env_updates"] == {"GDRIVE_READY": "no"}

    blocked_auth = evaluate(phase="authentication", catchup=True)
    assert blocked_auth["allowed"] is False
    assert blocked_auth["status"] == "BLOCKED_DURABLE_DRIVE_AUTH"
    assert evaluate(
        phase="authentication", catchup=True, auth=True
    )["allowed"] is True

    assert evaluate(phase="restored", catchup=False)["allowed"] is True
    assert evaluate(
        phase="restored", catchup=True, ready=False, rclone=True
    )["status"] == "BLOCKED_DURABLE_DRIVE_RESTORE"
    assert evaluate(
        phase="restored", catchup=True, ready=True, rclone=False
    )["status"] == "BLOCKED_DURABLE_DRIVE_RESTORE"
    for state in sorted(ALLOWED_CANONICAL_STATES):
        passed = evaluate(
            phase="restored",
            catchup=True,
            ready=True,
            rclone=True,
            state=state,
        )
        assert passed["allowed"] is True, state
        assert passed["status"] == "READY_DURABLE_DRIVE"
    for state in ("", "UNKNOWN", "UNCLASSIFIED", "PROVEN_PRESENT_TYPO"):
        blocked = evaluate(
            phase="restored",
            catchup=True,
            ready=True,
            rclone=True,
            state=state,
        )
        assert blocked["allowed"] is False, state
        assert blocked["status"] == "BLOCKED_DURABLE_DRIVE_STATE"


def test_cli_preserves_normal_fallback_and_blocks_catchup() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        github_env = Path(tmp) / "github_env.txt"
        base_env = os.environ.copy()
        for key in (
            "GOOGLE_SERVICE_ACCOUNT_KEY",
            "RCLONE_CONFIG_GDRIVE",
            "GDRIVE_READY",
            "PAPER_CANONICAL_REMOTE_STATE",
        ):
            base_env.pop(key, None)
        base_env["GITHUB_ENV"] = str(github_env)

        normal_env = dict(base_env, PAPER_CATCHUP_MODE="no")
        normal = subprocess.run(
            [sys.executable, str(TOOL), "--phase", "authentication"],
            cwd=ROOT,
            env=normal_env,
            check=False,
            capture_output=True,
            text=True,
        )
        assert normal.returncode == 0, normal.stderr
        assert github_env.read_text(encoding="utf-8") == "GDRIVE_READY=no\n"

        github_env.write_text("", encoding="utf-8")
        catchup_env = dict(base_env, PAPER_CATCHUP_MODE="yes")
        blocked = subprocess.run(
            [sys.executable, str(TOOL), "--phase", "authentication"],
            cwd=ROOT,
            env=catchup_env,
            check=False,
            capture_output=True,
            text=True,
        )
        assert blocked.returncode == 2
        assert "durable Drive authentication is required" in blocked.stdout
        assert github_env.read_text(encoding="utf-8") == ""


def test_workflow_scope_and_order() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["refresh"]["steps"]
    names = [str(step.get("name")) for step in steps]
    by_name = {str(step.get("name")): step for step in steps}

    configure = by_name["Configure rclone"]
    configure_env = configure["env"]
    assert configure_env["GOOGLE_SERVICE_ACCOUNT_KEY"] == (
        "${{ secrets.RUN287_DURABLE_GOOGLE_SERVICE_ACCOUNT_KEY }}"
    )
    assert configure_env["RCLONE_CONFIG_GDRIVE"] == (
        "${{ secrets.RUN287_DURABLE_RCLONE_CONFIG_GDRIVE }}"
    )
    assert "${{ secrets.GOOGLE_SERVICE_ACCOUNT_KEY }}" not in str(configure_env)
    assert "${{ secrets.RCLONE_CONFIG_GDRIVE }}" not in str(configure_env)
    configure_run = configure["run"]
    assert (
        "python tools/check_run287_catchup_drive_readiness.py"
        in configure_run
    )
    assert "--phase authentication" in configure_run
    assert configure_run.index(
        "python tools/check_run287_catchup_drive_readiness.py"
    ) < configure_run.index('if [ -z "${RCLONE_CONFIG_GDRIVE:-}" ]')
    assert "continue-on-error" not in configure

    guard_name = "Enforce durable Drive for chronological catch-up"
    guard = by_name[guard_name]
    assert str(guard["if"]) == (
        "steps.market.outputs.ready == 'yes' && "
        "steps.market.outputs.catchup_mode == 'yes'"
    )
    assert "continue-on-error" not in guard
    assert (
        "python tools/check_run287_catchup_drive_readiness.py --phase restored"
        in guard["run"]
    )
    assert names.index(guard_name) < names.index(
        "Run transactional paper ledger and same-close selector"
    )


def main() -> int:
    test_behavior_matrix()
    test_cli_preserves_normal_fallback_and_blocks_catchup()
    test_workflow_scope_and_order()
    print("run287_catchup_drive_readiness_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
