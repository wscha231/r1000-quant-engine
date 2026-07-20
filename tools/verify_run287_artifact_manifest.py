#!/usr/bin/env python3
"""Verify Run287 artifact manifests and resolve trusted CI baselines.

External or manually supplied artifacts are never trusted by path alone.  A
manifest must enumerate every payload file (other than the manifest itself),
and every byte count and SHA-256 digest must match before a consumer can read
the artifact.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path, PurePosixPath
from typing import Any


SCHEMA_VERSION = "run287-artifact-manifest-v1"
CANONICAL_FIXTURE = (
    Path(__file__).resolve().parent.parent
    / "tests"
    / "fixtures"
    / "run287_canonical_baseline"
)
REQUIRED_METADATA = (
    "source_commit",
    "source_run_id",
    "generated_at",
    "retention_policy",
    "restore_command",
    "privacy_safety",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_relative_path(value: str) -> bool:
    candidate = PurePosixPath(value.replace("\\", "/"))
    return bool(value) and not candidate.is_absolute() and ".." not in candidate.parts


def verify_manifest(root: Path, manifest_path: Path | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    root = root.resolve()
    manifest_path = (manifest_path or root / "manifest.json").resolve()
    errors: list[dict[str, Any]] = []
    checked = 0
    checked_bytes = 0

    if not root.is_dir():
        return {
            "status": "UNSUPPORTED_BASELINE_PATH",
            "trusted": False,
            "root": str(root),
            "errors": [{"code": "ROOT_MISSING", "path": str(root)}],
            "duration_seconds": round(time.perf_counter() - started, 6),
        }
    if not manifest_path.is_file():
        return {
            "status": "UNSUPPORTED_BASELINE_PATH",
            "trusted": False,
            "root": str(root),
            "errors": [{"code": "MANIFEST_MISSING", "path": str(manifest_path)}],
            "duration_seconds": round(time.perf_counter() - started, 6),
        }

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "status": "MANIFEST_INVALID",
            "trusted": False,
            "root": str(root),
            "errors": [{"code": "MANIFEST_PARSE_ERROR", "detail": str(exc)}],
            "duration_seconds": round(time.perf_counter() - started, 6),
        }

    if payload.get("schema_version") != SCHEMA_VERSION:
        errors.append({"code": "SCHEMA_VERSION_MISMATCH"})
    for key in REQUIRED_METADATA:
        if not payload.get(key):
            errors.append({"code": "REQUIRED_METADATA_MISSING", "field": key})

    entries = payload.get("files")
    if not isinstance(entries, list) or not entries:
        errors.append({"code": "FILE_LIST_EMPTY"})
        entries = []

    declared: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            errors.append({"code": "FILE_ENTRY_INVALID"})
            continue
        rel = str(entry.get("path") or "")
        if not _safe_relative_path(rel) or rel == "manifest.json":
            errors.append({"code": "UNSAFE_FILE_PATH", "path": rel})
            continue
        if rel in declared:
            errors.append({"code": "DUPLICATE_FILE_ENTRY", "path": rel})
            continue
        declared.add(rel)
        path = (root / Path(rel)).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            errors.append({"code": "PATH_ESCAPE", "path": rel})
            continue
        if not path.is_file():
            errors.append({"code": "FILE_MISSING", "path": rel})
            continue
        actual_size = path.stat().st_size
        expected_size = entry.get("size_bytes")
        if expected_size != actual_size:
            errors.append(
                {"code": "SIZE_MISMATCH", "path": rel, "expected": expected_size, "actual": actual_size}
            )
            continue
        actual_hash = _sha256(path)
        expected_hash = str(entry.get("sha256") or "").lower()
        if actual_hash != expected_hash:
            errors.append(
                {"code": "SHA256_MISMATCH", "path": rel, "expected": expected_hash, "actual": actual_hash}
            )
            continue
        checked += 1
        checked_bytes += actual_size

    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.resolve() != manifest_path
    }
    for rel in sorted(actual - declared):
        errors.append({"code": "UNDECLARED_FILE", "path": rel})
    for rel in sorted(declared - actual):
        if not any(e.get("code") == "FILE_MISSING" and e.get("path") == rel for e in errors):
            errors.append({"code": "DECLARED_FILE_MISSING", "path": rel})

    trusted = not errors and checked == len(entries)
    return {
        "status": "TRUSTED" if trusted else "CHECKSUM_VERIFICATION_FAILED",
        "trusted": trusted,
        "root": str(root),
        "manifest": str(manifest_path),
        "checked_files": checked,
        "checked_bytes": checked_bytes,
        "duration_seconds": round(time.perf_counter() - started, 6),
        "errors": errors,
    }


def resolve_baseline(requested: str | None) -> dict[str, Any]:
    path = Path(requested).resolve() if requested else CANONICAL_FIXTURE.resolve()
    result = verify_manifest(path)
    canonical = path == CANONICAL_FIXTURE.resolve()
    result["baseline_mode"] = "CANONICAL_CI_FIXTURE" if canonical else "CUSTOM_MATERIALIZED"
    if result["trusted"]:
        result["status"] = "READY" if canonical else "READY_CUSTOM_MATERIALIZED"
        result["resolved_path"] = str(path)
    elif not canonical:
        result["status"] = "UNSUPPORTED_BASELINE_PATH"
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", help="Artifact directory to verify")
    parser.add_argument("--manifest", help="Optional manifest path")
    parser.add_argument("--resolve-baseline", help="Resolve canonical or custom baseline path")
    parser.add_argument("--output", help="Optional JSON result path")
    args = parser.parse_args()

    if args.resolve_baseline is not None:
        result = resolve_baseline(args.resolve_baseline or None)
    elif args.root:
        result = verify_manifest(Path(args.root), Path(args.manifest) if args.manifest else None)
    else:
        parser.error("use --root or --resolve-baseline")

    rendered = json.dumps(result, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if result.get("trusted") else 2


if __name__ == "__main__":
    raise SystemExit(main())
