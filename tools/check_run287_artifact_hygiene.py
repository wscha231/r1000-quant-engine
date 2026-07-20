#!/usr/bin/env python3
"""Reject new large or dated runtime bundles from ordinary Git changes."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
MAX_BLOB_BYTES = 2 * 1024 * 1024
DATED_COMPONENT = re.compile(r"(?:^|[_-])20\d{6}(?:[_-]|$)")
RUNTIME_ROOTS = ("cloud_results/", "outputs/")
CANONICAL_FIXTURE_PREFIX = "tests/fixtures/run287_canonical_baseline/"


def _git(*args: str, cwd: Path = ROOT) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True, encoding="utf-8"
    )
    return result.stdout


def _changed_paths(base_ref: str, root: Path) -> list[tuple[str, str]]:
    # Compare the exact base tree to HEAD.  A shallow PR checkout may not have
    # enough ancestry for merge-base (`base...HEAD`) even after fetching the
    # base object, but the two endpoint trees are sufficient for this guard.
    raw = _git("diff", "--name-status", "--find-renames", base_ref, "HEAD", cwd=root)
    rows: list[tuple[str, str]] = []
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0]
        path = parts[-1].replace("\\", "/")
        rows.append((status, path))
    return rows


def evaluate_changes(
    changes: list[tuple[str, str]], root: Path = ROOT, max_blob_bytes: int = MAX_BLOB_BYTES
) -> dict[str, Any]:
    violations: list[dict[str, Any]] = []
    added_bytes = 0
    inspected: list[dict[str, Any]] = []
    for status, rel in changes:
        if status.startswith("D"):
            continue
        path = root / rel
        size = path.stat().st_size if path.is_file() else 0
        added_bytes += size if status.startswith("A") else 0
        inspected.append({"status": status, "path": rel, "size_bytes": size})

        if rel.startswith("cloud_results/"):
            violations.append({"code": "NEW_RUNTIME_BLOB_IN_GIT", "path": rel})
        elif rel.startswith("outputs/") and (
            DATED_COMPONENT.search(rel) or "/failed" in rel.lower() or "failed_" in rel.lower()
        ):
            violations.append({"code": "NEW_DATED_OR_FAILED_OUTPUT_BUNDLE", "path": rel})

        if size > max_blob_bytes and not rel.startswith(CANONICAL_FIXTURE_PREFIX):
            violations.append(
                {
                    "code": "GIT_BLOB_TOO_LARGE",
                    "path": rel,
                    "size_bytes": size,
                    "max_blob_bytes": max_blob_bytes,
                }
            )

    return {
        "status": "PASS" if not violations else "BLOCKED_ARTIFACT_HYGIENE",
        "trusted_for_merge": not violations,
        "changed_file_count": len(inspected),
        "new_artifact_bytes": added_bytes,
        "max_blob_bytes": max_blob_bytes,
        "violations": violations,
        "files": inspected,
        "preservation_policy": "report-only; no artifact deletion or history rewrite",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-ref", default="HEAD^")
    parser.add_argument("--max-blob-bytes", type=int, default=MAX_BLOB_BYTES)
    parser.add_argument("--output")
    args = parser.parse_args()
    result = evaluate_changes(_changed_paths(args.base_ref, ROOT), ROOT, args.max_blob_bytes)
    rendered = json.dumps(result, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if result["trusted_for_merge"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
