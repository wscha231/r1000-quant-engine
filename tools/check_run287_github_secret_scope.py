#!/usr/bin/env python3
"""Verify that Run287 durable credentials exist only in the GitHub environment."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ENVIRONMENT_NAME = "run287-paper-durable"
ATTESTATION_SECRET = "RUN287_DURABLE_ENVIRONMENT_ATTESTATION"
RCLONE_SECRET = "RUN287_DURABLE_RCLONE_CONFIG_GDRIVE"
RESERVED_SERVICE_ACCOUNT_SECRET = (
    "RUN287_DURABLE_GOOGLE_SERVICE_ACCOUNT_KEY"
)
TRACKED_SECRETS = {
    ATTESTATION_SECRET,
    RCLONE_SECRET,
    RESERVED_SERVICE_ACCOUNT_SECRET,
}


def complete_names(
    payload: dict[str, Any],
    label: str,
) -> tuple[set[str], list[str]]:
    rows = payload.get("secrets")
    total = payload.get("total_count")
    failures: list[str] = []
    if not isinstance(rows, list) or type(total) is not int:
        return set(), [f"{label}_secret_metadata_shape_invalid"]
    if total != len(rows):
        failures.append(f"{label}_secret_metadata_pagination_incomplete")
    names: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            failures.append(f"{label}_secret_metadata_row_invalid")
            continue
        name = str(row.get("name") or "").strip().upper()
        if not name:
            failures.append(f"{label}_secret_metadata_name_empty")
            continue
        if name in names:
            failures.append(f"{label}_secret_metadata_name_duplicate")
        names.add(name)
    return names, failures


def evaluate_scope_metadata(
    *,
    repository: dict[str, Any],
    environment: dict[str, Any],
) -> dict[str, Any]:
    repository_names, repository_failures = complete_names(
        repository, "repository"
    )
    environment_names, environment_failures = complete_names(
        environment, "environment"
    )
    failures = repository_failures + environment_failures
    for required in (ATTESTATION_SECRET, RCLONE_SECRET):
        if required not in environment_names:
            failures.append(f"missing_environment_secret:{required}")
    if RESERVED_SERVICE_ACCOUNT_SECRET in environment_names:
        failures.append(
            "reserved_environment_secret_present:"
            + RESERVED_SERVICE_ACCOUNT_SECRET
        )
    for forbidden in sorted(TRACKED_SECRETS & repository_names):
        failures.append(f"repository_secret_forbidden:{forbidden}")
    failures = sorted(set(failures))
    return {
        "schema_version": "run287-durable-secret-scope-v1",
        "status": (
            "VERIFIED_ENVIRONMENT_ONLY"
            if not failures
            else "BLOCKED_SCOPE_MISMATCH"
        ),
        "allowed": not failures,
        "environment": ENVIRONMENT_NAME,
        "required_environment_secrets_present": all(
            name in environment_names
            for name in (ATTESTATION_SECRET, RCLONE_SECRET)
        ),
        "reserved_environment_secret_absent": (
            RESERVED_SERVICE_ACCOUNT_SECRET not in environment_names
        ),
        "tracked_repository_secrets_absent": not bool(
            TRACKED_SECRETS & repository_names
        ),
        "repository_metadata_complete": not repository_failures,
        "environment_metadata_complete": not environment_failures,
        "failures": failures,
        "github_env_updates": (
            {"RUN287_DURABLE_SCOPE_VERIFIED": "yes"}
            if not failures
            else {}
        ),
    }


def append_github_env(path_value: str, updates: dict[str, str]) -> None:
    if not updates or not str(path_value or "").strip():
        return
    path = Path(path_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for key, value in updates.items():
            handle.write(f"{key}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-metadata", type=Path, required=True)
    parser.add_argument("--environment-metadata", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--github-env", default="")
    args = parser.parse_args()

    repository = json.loads(
        args.repository_metadata.read_text(encoding="utf-8")
    )
    environment = json.loads(
        args.environment_metadata.read_text(encoding="utf-8")
    )
    result = evaluate_scope_metadata(
        repository=repository,
        environment=environment,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    append_github_env(args.github_env, result["github_env_updates"])
    print(json.dumps(result, sort_keys=True))
    return 0 if result["allowed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
