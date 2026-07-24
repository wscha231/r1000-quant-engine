#!/usr/bin/env python3
"""Create an owner-authored, short-lived Run287 catch-up scope attestation."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

if __package__:
    from .check_run287_github_secret_scope import evaluate_scope_metadata
    from .verify_run287_catchup_scope_attestation import (
        ANCHOR_ISSUE_NUMBER,
        ANCHOR_ISSUE_ID,
        ANCHOR_ISSUE_NODE_ID,
        ATTESTED_DISPATCH_INPUT_KEYS,
        ATTESTATION_SCHEMA,
        DEFAULT_BRANCH,
        DIGEST_RE,
        ENVIRONMENT_NAME,
        EXPECTED_AUTHORIZATION,
        EXPECTED_SCOPE,
        MAX_TTL_SECONDS,
        OWNER_LOGIN,
        OWNER_ID,
        OWNER_NODE_ID,
        REPOSITORY,
        REPOSITORY_ID,
        REPOSITORY_NODE_ID,
        RUN_ID_RE,
        SHA_RE,
        WORKFLOW_ID,
        WORKFLOW_NODE_ID,
        WORKFLOW_PATH,
        canonical_json,
        expected_dispatch_inputs,
        file_sha256,
        utc_text,
        verify_attestation_comment,
    )
else:
    from check_run287_github_secret_scope import evaluate_scope_metadata
    from verify_run287_catchup_scope_attestation import (
        ANCHOR_ISSUE_NUMBER,
        ANCHOR_ISSUE_ID,
        ANCHOR_ISSUE_NODE_ID,
        ATTESTED_DISPATCH_INPUT_KEYS,
        ATTESTATION_SCHEMA,
        DEFAULT_BRANCH,
        DIGEST_RE,
        ENVIRONMENT_NAME,
        EXPECTED_AUTHORIZATION,
        EXPECTED_SCOPE,
        MAX_TTL_SECONDS,
        OWNER_LOGIN,
        OWNER_ID,
        OWNER_NODE_ID,
        REPOSITORY,
        REPOSITORY_ID,
        REPOSITORY_NODE_ID,
        RUN_ID_RE,
        SHA_RE,
        WORKFLOW_ID,
        WORKFLOW_NODE_ID,
        WORKFLOW_PATH,
        canonical_json,
        expected_dispatch_inputs,
        file_sha256,
        utc_text,
        verify_attestation_comment,
    )


API_VERSION = "2022-11-28"
MIN_TTL_SECONDS = 60
DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
CRITICAL_SOURCE_PATHS = (
    ".github/workflows/daily_operating_selection_refresh.yml",
    "data_static/run287_durable_environment_contract.json",
    "tools/check_run287_catchup_drive_readiness.py",
    "tools/check_run287_github_secret_scope.py",
    "tools/create_run287_catchup_scope_attestation.py",
    "tools/run287_catchup_scope_consumption.py",
    "tools/verify_run287_catchup_scope_attestation.py",
)


class SafeCommandError(RuntimeError):
    """Command failure whose message intentionally excludes command output."""


def run_command_json(
    command: list[str],
    *,
    stdin_payload: dict[str, Any] | None = None,
) -> Any:
    completed = subprocess.run(
        command,
        input=(
            canonical_json(stdin_payload)
            if stdin_payload is not None
            else None
        ),
        cwd=Path(__file__).resolve().parent.parent,
        env=os.environ.copy(),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise SafeCommandError(
            f"command failed without exposing captured output: {command[0]}"
        )
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SafeCommandError(
            f"command returned non-JSON output: {command[0]}"
        ) from exc


def gh_json(
    endpoint: str,
    *,
    paginate: bool = False,
    method: str = "GET",
    stdin_payload: dict[str, Any] | None = None,
) -> Any:
    command = [
        "gh",
        "api",
        "-H",
        "Accept: application/vnd.github+json",
        "-H",
        f"X-GitHub-Api-Version: {API_VERSION}",
    ]
    if paginate:
        command.extend(["--paginate", "--slurp"])
    if method != "GET":
        command.extend(["--method", method])
    if stdin_payload is not None:
        command.extend(["--input", "-"])
    command.append(endpoint)
    return run_command_json(command, stdin_payload=stdin_payload)


def combine_secret_pages(payload: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(payload, list) or not payload:
        raise SafeCommandError(f"{label} secret metadata pages are invalid")
    total_counts: set[int] = set()
    rows: list[dict[str, Any]] = []
    for page in payload:
        if not isinstance(page, dict):
            raise SafeCommandError(
                f"{label} secret metadata page is invalid"
            )
        total = page.get("total_count")
        secrets = page.get("secrets")
        if type(total) is not int or not isinstance(secrets, list):
            raise SafeCommandError(
                f"{label} secret metadata shape is invalid"
            )
        total_counts.add(total)
        for row in secrets:
            if not isinstance(row, dict):
                raise SafeCommandError(
                    f"{label} secret metadata row is invalid"
                )
            rows.append(row)
    if len(total_counts) != 1:
        raise SafeCommandError(
            f"{label} secret metadata total changed during pagination"
        )
    return {
        "total_count": next(iter(total_counts)),
        "secrets": rows,
    }


def scope_subset(scope_result: dict[str, Any]) -> dict[str, Any]:
    subset = {key: scope_result.get(key) for key in EXPECTED_SCOPE}
    if subset != EXPECTED_SCOPE:
        raise ValueError("durable secret scope is not environment-only")
    return subset


def build_attestation(
    *,
    scope_result: dict[str, Any],
    default_branch_sha: str,
    session_date: str,
    evidence_run_id: str,
    evidence_artifact_digest: str,
    checked_at: datetime,
    ttl_seconds: int,
    nonce: str | None = None,
) -> dict[str, Any]:
    if not SHA_RE.fullmatch(default_branch_sha):
        raise ValueError("default branch SHA must be 40 lowercase hex")
    if not DATE_RE.fullmatch(session_date):
        raise ValueError("session date must be YYYY-MM-DD")
    try:
        datetime.strptime(session_date, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("session date is not a calendar date") from exc
    if not RUN_ID_RE.fullmatch(evidence_run_id):
        raise ValueError("evidence run id must be a positive integer")
    if not DIGEST_RE.fullmatch(evidence_artifact_digest):
        raise ValueError("evidence artifact digest must be sha256:<64 hex>")
    if not MIN_TTL_SECONDS <= ttl_seconds <= MAX_TTL_SECONDS:
        raise ValueError(
            f"ttl must be {MIN_TTL_SECONDS}..{MAX_TTL_SECONDS} seconds"
        )
    checked_at = checked_at.astimezone(timezone.utc).replace(microsecond=0)
    request_nonce = nonce or str(uuid4())
    expected_inputs = expected_dispatch_inputs(
        session_date=session_date,
        evidence_run_id=evidence_run_id,
        evidence_artifact_digest=evidence_artifact_digest,
        comment_id=1,
    )
    return {
        "schema_version": ATTESTATION_SCHEMA,
        "status": "VERIFIED_ENVIRONMENT_ONLY",
        "source": "OWNER_LOCAL_GH_SCOPE_PREFLIGHT",
        "repository": REPOSITORY,
        "repository_id": REPOSITORY_ID,
        "repository_node_id": REPOSITORY_NODE_ID,
        "environment": ENVIRONMENT_NAME,
        "durable_environment_contract_sha256": file_sha256(),
        "anchor_issue_number": ANCHOR_ISSUE_NUMBER,
        "anchor_issue_id": ANCHOR_ISSUE_ID,
        "anchor_issue_node_id": ANCHOR_ISSUE_NODE_ID,
        "session_date": session_date,
        "catchup_price_evidence_run_id": evidence_run_id,
        "catchup_price_evidence_artifact_digest": (
            evidence_artifact_digest
        ),
        "attested_actor": OWNER_LOGIN,
        "attested_actor_id": OWNER_ID,
        "attested_actor_node_id": OWNER_NODE_ID,
        "checked_at": utc_text(checked_at),
        "expires_at": utc_text(
            checked_at + timedelta(seconds=ttl_seconds)
        ),
        "request_nonce": request_nonce,
        "workflow": {
            "default_branch": DEFAULT_BRANCH,
            "default_branch_sha": default_branch_sha,
            "event": "workflow_dispatch",
            "path": WORKFLOW_PATH,
            "ref": f"refs/heads/{DEFAULT_BRANCH}",
            "workflow_id": WORKFLOW_ID,
            "workflow_node_id": WORKFLOW_NODE_ID,
        },
        "dispatch_inputs": {
            key: expected_inputs[key]
            for key in ATTESTED_DISPATCH_INPUT_KEYS
        },
        "scope": scope_subset(scope_result),
        "authorization": dict(EXPECTED_AUTHORIZATION),
    }


def require_mapping(payload: Any, label: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise SafeCommandError(f"{label} response is not an object")
    return payload


def read_git_head() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=Path(__file__).resolve().parent.parent,
        env=os.environ.copy(),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    head = completed.stdout.strip()
    if completed.returncode != 0 or not SHA_RE.fullmatch(head):
        raise SafeCommandError("unable to verify the local Git HEAD")
    return head


def require_clean_critical_sources() -> None:
    completed = subprocess.run(
        [
            "git",
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--",
            *CRITICAL_SOURCE_PATHS,
        ],
        cwd=Path(__file__).resolve().parent.parent,
        env=os.environ.copy(),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0 or completed.stdout.strip():
        raise SafeCommandError(
            "critical attestation sources are not clean at local HEAD"
        )


def fetch_verified_scope(expected_default_sha: str) -> dict[str, Any]:
    user = require_mapping(gh_json("user"), "authenticated user")
    if {
        "login": user.get("login"),
        "id": user.get("id"),
        "node_id": user.get("node_id"),
        "type": user.get("type"),
    } != {
        "login": OWNER_LOGIN,
        "id": OWNER_ID,
        "node_id": OWNER_NODE_ID,
        "type": "User",
    }:
        raise SafeCommandError("authenticated gh identity is not the owner")

    repository = require_mapping(
        gh_json(f"repos/{REPOSITORY}"),
        "repository",
    )
    repository_owner = repository.get("owner")
    if (
        repository.get("id") != REPOSITORY_ID
        or repository.get("node_id") != REPOSITORY_NODE_ID
        or repository.get("full_name") != REPOSITORY
        or repository.get("default_branch") != DEFAULT_BRANCH
        or not isinstance(repository_owner, dict)
        or repository_owner.get("login") != OWNER_LOGIN
        or repository_owner.get("id") != OWNER_ID
        or repository_owner.get("node_id") != OWNER_NODE_ID
        or repository_owner.get("type") != "User"
    ):
        raise SafeCommandError("repository identity contract mismatch")

    branch = require_mapping(
        gh_json(f"repos/{REPOSITORY}/branches/{DEFAULT_BRANCH}"),
        "default branch",
    )
    commit = branch.get("commit")
    remote_sha = commit.get("sha") if isinstance(commit, dict) else None
    if remote_sha != expected_default_sha:
        raise SafeCommandError("remote default branch SHA changed")
    if read_git_head() != expected_default_sha:
        raise SafeCommandError(
            "local tool HEAD is not the attested default branch SHA"
        )
    require_clean_critical_sources()

    issue = require_mapping(
        gh_json(f"repos/{REPOSITORY}/issues/{ANCHOR_ISSUE_NUMBER}"),
        "anchor issue",
    )
    issue_user = issue.get("user")
    if (
        issue.get("id") != ANCHOR_ISSUE_ID
        or issue.get("node_id") != ANCHOR_ISSUE_NODE_ID
        or issue.get("number") != ANCHOR_ISSUE_NUMBER
        or issue.get("state") != "open"
        or issue.get("locked") is not False
        or issue.get("title")
        != "Run287 durable catch-up scope attestations"
        or "pull_request" in issue
        or not isinstance(issue_user, dict)
        or issue_user.get("login") != OWNER_LOGIN
        or issue_user.get("id") != OWNER_ID
        or issue_user.get("node_id") != OWNER_NODE_ID
        or issue_user.get("type") != "User"
    ):
        raise SafeCommandError("scope-attestation anchor issue mismatch")

    workflow = require_mapping(
        gh_json(
            f"repos/{REPOSITORY}/actions/workflows/"
            f"{Path(WORKFLOW_PATH).name}"
        ),
        "workflow",
    )
    if (
        workflow.get("id") != WORKFLOW_ID
        or workflow.get("node_id") != WORKFLOW_NODE_ID
        or workflow.get("path") != WORKFLOW_PATH
        or workflow.get("state") != "active"
    ):
        raise SafeCommandError("workflow identity contract mismatch")

    repository_pages = gh_json(
        f"repos/{REPOSITORY}/actions/secrets?per_page=100",
        paginate=True,
    )
    environment_pages = gh_json(
        "repos/"
        f"{REPOSITORY}/environments/{ENVIRONMENT_NAME}/secrets?per_page=100",
        paginate=True,
    )
    scope_result = evaluate_scope_metadata(
        repository=combine_secret_pages(
            repository_pages,
            label="repository",
        ),
        environment=combine_secret_pages(
            environment_pages,
            label="environment",
        ),
    )
    if not scope_result["allowed"]:
        raise SafeCommandError("durable secret scope verification failed")
    return scope_result


def synthetic_event(
    *,
    comment_id: int,
    session_date: str,
    evidence_run_id: str,
    evidence_artifact_digest: str,
) -> dict[str, Any]:
    return {
        "inputs": expected_dispatch_inputs(
            session_date=session_date,
            evidence_run_id=evidence_run_id,
            evidence_artifact_digest=evidence_artifact_digest,
            comment_id=comment_id,
        )
    }


def synthetic_run(
    *,
    default_branch_sha: str,
    created_at: str,
) -> dict[str, Any]:
    owner = {
        "login": OWNER_LOGIN,
        "id": OWNER_ID,
        "node_id": OWNER_NODE_ID,
        "type": "User",
    }
    return {
        "id": 1,
        "run_attempt": 1,
        "event": "workflow_dispatch",
        "head_sha": default_branch_sha,
        "head_branch": DEFAULT_BRANCH,
        "path": WORKFLOW_PATH,
        "workflow_id": WORKFLOW_ID,
        "created_at": created_at,
        "run_started_at": created_at,
        "actor": dict(owner),
        "triggering_actor": dict(owner),
        "repository": {
            "id": REPOSITORY_ID,
            "node_id": REPOSITORY_NODE_ID,
            "full_name": REPOSITORY,
            "owner": dict(owner),
        },
    }


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-default-branch-sha", required=True)
    parser.add_argument("--session-date", required=True)
    parser.add_argument("--price-evidence-run-id", required=True)
    parser.add_argument(
        "--price-evidence-artifact-digest",
        required=True,
    )
    parser.add_argument("--ttl-seconds", type=int, default=900)
    parser.add_argument("--post", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        scope_result = fetch_verified_scope(
            args.expected_default_branch_sha
        )
        checked_at = datetime.now(timezone.utc)
        attestation = build_attestation(
            scope_result=scope_result,
            default_branch_sha=args.expected_default_branch_sha,
            session_date=args.session_date,
            evidence_run_id=args.price_evidence_run_id,
            evidence_artifact_digest=(
                args.price_evidence_artifact_digest
            ),
            checked_at=checked_at,
            ttl_seconds=args.ttl_seconds,
        )
    except (SafeCommandError, ValueError) as exc:
        print(f"[run287-scope-attestation] BLOCKED: {exc}")
        return 2

    if not args.post:
        result = {
            "schema_version": "run287-durable-scope-attestation-dry-run-v1",
            "status": "DRY_RUN_VERIFIED_NOT_POSTED",
            "posted": False,
            "repository": REPOSITORY,
            "anchor_issue_number": ANCHOR_ISSUE_NUMBER,
            "default_branch_sha": args.expected_default_branch_sha,
            "session_date": args.session_date,
            "expires_at": attestation["expires_at"],
            "request_nonce": attestation["request_nonce"],
        }
        write_json(args.output, result)
        print(json.dumps(result, sort_keys=True))
        return 0

    try:
        comment = require_mapping(
            gh_json(
                f"repos/{REPOSITORY}/issues/"
                f"{ANCHOR_ISSUE_NUMBER}/comments",
                method="POST",
                stdin_payload={"body": canonical_json(attestation)},
            ),
            "created comment",
        )
        comment_id = comment.get("id")
        if type(comment_id) is not int or comment_id <= 0:
            raise SafeCommandError(
                "created comment did not return a valid id"
            )
        verification = verify_attestation_comment(
            comment=comment,
            run=synthetic_run(
                default_branch_sha=args.expected_default_branch_sha,
                created_at=str(comment.get("created_at") or ""),
            ),
            event=synthetic_event(
                comment_id=comment_id,
                session_date=args.session_date,
                evidence_run_id=args.price_evidence_run_id,
                evidence_artifact_digest=(
                    args.price_evidence_artifact_digest
                ),
            ),
            expected_comment_id=comment_id,
            expected_repository=REPOSITORY,
            expected_default_branch=DEFAULT_BRANCH,
            expected_default_branch_sha=(
                args.expected_default_branch_sha
            ),
            expected_session_date=args.session_date,
            expected_evidence_run_id=args.price_evidence_run_id,
            expected_evidence_artifact_digest=(
                args.price_evidence_artifact_digest
            ),
            expected_workflow_run_id="1",
            workflow_actor=OWNER_LOGIN,
            now=datetime.now(timezone.utc),
        )
    except SafeCommandError as exc:
        print(f"[run287-scope-attestation] BLOCKED: {exc}")
        return 2

    result = {
        "schema_version": "run287-durable-scope-attestation-receipt-v1",
        "status": verification["status"],
        "posted": True,
        "allowed": verification["allowed"],
        "repository": REPOSITORY,
        "anchor_issue_number": ANCHOR_ISSUE_NUMBER,
        "comment_id": comment_id,
        "comment_url": comment.get("html_url"),
        "comment_body_sha256": verification["comment_body_sha256"],
        "default_branch_sha": args.expected_default_branch_sha,
        "session_date": args.session_date,
        "expires_at": attestation["expires_at"],
        "request_nonce": attestation["request_nonce"],
        "failures": verification["failures"],
    }
    write_json(args.output, result)
    print(json.dumps(result, sort_keys=True))
    return 0 if verification["allowed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
