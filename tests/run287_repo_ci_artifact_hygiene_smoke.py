#!/usr/bin/env python3
"""Smoke coverage for P8 manifest and Git artifact hygiene contracts."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from check_run287_artifact_hygiene import evaluate_changes  # noqa: E402
from verify_run287_artifact_manifest import (  # noqa: E402
    CANONICAL_FIXTURE,
    resolve_baseline,
    verify_manifest,
)


def _write_manifest(root: Path, name: str, payload: bytes) -> None:
    (root / name).write_bytes(payload)
    manifest = {
        "schema_version": "run287-artifact-manifest-v1",
        "source_commit": "fixture",
        "source_run_id": "fixture",
        "generated_at": "2026-07-20T00:00:00Z",
        "retention_policy": "test",
        "restore_command": "none",
        "privacy_safety": "synthetic",
        "files": [
            {"path": name, "size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        ],
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_canonical_fixture_is_exact_and_trusted() -> None:
    result = verify_manifest(CANONICAL_FIXTURE)
    assert result["status"] == "TRUSTED", result
    assert result["checked_files"] >= 20
    assert resolve_baseline(None)["status"] == "READY"


def test_tamper_and_undeclared_files_fail_closed() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_manifest(root, "payload.json", b"{}")
        assert verify_manifest(root)["trusted"] is True
        (root / "payload.json").write_bytes(b'{"changed":true}')
        assert verify_manifest(root)["status"] == "CHECKSUM_VERIFICATION_FAILED"
        (root / "payload.json").write_bytes(b"{}")
        (root / "extra.txt").write_text("not declared", encoding="utf-8")
        result = verify_manifest(root)
        assert any(item["code"] == "UNDECLARED_FILE" for item in result["errors"])


def test_custom_baseline_without_manifest_is_explicitly_unsupported() -> None:
    with TemporaryDirectory() as tmp:
        result = resolve_baseline(tmp)
        assert result["status"] == "UNSUPPORTED_BASELINE_PATH", result
        assert result["trusted"] is False


def test_artifact_hygiene_blocks_runtime_and_large_blobs() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "cloud_results").mkdir()
        (root / "cloud_results" / "run.json").write_text("{}", encoding="utf-8")
        (root / "large.bin").write_bytes(b"x" * 101)
        result = evaluate_changes(
            [("A", "cloud_results/run.json"), ("A", "large.bin")], root=root, max_blob_bytes=100
        )
        codes = {row["code"] for row in result["violations"]}
        assert "NEW_RUNTIME_BLOB_IN_GIT" in codes
        assert "GIT_BLOB_TOO_LARGE" in codes
        assert result["trusted_for_merge"] is False


def test_small_code_change_passes_without_mutation() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "tools").mkdir()
        (root / "tools" / "small.py").write_text("pass\n", encoding="utf-8")
        result = evaluate_changes([("A", "tools/small.py")], root=root)
        assert result["status"] == "PASS", result
        assert result["new_artifact_bytes"] == (root / "tools" / "small.py").stat().st_size


if __name__ == "__main__":
    tests = [value for key, value in sorted(globals().items()) if key.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"run287_repo_ci_artifact_hygiene_smoke: {len(tests)} passed")
