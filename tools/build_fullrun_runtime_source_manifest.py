#!/usr/bin/env python3
"""Bind mutable Run287 fullrun inputs to the approved code identity.

The approved manifest freezes tracked Git blobs.  This companion manifest is
captured only after cache/data restore and refresh, so prefix-restored mutable
inputs cannot share an approval identity without publishing different hashes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_VERSION = "run287-fullrun-runtime-source-manifest-v1"
CONTRACT_SCHEMA_VERSION = "run287-fullrun-runtime-source-contract-v1"


def canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_head() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
    ).strip()


def git_blob_bytes(relative: str) -> bytes:
    return subprocess.check_output(
        ["git", "show", f"HEAD:{relative}"], cwd=REPO_ROOT
    )


def git_blob_sha256(relative: str) -> str:
    return sha256_bytes(git_blob_bytes(relative))


def safe_relative(value: Any) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    path = Path(raw)
    if not raw or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe runtime source path: {value!r}")
    return raw


def expand_source(pattern: str) -> list[Path]:
    relative = safe_relative(pattern)
    has_magic = any(char in relative for char in "*?[")
    roots = list(REPO_ROOT.glob(relative)) if has_magic else [REPO_ROOT / relative]
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        resolved = root.resolve(strict=True)
        resolved.relative_to(REPO_ROOT.resolve())
        if root.is_symlink():
            raise ValueError(f"symlink runtime source is not allowed: {relative}")
        if root.is_file():
            files.append(root)
            continue
        for candidate in root.rglob("*"):
            if candidate.is_symlink():
                raise ValueError(
                    "symlink below runtime source is not allowed: "
                    f"{candidate.relative_to(REPO_ROOT).as_posix()}"
                )
            if candidate.is_file():
                candidate.resolve(strict=True).relative_to(REPO_ROOT.resolve())
                files.append(candidate)
    return files


def capture_group(label: str, spec: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    failures: list[str] = []
    patterns = spec.get("paths")
    if not isinstance(patterns, list) or not patterns:
        return {}, [f"runtime_source_group_paths_invalid:{label}"]
    files: dict[str, Path] = {}
    try:
        for pattern in patterns:
            for path in expand_source(str(pattern)):
                files[path.relative_to(REPO_ROOT).as_posix()] = path
    except Exception as exc:
        return {}, [f"runtime_source_group_unsafe:{label}:{exc}"]
    records = [
        {
            "path": relative,
            "size_bytes": int(path.stat().st_size),
            "sha256": sha256_file(path),
        }
        for relative, path in sorted(files.items())
    ]
    min_files = int(spec.get("min_files", 0) or 0)
    if len(records) < min_files:
        failures.append(
            f"runtime_source_group_below_minimum:{label}:{len(records)}<{min_files}"
        )
    payload = {
        "paths": [safe_relative(item) for item in patterns],
        "min_files": min_files,
        "file_count": len(records),
        "total_bytes": sum(item["size_bytes"] for item in records),
        "files": records,
        "aggregate_sha256": sha256_bytes(canonical_json(records)),
    }
    return payload, failures


def canonical_timestamp(value: Any) -> str:
    parsed = datetime.fromisoformat(str(value or "").strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("decision_time_utc must include an explicit UTC offset")
    return parsed.astimezone(timezone.utc).isoformat()


def bool_value(value: Any) -> bool:
    normalized = str(value or "").strip().lower()
    if normalized in {"1", "true", "yes"}:
        return True
    if normalized in {"0", "false", "no"}:
        return False
    raise ValueError(f"invalid boolean: {value!r}")


def build(args: argparse.Namespace) -> dict[str, Any]:
    failures: list[str] = []
    approved_relative = safe_relative(args.approved_manifest)
    approved_bytes = b""
    try:
        approved_bytes = git_blob_bytes(approved_relative)
        approved_hash = sha256_bytes(approved_bytes)
    except Exception as exc:
        approved_hash = ""
        failures.append(f"approved_manifest_git_blob_invalid:{exc}")
    expected_hash = str(args.expected_manifest_sha256 or "").strip().lower()
    if approved_hash != expected_hash:
        failures.append("approved_manifest_sha256_mismatch")
    actual_head = git_head()
    expected_head = str(args.expected_commit_sha or "").strip().lower()
    if actual_head != expected_head:
        failures.append("approved_commit_sha_mismatch")
    try:
        # Parse exactly the committed bytes whose digest was approved.  Reading
        # the worktree path here would let a post-verification mutation change
        # runtime group semantics while retaining the committed blob hash.
        manifest = json.loads(approved_bytes.decode("utf-8"))
    except Exception as exc:
        manifest = {}
        failures.append(f"approved_manifest_json_invalid:{exc}")

    runtime_contract = manifest.get("runtime_source_contract")
    if not isinstance(runtime_contract, dict):
        runtime_contract = {}
        failures.append("runtime_source_contract_missing")
    if runtime_contract.get("schema_version") != CONTRACT_SCHEMA_VERSION:
        failures.append("runtime_source_contract_schema_mismatch")
    stages = runtime_contract.get("stages")
    stage_name = str(args.stage or "").strip()
    stage_spec = stages.get(stage_name) if isinstance(stages, dict) else None
    if not isinstance(stage_spec, dict):
        stage_spec = {}
        failures.append(f"runtime_source_stage_missing:{stage_name}")
    group_specs = stage_spec.get("groups")
    if not isinstance(group_specs, dict) or not group_specs:
        group_specs = {}
        failures.append(f"runtime_source_groups_missing:{stage_name}")

    groups: dict[str, Any] = {}
    for label, spec in sorted(group_specs.items()):
        if not isinstance(spec, dict):
            failures.append(f"runtime_source_group_invalid:{label}")
            continue
        group, group_failures = capture_group(str(label), spec)
        groups[str(label)] = group
        failures.extend(group_failures)

    try:
        decision_time = canonical_timestamp(args.decision_time_utc)
        skip_collector = bool_value(args.skip_collector)
    except Exception as exc:
        decision_time = str(args.decision_time_utc or "")
        skip_collector = False
        failures.append(f"runtime_identity_invalid:{exc}")
    identity = {
        "schema_version": SCHEMA_VERSION,
        "stage": stage_name,
        "approved_manifest": {
            "path": approved_relative,
            "git_blob_sha256": approved_hash,
        },
        "code_identity": {
            "git_head": actual_head,
            "approved_commit_sha": expected_head,
        },
        "decision_identity": {
            "resolved_session_date": str(args.resolved_session_date or "").strip(),
            "decision_time_utc": decision_time,
            "skip_collector": skip_collector,
        },
        "workflow_identity": str(args.workflow_identity or "").strip(),
        "groups": groups,
    }
    payload = {
        **identity,
        "status": (
            "READY_FULLRUN_RUNTIME_SOURCE_MANIFEST"
            if not failures
            else "BLOCKED_FULLRUN_RUNTIME_SOURCE_MANIFEST"
        ),
        "ready": not failures,
        "contract_failures": sorted(set(failures)),
        "runtime_source_identity_sha256": sha256_bytes(canonical_json(identity)),
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "automatic_promotion_allowed": False,
    }
    output = Path(args.output)
    if not output.is_absolute():
        output = REPO_ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approved-manifest", required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--expected-commit-sha", required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--resolved-session-date", required=True)
    parser.add_argument("--decision-time-utc", required=True)
    parser.add_argument("--skip-collector", required=True)
    parser.add_argument("--workflow-identity", default=os.environ.get("GITHUB_RUN_ID", "local"))
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def main() -> int:
    payload = build(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
