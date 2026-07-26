#!/usr/bin/env python3
"""Write one hash-bound Run287 price-refresh attempt sidecar."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    if not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def manifest_contract(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        "schema_version": str(payload.get("schema_version") or ""),
        "status": str(payload.get("status") or ""),
        "refresh_through_date": str(
            payload.get("refresh_through_date") or ""
        ),
        "refresh_through_exact_coverage": payload.get(
            "refresh_through_exact_coverage"
        ),
        "refresh_through_ticker_count": payload.get(
            "refresh_through_ticker_count"
        ),
        "refresh_through_exact_ticker_count": payload.get(
            "refresh_through_exact_ticker_count"
        ),
    }


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    manifest = Path(args.manifest)
    prior_manifest = Path(args.prior_manifest) if args.prior_manifest else None
    manifest_exists = manifest.is_file()
    return {
        "schema_version": "run287-price-refresh-attempt-v1",
        "phase": str(args.phase),
        "status": str(args.status),
        "exit_code": int(args.exit_code),
        "required_through_date": str(args.required_through_date),
        "manifest_path": str(manifest),
        "manifest_exists": manifest_exists,
        "manifest_current_attempt": (
            int(args.exit_code) == 0 and manifest_exists
        ),
        "manifest_sha256": sha256_file(manifest),
        "manifest_contract": manifest_contract(manifest),
        "prior_manifest_archived": bool(
            prior_manifest is not None and prior_manifest.is_file()
        ),
        "prior_manifest_sha256": (
            sha256_file(prior_manifest)
            if prior_manifest is not None
            else ""
        ),
        "source_commit_sha": str(args.source_commit_sha),
        "workflow_identity": str(args.workflow_identity),
        "run_id": str(args.run_id),
        "run_attempt": str(args.run_attempt),
    }


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    if temporary.exists():
        raise FileExistsError("price_refresh_attempt_stage_exists")
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exit-code", type=int, required=True)
    parser.add_argument("--status", required=True)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--prior-manifest", default="")
    parser.add_argument(
        "--required-through-date",
        default=os.environ.get("LAST_NYSE_SESSION_DATE", ""),
    )
    parser.add_argument(
        "--source-commit-sha",
        default=os.environ.get("GITHUB_SHA", ""),
    )
    parser.add_argument(
        "--workflow-identity",
        default=os.environ.get("GITHUB_WORKFLOW_REF", ""),
    )
    parser.add_argument(
        "--run-id",
        default=os.environ.get("GITHUB_RUN_ID", ""),
    )
    parser.add_argument(
        "--run-attempt",
        default=os.environ.get("GITHUB_RUN_ATTEMPT", ""),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_payload(args)
    write_json_atomic(Path(args.output), payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
