#!/usr/bin/env python3
"""Fail closed unless a Run287 catch-up can use durable Google Drive state."""
from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path
from typing import Any


ALLOWED_CANONICAL_STATES = {
    "PROVEN_PRESENT",
    "PROVEN_ABSENT",
    "REPAIR_FROM_IMMUTABLE",
}
TRUE_VALUES = {"1", "true", "yes"}


def as_bool(value: Any) -> bool:
    return str(value or "").strip().lower() in TRUE_VALUES


def evaluate_readiness(
    *,
    phase: str,
    catchup_mode: bool,
    auth_configured: bool,
    gdrive_ready: bool,
    rclone_available: bool,
    canonical_state: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": "run287-catchup-drive-readiness-v1",
        "phase": phase,
        "catchup_mode": bool(catchup_mode),
        "allowed": True,
        "status": "",
        "message": "",
        "github_env_updates": {},
    }
    if phase == "authentication":
        if auth_configured:
            result["status"] = "READY_AUTH_CONFIGURED"
        elif catchup_mode:
            result.update(
                {
                    "allowed": False,
                    "status": "BLOCKED_DURABLE_DRIVE_AUTH",
                    "message": (
                        "[paper-catchup] BLOCKED: durable Drive authentication "
                        "is required"
                    ),
                }
            )
        else:
            result["status"] = "READY_NON_CATCHUP_CACHE_ONLY"
            result["github_env_updates"] = {"GDRIVE_READY": "no"}
        return result

    if phase != "restored":
        raise ValueError(f"unsupported phase: {phase}")
    if not catchup_mode:
        result["status"] = "READY_NOT_CATCHUP"
        return result
    if not gdrive_ready or not rclone_available:
        result.update(
            {
                "allowed": False,
                "status": "BLOCKED_DURABLE_DRIVE_RESTORE",
                "message": (
                    "[paper-catchup] BLOCKED: durable Drive restore is unavailable"
                ),
            }
        )
        return result
    normalized_state = str(canonical_state or "").strip().upper()
    if normalized_state not in ALLOWED_CANONICAL_STATES:
        result.update(
            {
                "allowed": False,
                "status": "BLOCKED_DURABLE_DRIVE_STATE",
                "message": (
                    "[paper-catchup] BLOCKED: durable Drive canonical state was "
                    "not classified"
                ),
            }
        )
        return result
    result["status"] = "READY_DURABLE_DRIVE"
    result["canonical_state"] = normalized_state
    return result


def append_github_env(path_value: str, updates: dict[str, str]) -> None:
    if not updates or not str(path_value or "").strip():
        return
    path = Path(path_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for key, value in updates.items():
            handle.write(f"{key}={value}\n")


def evaluate_environment(phase: str) -> dict[str, Any]:
    return evaluate_readiness(
        phase=phase,
        catchup_mode=as_bool(os.environ.get("PAPER_CATCHUP_MODE")),
        auth_configured=bool(
            str(os.environ.get("RCLONE_CONFIG_GDRIVE") or "").strip()
            or str(os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY") or "").strip()
        ),
        gdrive_ready=as_bool(os.environ.get("GDRIVE_READY")),
        rclone_available=shutil.which("rclone") is not None,
        canonical_state=str(
            os.environ.get("PAPER_CANONICAL_REMOTE_STATE") or ""
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase",
        required=True,
        choices=("authentication", "restored"),
    )
    args = parser.parse_args()
    result = evaluate_environment(args.phase)
    append_github_env(
        os.environ.get("GITHUB_ENV", ""),
        result.get("github_env_updates") or {},
    )
    if result.get("message"):
        print(result["message"])
    print(json.dumps(result, sort_keys=True))
    return 0 if result["allowed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
