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

from tools import build_fullrun_runtime_source_manifest as runtime  # noqa: E402


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def fixture(root: Path) -> argparse.Namespace:
    git(root, "init")
    git(root, "config", "user.email", "run287@example.invalid")
    git(root, "config", "user.name", "Run287 Test")
    source = root / "cache_prices" / "AAA.csv"
    source.parent.mkdir()
    source.write_text("date,close\n2026-07-31,100\n", encoding="utf-8")
    manifest = root / "manifests" / "fullrun" / "approved.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "runtime_source_contract": {
                    "schema_version": runtime.CONTRACT_SCHEMA_VERSION,
                    "stages": {
                        "engine_pre_run": {
                            "groups": {
                                "prices": {"paths": ["cache_prices"], "min_files": 1}
                            }
                        }
                    },
                }
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    git(root, "add", "manifests/fullrun/approved.json")
    git(root, "commit", "-m", "approved manifest")
    approved_hash = hashlib.sha256(
        subprocess.check_output(
            ["git", "show", "HEAD:manifests/fullrun/approved.json"], cwd=root
        )
    ).hexdigest()
    return argparse.Namespace(
        approved_manifest="manifests/fullrun/approved.json",
        expected_manifest_sha256=approved_hash,
        expected_commit_sha=git(root, "rev-parse", "HEAD"),
        stage="engine_pre_run",
        resolved_session_date="2026-07-31",
        decision_time_utc="2026-08-01T03:00:00Z",
        skip_collector="true",
        workflow_identity="fixture/1/1",
        output="outputs/fullrun_runtime_source_manifest.json",
    )


def test_mutable_runtime_inputs_change_composite_identity_and_missing_blocks() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        original = runtime.REPO_ROOT
        try:
            runtime.REPO_ROOT = root
            args = fixture(root)
            first = runtime.build(args)
            assert first["ready"] is True
            assert first["groups"]["prices"]["file_count"] == 1

            price = root / "cache_prices" / "AAA.csv"
            price.write_text("date,close\n2026-07-31,101\n", encoding="utf-8")
            second = runtime.build(args)
            assert second["ready"] is True
            assert (
                first["runtime_source_identity_sha256"]
                != second["runtime_source_identity_sha256"]
            )

            price.unlink()
            blocked = runtime.build(args)
            assert blocked["ready"] is False
            assert any(
                failure.startswith("runtime_source_group_below_minimum:prices")
                for failure in blocked["contract_failures"]
            )
        finally:
            runtime.REPO_ROOT = original


if __name__ == "__main__":
    test_mutable_runtime_inputs_change_composite_identity_and_missing_blocks()
    print("fullrun_runtime_source_manifest_smoke: PASS")
