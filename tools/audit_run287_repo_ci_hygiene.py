#!/usr/bin/env python3
"""Measure Run287 repository and CI artifact hygiene without mutation."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from verify_run287_artifact_manifest import CANONICAL_FIXTURE, verify_manifest


ROOT = Path(__file__).resolve().parent.parent
DATED_REF = re.compile(r"(?:cloud_results|outputs)/[^\"'\s]*(?:20\d{6}|failed_runs)")
CORE_BASELINE_TESTS = (
    "auto_learning_v2_smoke.py",
    "orchestrator_replay_smoke.py",
    "portfolio_goal_search_smoke.py",
    "portfolio_system_guard_smoke.py",
)


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True, encoding="utf-8"
    ).stdout


def _tree_metrics() -> tuple[int, int, list[dict[str, Any]]]:
    rows = []
    total = 0
    raw = _git("ls-tree", "-r", "-l", "HEAD")
    for line in raw.splitlines():
        meta, _, path = line.partition("\t")
        bits = meta.split()
        if len(bits) < 4 or not bits[3].isdigit():
            continue
        size = int(bits[3])
        total += size
        rows.append({"path": path, "size_bytes": size, "sha": bits[2]})
    rows.sort(key=lambda item: item["size_bytes"], reverse=True)
    return total, len(rows), rows[:20]


def _top_level(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, int]] = {}
    for row in rows:
        top = row["path"].split("/", 1)[0]
        item = grouped.setdefault(top, {"bytes": 0, "files": 0})
        item["bytes"] += int(row["size_bytes"])
        item["files"] += 1
    return [
        {"path": key, **value}
        for key, value in sorted(grouped.items(), key=lambda kv: kv[1]["bytes"], reverse=True)[:20]
    ]


def _all_tree_rows() -> list[dict[str, Any]]:
    rows = []
    for line in _git("ls-tree", "-r", "-l", "HEAD").splitlines():
        meta, _, path = line.partition("\t")
        bits = meta.split()
        if len(bits) >= 4 and bits[3].isdigit():
            rows.append({"path": path, "size_bytes": int(bits[3])})
    return rows


def _count_hidden_dated_test_dependencies() -> tuple[int, list[str]]:
    """Count executable core-baseline dependencies, not literal contract assertions."""
    matches: set[str] = set()
    for name in CORE_BASELINE_TESTS:
        path = ROOT / "tests" / name
        text = path.read_text(encoding="utf-8", errors="replace")
        for hit in DATED_REF.findall(text):
            matches.add(f"{path.relative_to(ROOT).as_posix()}:{hit}")
    return len(matches), sorted(matches)


def build_audit(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    total, count, largest = _tree_metrics()
    all_rows = _all_tree_rows()
    fixture_check = verify_manifest(CANONICAL_FIXTURE)
    hidden_count, hidden = _count_hidden_dated_test_dependencies()
    fixture_bytes = sum(p.stat().st_size for p in CANONICAL_FIXTURE.rglob("*") if p.is_file())
    return {
        "schema_version": "run287-repo-ci-hygiene-audit-v1",
        "status": "MEASURED",
        "git_tree": {
            "bytes": total,
            "files": count,
            "largest_20_blobs": largest,
            "largest_20_top_level_paths": _top_level(all_rows),
        },
        "canonical_fixture": {
            "path": CANONICAL_FIXTURE.relative_to(ROOT).as_posix(),
            "bytes_including_manifest": fixture_bytes,
            "verification": fixture_check,
        },
        "ci_measurements_seconds": {
            "checkout_before": args.checkout_before,
            "tier1_before": args.tier1_before,
            "external_restore_and_checksum": fixture_check["duration_seconds"],
        },
        "duplicate_same_sha_validation_before": args.duplicate_same_sha_before,
        "hidden_dated_path_dependency_count": hidden_count,
        "hidden_dated_path_dependencies": hidden,
        "new_artifact_bytes_after_cleanup": args.new_artifact_bytes,
        "duration_seconds": round(time.perf_counter() - started, 6),
        "safety": "read-only audit; historical artifacts preserved",
    }


def _markdown(payload: dict[str, Any]) -> str:
    tree = payload["git_tree"]
    fixture = payload["canonical_fixture"]
    return "\n".join(
        [
            "# Run287 P8 repository and CI hygiene audit",
            "",
            "Status label: `ACTIVE_REVIEW_EVIDENCE`",
            "",
            f"- Git tree: {tree['bytes']:,} bytes / {tree['files']:,} files",
            f"- Canonical CI fixture: {fixture['bytes_including_manifest']:,} bytes",
            f"- Fixture verification: `{fixture['verification']['status']}`",
            f"- Hidden dated test dependencies: {payload['hidden_dated_path_dependency_count']}",
            f"- New artifact bytes after cleanup: {payload['new_artifact_bytes_after_cleanup']:,}",
            f"- Duplicate same-SHA validation jobs before: {payload['duplicate_same_sha_validation_before']}",
            "- No historical evidence was deleted or rewritten.",
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="outputs/run287_repo_ci_hygiene")
    parser.add_argument("--checkout-before", type=float, default=20.5)
    parser.add_argument("--tier1-before", type=float, default=239.5)
    parser.add_argument("--duplicate-same-sha-before", type=int, default=2)
    parser.add_argument("--new-artifact-bytes", type=int, default=0)
    args = parser.parse_args()
    payload = build_audit(args)
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "repo_ci_hygiene_audit.json"
    md_path = out / "repo_ci_hygiene_audit.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(_markdown(payload), encoding="utf-8")
    print(json.dumps({"status": payload["status"], "json": str(json_path), "markdown": str(md_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
