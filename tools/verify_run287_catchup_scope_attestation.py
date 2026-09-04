#!/usr/bin/env python3
"""Verify a short-lived owner-authored Run287 catch-up scope attestation."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID


ROOT = Path(__file__).resolve().parent.parent
CONTRACT_PATH = ROOT / "data_static" / (
    "run287_durable_environment_contract.json"
)
REPOSITORY = "wscha231/r1000-quant-engine"
REPOSITORY_ID = 1202801237
REPOSITORY_NODE_ID = "R_kgDOR7FKVQ"
OWNER_LOGIN = "wscha231"
OWNER_ID = 32551544
OWNER_NODE_ID = "MDQ6VXNlcjMyNTUxNTQ0"
ENVIRONMENT_NAME = "run287-paper-durable"
DEFAULT_BRANCH = "master"
ANCHOR_ISSUE_NUMBER = 324
ANCHOR_ISSUE_ID = 4966421996
ANCHOR_ISSUE_NODE_ID = "I_kwDOR7FKVc8AAAABKAWV7A"
WORKFLOW_ID = 296748480
WORKFLOW_NODE_ID = "W_kwDOR7FKVc4RsAXA"
WORKFLOW_PATH = ".github/workflows/daily_operating_selection_refresh.yml"
ATTESTATION_SCHEMA = "run287-durable-scope-attestation-v2"
VERIFICATION_SCHEMA = "run287-durable-scope-comment-verification-v2"
MAX_TTL_SECONDS = 900
MAX_RUN_LEASE_SECONDS = 3600
MAX_POST_DELAY_SECONDS = 120
MAX_CLOCK_SKEW_SECONDS = 60
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
RUN_ID_RE = re.compile(r"^[1-9][0-9]*$")
DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")

TOP_LEVEL_KEYS = {
    "anchor_issue_id",
    "anchor_issue_node_id",
    "anchor_issue_number",
    "attested_actor",
    "attested_actor_id",
    "attested_actor_node_id",
    "authorization",
    "catchup_price_evidence_artifact_digest",
    "catchup_price_evidence_run_id",
    "checked_at",
    "dispatch_inputs",
    "durable_environment_contract_sha256",
    "environment",
    "expires_at",
    "repository",
    "repository_id",
    "repository_node_id",
    "request_nonce",
    "schema_version",
    "scope",
    "session_date",
    "source",
    "status",
    "workflow",
}
SCOPE_KEYS = {
    "allowed",
    "environment",
    "environment_metadata_complete",
    "failures",
    "repository_metadata_complete",
    "required_environment_secrets_present",
    "reserved_environment_secret_absent",
    "schema_version",
    "status",
    "tracked_repository_secrets_absent",
}
EXPECTED_SCOPE = {
    "allowed": True,
    "environment": ENVIRONMENT_NAME,
    "environment_metadata_complete": True,
    "failures": [],
    "repository_metadata_complete": True,
    "required_environment_secrets_present": True,
    "reserved_environment_secret_absent": True,
    "schema_version": "run287-durable-secret-scope-v1",
    "status": "VERIFIED_ENVIRONMENT_ONLY",
    "tracked_repository_secrets_absent": True,
}
EXPECTED_AUTHORIZATION = {
    "automatic_promotion_authorized": False,
    "fullrun_authorized": False,
    "live_trading_authorized": False,
    "paper_catchup_only": True,
    "production_activation_authorized": False,
}
EVENT_INPUT_KEYS = {
    "allow_quarantined_legacy_outcome_parent",
    "allow_risk_outcome_genesis_bootstrap",
    "allow_verified_paper_canonical_head_bootstrap",
    "catchup_price_evidence_artifact_digest",
    "catchup_price_evidence_run_id",
    "catchup_secret_scope_attestation_comment_id",
    "capture_catchup_evidence_only",
    "force_run",
    "latest_run",
    "session_date",
    "strict_selection",
}
ATTESTED_DISPATCH_INPUT_KEYS = EVENT_INPUT_KEYS - {
    "catchup_secret_scope_attestation_comment_id"
}
BOOLEAN_INPUT_KEYS = {
    "allow_quarantined_legacy_outcome_parent",
    "allow_risk_outcome_genesis_bootstrap",
    "allow_verified_paper_canonical_head_bootstrap",
    "capture_catchup_evidence_only",
    "force_run",
    "strict_selection",
}


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def utc_text(value: datetime) -> str:
    normalized = value.astimezone(timezone.utc).replace(microsecond=0)
    return normalized.strftime("%Y-%m-%dT%H:%M:%SZ")


def file_sha256(path: Path = CONTRACT_PATH) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return hashlib.sha256(
        canonical_json(payload).encode("utf-8")
    ).hexdigest()


def parse_utc(
    value: Any,
    *,
    label: str,
    failures: list[str],
) -> datetime | None:
    if not isinstance(value, str):
        failures.append(f"{label}_invalid")
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        failures.append(f"{label}_invalid")
        return None
    return parsed.replace(tzinfo=timezone.utc)


def valid_uuid4(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError):
        return False
    return parsed.version == 4 and str(parsed) == value


def append_github_env(path_value: str, updates: dict[str, str]) -> None:
    if not updates or not str(path_value or "").strip():
        return
    path = Path(path_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for key, value in updates.items():
            handle.write(f"{key}={value}\n")


def exact_user(
    value: Any,
    *,
    label: str,
    failures: list[str],
) -> None:
    if not isinstance(value, dict):
        failures.append(f"{label}_invalid")
        return
    expected = {
        "login": OWNER_LOGIN,
        "id": OWNER_ID,
        "node_id": OWNER_NODE_ID,
        "type": "User",
    }
    for key, expected_value in expected.items():
        if value.get(key) != expected_value:
            failures.append(f"{label}_{key}_mismatch")


def normalize_boolean(
    value: Any,
    *,
    label: str,
    failures: list[str],
) -> bool | None:
    if type(value) is bool:
        return value
    if value == "true":
        return True
    if value == "false":
        return False
    failures.append(f"{label}_not_boolean")
    return None


def normalize_event_inputs(
    event: dict[str, Any],
    *,
    failures: list[str],
) -> dict[str, Any]:
    raw = event.get("inputs")
    if not isinstance(raw, dict) or set(raw) != EVENT_INPUT_KEYS:
        failures.append("workflow_dispatch_inputs_shape_invalid")
        return {}
    normalized: dict[str, Any] = {}
    for key in sorted(EVENT_INPUT_KEYS):
        value = raw.get(key)
        if key in BOOLEAN_INPUT_KEYS:
            normalized[key] = normalize_boolean(
                value,
                label=f"workflow_dispatch_input_{key}",
                failures=failures,
            )
        elif not isinstance(value, str):
            failures.append(f"workflow_dispatch_input_{key}_not_string")
        else:
            normalized[key] = value
    return normalized


def expected_dispatch_inputs(
    *,
    session_date: str,
    evidence_run_id: str,
    evidence_artifact_digest: str,
    comment_id: int,
) -> dict[str, Any]:
    return {
        "allow_quarantined_legacy_outcome_parent": False,
        "allow_risk_outcome_genesis_bootstrap": False,
        "allow_verified_paper_canonical_head_bootstrap": False,
        "catchup_price_evidence_artifact_digest": (
            evidence_artifact_digest
        ),
        "catchup_price_evidence_run_id": evidence_run_id,
        "catchup_secret_scope_attestation_comment_id": str(comment_id),
        "capture_catchup_evidence_only": False,
        "force_run": True,
        "latest_run": "outputs",
        "session_date": session_date,
        "strict_selection": True,
    }


def verify_run_metadata(
    *,
    run: dict[str, Any],
    expected_workflow_run_id: str,
    expected_default_branch_sha: str,
    workflow_actor: str,
    failures: list[str],
) -> tuple[datetime | None, datetime | None]:
    if not RUN_ID_RE.fullmatch(expected_workflow_run_id):
        failures.append("expected_workflow_run_id_invalid")
        expected_run_id: int | None = None
    else:
        expected_run_id = int(expected_workflow_run_id)
    exact_fields = {
        "id": expected_run_id,
        "run_attempt": 1,
        "event": "workflow_dispatch",
        "head_sha": expected_default_branch_sha,
        "head_branch": DEFAULT_BRANCH,
        "path": WORKFLOW_PATH,
        "workflow_id": WORKFLOW_ID,
    }
    for key, expected in exact_fields.items():
        if run.get(key) != expected:
            failures.append(f"workflow_run_{key}_mismatch")
    if workflow_actor != OWNER_LOGIN:
        failures.append("workflow_actor_not_owner")
    exact_user(run.get("actor"), label="workflow_run_actor", failures=failures)
    exact_user(
        run.get("triggering_actor"),
        label="workflow_run_triggering_actor",
        failures=failures,
    )
    repository = run.get("repository")
    if not isinstance(repository, dict):
        failures.append("workflow_run_repository_invalid")
    else:
        expected_repository = {
            "id": REPOSITORY_ID,
            "node_id": REPOSITORY_NODE_ID,
            "full_name": REPOSITORY,
        }
        for key, expected in expected_repository.items():
            if repository.get(key) != expected:
                failures.append(
                    f"workflow_run_repository_{key}_mismatch"
                )
        exact_user(
            repository.get("owner"),
            label="workflow_run_repository_owner",
            failures=failures,
        )
    created_at = parse_utc(
        run.get("created_at"),
        label="workflow_run_created_at",
        failures=failures,
    )
    started_at = parse_utc(
        run.get("run_started_at"),
        label="workflow_run_started_at",
        failures=failures,
    )
    if created_at is not None and started_at is not None:
        if started_at < created_at:
            failures.append("workflow_run_started_before_created")
        if started_at - created_at > timedelta(minutes=10):
            failures.append("workflow_run_start_delay_too_long")
    return created_at, started_at


def verify_attestation_comment(
    *,
    comment: dict[str, Any],
    run: dict[str, Any],
    event: dict[str, Any],
    expected_comment_id: int,
    expected_repository: str,
    expected_default_branch: str,
    expected_default_branch_sha: str,
    expected_session_date: str,
    expected_evidence_run_id: str,
    expected_evidence_artifact_digest: str,
    expected_workflow_run_id: str,
    workflow_actor: str,
    now: datetime,
    prior_verification: dict[str, Any] | None = None,
) -> dict[str, Any]:
    failures: list[str] = []
    now = now.astimezone(timezone.utc)

    if expected_repository != REPOSITORY:
        failures.append("expected_repository_not_pinned")
    if expected_default_branch != DEFAULT_BRANCH:
        failures.append("expected_default_branch_not_pinned")
    if (
        not isinstance(expected_default_branch_sha, str)
        or not SHA_RE.fullmatch(expected_default_branch_sha)
    ):
        failures.append("expected_default_branch_sha_invalid")
    if (
        not isinstance(expected_session_date, str)
        or not DATE_RE.fullmatch(expected_session_date)
    ):
        failures.append("expected_session_date_invalid")
    else:
        try:
            datetime.strptime(expected_session_date, "%Y-%m-%d")
        except ValueError:
            failures.append("expected_session_date_invalid")
    if (
        not isinstance(expected_evidence_run_id, str)
        or not RUN_ID_RE.fullmatch(expected_evidence_run_id)
    ):
        failures.append("expected_evidence_run_id_invalid")
    if (
        not isinstance(expected_evidence_artifact_digest, str)
        or not DIGEST_RE.fullmatch(expected_evidence_artifact_digest)
    ):
        failures.append("expected_evidence_artifact_digest_invalid")
    if type(expected_comment_id) is not int or expected_comment_id <= 0:
        failures.append("expected_comment_id_invalid")

    run_created_at, _ = verify_run_metadata(
        run=run,
        expected_workflow_run_id=expected_workflow_run_id,
        expected_default_branch_sha=expected_default_branch_sha,
        workflow_actor=workflow_actor,
        failures=failures,
    )

    normalized_inputs = normalize_event_inputs(event, failures=failures)
    expected_inputs = expected_dispatch_inputs(
        session_date=expected_session_date,
        evidence_run_id=expected_evidence_run_id,
        evidence_artifact_digest=expected_evidence_artifact_digest,
        comment_id=expected_comment_id,
    )
    if normalized_inputs and normalized_inputs != expected_inputs:
        failures.append("workflow_dispatch_inputs_not_exact_safe_catchup")

    comment_id = comment.get("id")
    if type(comment_id) is not int or comment_id != expected_comment_id:
        failures.append("comment_id_mismatch")
    expected_api_url = (
        f"https://api.github.com/repos/{REPOSITORY}/issues/comments/"
        f"{expected_comment_id}"
    )
    expected_issue_url = (
        f"https://api.github.com/repos/{REPOSITORY}/issues/"
        f"{ANCHOR_ISSUE_NUMBER}"
    )
    expected_html_url = (
        f"https://github.com/{REPOSITORY}/issues/{ANCHOR_ISSUE_NUMBER}"
        f"#issuecomment-{expected_comment_id}"
    )
    if comment.get("url") != expected_api_url:
        failures.append("comment_api_url_mismatch")
    if comment.get("issue_url") != expected_issue_url:
        failures.append("comment_anchor_issue_mismatch")
    if comment.get("html_url") != expected_html_url:
        failures.append("comment_html_url_mismatch")
    exact_user(comment.get("user"), label="comment_author", failures=failures)
    if comment.get("author_association") != "OWNER":
        failures.append("comment_author_association_not_owner")
    if (
        "performed_via_github_app" not in comment
        or comment.get("performed_via_github_app") is not None
    ):
        failures.append("comment_not_direct_owner_authorship")

    created_at = parse_utc(
        comment.get("created_at"),
        label="comment_created_at",
        failures=failures,
    )
    updated_at = parse_utc(
        comment.get("updated_at"),
        label="comment_updated_at",
        failures=failures,
    )
    if comment.get("created_at") != comment.get("updated_at"):
        failures.append("comment_was_edited")

    body = comment.get("body")
    payload: dict[str, Any] = {}
    if not isinstance(body, str):
        failures.append("comment_body_invalid")
    else:
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            failures.append("comment_body_not_json")
        else:
            if not isinstance(parsed, dict):
                failures.append("comment_body_not_object")
            else:
                payload = parsed
                if body != canonical_json(payload):
                    failures.append("comment_body_not_canonical")

    request_nonce = ""
    contract_sha = file_sha256()
    if payload:
        if set(payload) != TOP_LEVEL_KEYS:
            failures.append("attestation_top_level_shape_invalid")
        exact_fields = {
            "schema_version": ATTESTATION_SCHEMA,
            "status": "VERIFIED_ENVIRONMENT_ONLY",
            "source": "OWNER_LOCAL_GH_SCOPE_PREFLIGHT",
            "repository": REPOSITORY,
            "repository_id": REPOSITORY_ID,
            "repository_node_id": REPOSITORY_NODE_ID,
            "environment": ENVIRONMENT_NAME,
            "durable_environment_contract_sha256": contract_sha,
            "anchor_issue_number": ANCHOR_ISSUE_NUMBER,
            "anchor_issue_id": ANCHOR_ISSUE_ID,
            "anchor_issue_node_id": ANCHOR_ISSUE_NODE_ID,
            "session_date": expected_session_date,
            "catchup_price_evidence_run_id": expected_evidence_run_id,
            "catchup_price_evidence_artifact_digest": (
                expected_evidence_artifact_digest
            ),
            "attested_actor": OWNER_LOGIN,
            "attested_actor_id": OWNER_ID,
            "attested_actor_node_id": OWNER_NODE_ID,
        }
        for key, expected in exact_fields.items():
            if payload.get(key) != expected:
                failures.append(f"attestation_{key}_mismatch")
        request_nonce = str(payload.get("request_nonce") or "")
        if not valid_uuid4(request_nonce):
            failures.append("attestation_request_nonce_invalid")
        expected_workflow = {
            "default_branch": DEFAULT_BRANCH,
            "default_branch_sha": expected_default_branch_sha,
            "event": "workflow_dispatch",
            "path": WORKFLOW_PATH,
            "ref": f"refs/heads/{DEFAULT_BRANCH}",
            "workflow_id": WORKFLOW_ID,
            "workflow_node_id": WORKFLOW_NODE_ID,
        }
        if payload.get("workflow") != expected_workflow:
            failures.append("attestation_workflow_identity_mismatch")
        attested_inputs = payload.get("dispatch_inputs")
        expected_attested_inputs = {
            key: expected_inputs[key]
            for key in ATTESTED_DISPATCH_INPUT_KEYS
        }
        if (
            not isinstance(attested_inputs, dict)
            or set(attested_inputs) != ATTESTED_DISPATCH_INPUT_KEYS
        ):
            failures.append("attestation_dispatch_inputs_shape_invalid")
        elif attested_inputs != expected_attested_inputs:
            failures.append("attestation_dispatch_inputs_mismatch")
        scope = payload.get("scope")
        if not isinstance(scope, dict) or set(scope) != SCOPE_KEYS:
            failures.append("attestation_scope_shape_invalid")
        elif scope != EXPECTED_SCOPE:
            failures.append("attestation_scope_not_verified")
        if payload.get("authorization") != EXPECTED_AUTHORIZATION:
            failures.append("attestation_authorization_invalid")

    checked_at = parse_utc(
        payload.get("checked_at"),
        label="attestation_checked_at",
        failures=failures,
    )
    expires_at = parse_utc(
        payload.get("expires_at"),
        label="attestation_expires_at",
        failures=failures,
    )
    if checked_at is not None and expires_at is not None:
        ttl = (expires_at - checked_at).total_seconds()
        if ttl < 60 or ttl > MAX_TTL_SECONDS:
            failures.append("attestation_ttl_invalid")
        # The owner comment authorizes run creation only. After an accepted
        # initial check, the immutable comment is tied to one run/attempt and
        # governed by the separate 60-minute run lease below.
        if prior_verification is None and now > expires_at:
            failures.append("attestation_expired")
        if now < checked_at - timedelta(seconds=MAX_CLOCK_SKEW_SECONDS):
            failures.append("attestation_checked_at_in_future")
    if created_at is not None:
        if now < created_at - timedelta(seconds=MAX_CLOCK_SKEW_SECONDS):
            failures.append("comment_created_at_in_future")
        if (
            prior_verification is None
            and now - created_at > timedelta(seconds=MAX_TTL_SECONDS)
        ):
            failures.append("comment_too_old")
    if checked_at is not None and created_at is not None:
        if created_at < checked_at - timedelta(
            seconds=MAX_CLOCK_SKEW_SECONDS
        ):
            failures.append("comment_predates_scope_check")
        if created_at > checked_at + timedelta(
            seconds=MAX_POST_DELAY_SECONDS
        ):
            failures.append("comment_posted_too_late")
    if created_at is not None and updated_at is not None:
        if updated_at != created_at:
            failures.append("comment_was_edited")
    if run_created_at is not None and created_at is not None:
        if run_created_at < created_at:
            failures.append("workflow_run_predates_attestation_comment")
        if (
            expires_at is not None
            and run_created_at > expires_at
        ):
            failures.append("workflow_run_created_after_attestation_expiry")
    run_lease_expires_at = (
        run_created_at + timedelta(seconds=MAX_RUN_LEASE_SECONDS)
        if run_created_at is not None
        else None
    )
    if run_lease_expires_at is not None and now > run_lease_expires_at:
        failures.append("workflow_run_lease_expired")

    body_sha256 = (
        hashlib.sha256(body.encode("utf-8")).hexdigest()
        if isinstance(body, str)
        else ""
    )
    dispatch_inputs_sha256 = hashlib.sha256(
        canonical_json(normalized_inputs).encode("utf-8")
    ).hexdigest()
    immutable_evidence = {
        "comment_id": expected_comment_id,
        "comment_body_sha256": body_sha256,
        "comment_created_at": (
            utc_text(created_at) if created_at is not None else ""
        ),
        "comment_updated_at": (
            utc_text(updated_at) if updated_at is not None else ""
        ),
        "request_nonce": request_nonce,
        "attestation_expires_at": (
            utc_text(expires_at) if expires_at is not None else ""
        ),
        "durable_environment_contract_sha256": contract_sha,
        "workflow_run_id": expected_workflow_run_id,
        "workflow_run_attempt": 1,
        "workflow_run_created_at": (
            utc_text(run_created_at)
            if run_created_at is not None
            else ""
        ),
        "workflow_run_lease_expires_at": (
            utc_text(run_lease_expires_at)
            if run_lease_expires_at is not None
            else ""
        ),
        "default_branch_sha": expected_default_branch_sha,
        "session_date": expected_session_date,
        "catchup_price_evidence_run_id": expected_evidence_run_id,
        "catchup_price_evidence_artifact_digest": (
            expected_evidence_artifact_digest
        ),
        "dispatch_inputs_sha256": dispatch_inputs_sha256,
    }
    if prior_verification is not None:
        if (
            prior_verification.get("schema_version")
            != VERIFICATION_SCHEMA
            or prior_verification.get("allowed") is not True
            or prior_verification.get("status")
            != "VERIFIED_OWNER_SCOPE_ATTESTATION"
            or prior_verification.get("verification_phase") != "INITIAL"
            or prior_verification.get("failures") != []
        ):
            failures.append("prior_scope_verification_invalid")
        for key, expected in immutable_evidence.items():
            if prior_verification.get(key) != expected:
                failures.append(f"prior_scope_{key}_mismatch")

    failures = sorted(set(failures))
    allowed = not failures
    phase = "REVERIFICATION" if prior_verification is not None else "INITIAL"
    github_env_updates: dict[str, str] = {}
    if allowed:
        if phase == "INITIAL":
            github_env_updates["RUN287_DURABLE_SCOPE_VERIFIED"] = "yes"
        else:
            github_env_updates[
                "RUN287_DURABLE_SCOPE_REVERIFIED"
            ] = "yes"
    return {
        "schema_version": VERIFICATION_SCHEMA,
        "status": (
            "VERIFIED_OWNER_SCOPE_ATTESTATION"
            if allowed
            else "BLOCKED_SCOPE_ATTESTATION"
        ),
        "verification_phase": phase,
        "allowed": allowed,
        "repository": expected_repository,
        "environment": ENVIRONMENT_NAME,
        "anchor_issue_number": ANCHOR_ISSUE_NUMBER,
        **immutable_evidence,
        "verified_at": utc_text(now),
        "failures": failures,
        "github_env_updates": github_env_updates,
    }


def read_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"unable to read {label} JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} JSON must be an object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comment", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--event", type=Path, required=True)
    parser.add_argument("--prior-verification", type=Path)
    parser.add_argument("--expected-comment-id", type=int, required=True)
    parser.add_argument("--expected-repository", required=True)
    parser.add_argument("--expected-default-branch", required=True)
    parser.add_argument("--expected-default-branch-sha", required=True)
    parser.add_argument("--expected-session-date", required=True)
    parser.add_argument("--expected-evidence-run-id", required=True)
    parser.add_argument(
        "--expected-evidence-artifact-digest",
        required=True,
    )
    parser.add_argument("--expected-workflow-run-id", required=True)
    parser.add_argument("--workflow-actor", required=True)
    parser.add_argument("--now", default="")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--github-env", default="")
    args = parser.parse_args()

    if args.now:
        now_failures: list[str] = []
        parsed_now = parse_utc(
            args.now,
            label="verification_now",
            failures=now_failures,
        )
        if parsed_now is None:
            parser.error("--now must use UTC YYYY-MM-DDTHH:MM:SSZ")
        now = parsed_now
    else:
        now = datetime.now(timezone.utc)

    try:
        comment = read_json_object(args.comment, "comment")
        run = read_json_object(args.run, "run")
        event = read_json_object(args.event, "event")
        prior = (
            read_json_object(
                args.prior_verification,
                "prior verification",
            )
            if args.prior_verification
            else None
        )
    except ValueError as exc:
        parser.error(str(exc))

    result = verify_attestation_comment(
        comment=comment,
        run=run,
        event=event,
        expected_comment_id=args.expected_comment_id,
        expected_repository=args.expected_repository,
        expected_default_branch=args.expected_default_branch,
        expected_default_branch_sha=args.expected_default_branch_sha,
        expected_session_date=args.expected_session_date,
        expected_evidence_run_id=args.expected_evidence_run_id,
        expected_evidence_artifact_digest=(
            args.expected_evidence_artifact_digest
        ),
        expected_workflow_run_id=args.expected_workflow_run_id,
        workflow_actor=args.workflow_actor,
        now=now,
        prior_verification=prior,
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
