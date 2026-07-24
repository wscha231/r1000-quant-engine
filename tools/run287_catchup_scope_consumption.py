#!/usr/bin/env python3
"""Prepare and verify a one-time GitHub audit record for a scope attestation."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

if __package__:
    from .verify_run287_catchup_scope_attestation import (
        ANCHOR_ISSUE_NUMBER,
        DEFAULT_BRANCH,
        OWNER_LOGIN,
        REPOSITORY,
        VERIFICATION_SCHEMA,
        WORKFLOW_ID,
        WORKFLOW_PATH,
        append_github_env,
        canonical_json,
        parse_utc,
        read_json_object,
        utc_text,
    )
else:
    from verify_run287_catchup_scope_attestation import (
        ANCHOR_ISSUE_NUMBER,
        DEFAULT_BRANCH,
        OWNER_LOGIN,
        REPOSITORY,
        VERIFICATION_SCHEMA,
        WORKFLOW_ID,
        WORKFLOW_PATH,
        append_github_env,
        canonical_json,
        parse_utc,
        read_json_object,
        utc_text,
    )


CONSUMPTION_SCHEMA = "run287-durable-scope-consumption-v1"
RECEIPT_SCHEMA = "run287-durable-scope-consumption-receipt-v1"
GITHUB_ACTIONS_BOT_LOGIN = "github-actions[bot]"
GITHUB_ACTIONS_BOT_ID = 41898282
GITHUB_ACTIONS_BOT_NODE_ID = "MDM6Qm90NDE4OTgyODI="
MAX_POST_DELAY_SECONDS = 120
RECORD_KEYS = {
    "anchor_issue_number",
    "attestation_body_sha256",
    "attestation_comment_id",
    "catchup_price_evidence_artifact_digest",
    "catchup_price_evidence_run_id",
    "consumed_at",
    "default_branch",
    "default_branch_sha",
    "dispatch_inputs_sha256",
    "repository",
    "request_nonce",
    "schema_version",
    "session_date",
    "status",
    "workflow_id",
    "workflow_path",
    "workflow_run_attempt",
    "workflow_run_created_at",
    "workflow_run_id",
    "workflow_run_lease_expires_at",
}


def flatten_comment_pages(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("issue comment inventory must be an array")
    flattened: list[dict[str, Any]] = []
    for item in value:
        rows = item if isinstance(item, list) else [item]
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("issue comment inventory row is invalid")
            flattened.append(row)
    return flattened


def require_initial_verification(
    verification: dict[str, Any],
) -> None:
    if (
        verification.get("schema_version") != VERIFICATION_SCHEMA
        or verification.get("status")
        != "VERIFIED_OWNER_SCOPE_ATTESTATION"
        or verification.get("verification_phase") != "INITIAL"
        or verification.get("allowed") is not True
        or verification.get("failures") != []
    ):
        raise ValueError("initial owner scope verification is not accepted")


def is_exact_actions_bot(value: Any) -> bool:
    return isinstance(value, dict) and {
        "login": value.get("login"),
        "id": value.get("id"),
        "node_id": value.get("node_id"),
        "type": value.get("type"),
    } == {
        "login": GITHUB_ACTIONS_BOT_LOGIN,
        "id": GITHUB_ACTIONS_BOT_ID,
        "node_id": GITHUB_ACTIONS_BOT_NODE_ID,
        "type": "Bot",
    }


def find_consumption_claims(
    comments: list[dict[str, Any]],
    *,
    verification: dict[str, Any],
) -> list[int]:
    attestation_comment_id = verification.get("comment_id")
    request_nonce = verification.get("request_nonce")
    claims: list[int] = []
    for comment in comments:
        body = comment.get("body")
        if not isinstance(body, str):
            continue
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        if payload.get("schema_version") != CONSUMPTION_SCHEMA:
            continue
        if (
            payload.get("attestation_comment_id")
            == attestation_comment_id
            or payload.get("request_nonce") == request_nonce
        ):
            # Foreign users cannot reserve a public nonce or pre-consume an
            # owner attestation. Only a strict canonical Actions-bot record
            # emitted by this serialized workflow is authoritative.
            if not is_exact_actions_bot(comment.get("user")):
                continue
            expected_static = {
                "schema_version": CONSUMPTION_SCHEMA,
                "status": "CONSUMED_ONCE",
                "repository": REPOSITORY,
                "anchor_issue_number": ANCHOR_ISSUE_NUMBER,
                "attestation_comment_id": attestation_comment_id,
                "attestation_body_sha256": verification.get(
                    "comment_body_sha256"
                ),
                "request_nonce": request_nonce,
                "workflow_id": WORKFLOW_ID,
                "workflow_path": WORKFLOW_PATH,
                "workflow_run_attempt": 1,
                "workflow_run_created_at": verification.get(
                    "workflow_run_created_at"
                ),
                "default_branch": DEFAULT_BRANCH,
                "default_branch_sha": verification.get(
                    "default_branch_sha"
                ),
                "session_date": verification.get("session_date"),
                "catchup_price_evidence_run_id": verification.get(
                    "catchup_price_evidence_run_id"
                ),
                "catchup_price_evidence_artifact_digest": verification.get(
                    "catchup_price_evidence_artifact_digest"
                ),
                "dispatch_inputs_sha256": verification.get(
                    "dispatch_inputs_sha256"
                ),
                "workflow_run_lease_expires_at": verification.get(
                    "workflow_run_lease_expires_at"
                ),
            }
            malformed = (
                set(payload) != RECORD_KEYS
                or comment.get("issue_url")
                != (
                    f"https://api.github.com/repos/{REPOSITORY}/issues/"
                    f"{ANCHOR_ISSUE_NUMBER}"
                )
                or comment.get("created_at") != comment.get("updated_at")
                or body != canonical_json(payload)
                or type(payload.get("workflow_run_id")) is not int
                or payload.get("workflow_run_id", 0) <= 0
                or not isinstance(payload.get("consumed_at"), str)
                or any(
                    payload.get(key) != value
                    for key, value in expected_static.items()
                )
            )
            if malformed:
                raise ValueError(
                    "malformed Actions-bot consumption claim"
                )
            comment_id = comment.get("id")
            if type(comment_id) is not int or comment_id <= 0:
                raise ValueError(
                    "Actions-bot consumption claim id is invalid"
                )
            claims.append(comment_id)
    return claims


def build_consumption_record(
    *,
    verification: dict[str, Any],
    run: dict[str, Any],
    existing_comments: list[dict[str, Any]],
    now: datetime,
) -> dict[str, Any]:
    require_initial_verification(verification)
    comment_id = verification.get("comment_id")
    request_nonce = verification.get("request_nonce")
    if type(comment_id) is not int or comment_id <= 0:
        raise ValueError("verified attestation comment id is invalid")
    if not isinstance(request_nonce, str) or not request_nonce:
        raise ValueError("verified request nonce is invalid")
    claims = find_consumption_claims(
        existing_comments,
        verification=verification,
    )
    if claims:
        raise ValueError(
            "scope attestation already has a consumption claim"
        )
    if (
        run.get("id") != int(verification["workflow_run_id"])
        or run.get("run_attempt") != 1
        or run.get("event") != "workflow_dispatch"
        or run.get("head_sha") != verification["default_branch_sha"]
        or run.get("head_branch") != DEFAULT_BRANCH
        or run.get("path") != WORKFLOW_PATH
        or run.get("workflow_id") != WORKFLOW_ID
    ):
        raise ValueError("workflow run does not match verified attestation")

    expiry_failures: list[str] = []
    expires_at = parse_utc(
        verification.get("attestation_expires_at"),
        label="attestation_expires_at",
        failures=expiry_failures,
    )
    now = now.astimezone(timezone.utc).replace(microsecond=0)
    if expires_at is None or expiry_failures or now > expires_at:
        raise ValueError("scope attestation expired before consumption")
    lease_failures: list[str] = []
    run_lease_expires_at = parse_utc(
        verification.get("workflow_run_lease_expires_at"),
        label="workflow_run_lease_expires_at",
        failures=lease_failures,
    )
    if (
        run_lease_expires_at is None
        or lease_failures
        or now > run_lease_expires_at
    ):
        raise ValueError("workflow run lease expired before consumption")
    return {
        "schema_version": CONSUMPTION_SCHEMA,
        "status": "CONSUMED_ONCE",
        "repository": REPOSITORY,
        "anchor_issue_number": ANCHOR_ISSUE_NUMBER,
        "attestation_comment_id": comment_id,
        "attestation_body_sha256": verification[
            "comment_body_sha256"
        ],
        "request_nonce": request_nonce,
        "workflow_id": WORKFLOW_ID,
        "workflow_path": WORKFLOW_PATH,
        "workflow_run_id": run["id"],
        "workflow_run_attempt": 1,
        "workflow_run_created_at": verification[
            "workflow_run_created_at"
        ],
        "workflow_run_lease_expires_at": verification[
            "workflow_run_lease_expires_at"
        ],
        "default_branch": DEFAULT_BRANCH,
        "default_branch_sha": verification["default_branch_sha"],
        "session_date": verification["session_date"],
        "catchup_price_evidence_run_id": verification[
            "catchup_price_evidence_run_id"
        ],
        "catchup_price_evidence_artifact_digest": verification[
            "catchup_price_evidence_artifact_digest"
        ],
        "dispatch_inputs_sha256": verification[
            "dispatch_inputs_sha256"
        ],
        "consumed_at": utc_text(now),
    }


def exact_actions_bot(value: Any, failures: list[str]) -> None:
    if not isinstance(value, dict):
        failures.append("consumption_author_invalid")
        return
    expected = {
        "login": GITHUB_ACTIONS_BOT_LOGIN,
        "id": GITHUB_ACTIONS_BOT_ID,
        "node_id": GITHUB_ACTIONS_BOT_NODE_ID,
        "type": "Bot",
    }
    for key, expected_value in expected.items():
        if value.get(key) != expected_value:
            failures.append(f"consumption_author_{key}_mismatch")


def verify_consumption_comment(
    *,
    comment: dict[str, Any],
    expected_record: dict[str, Any],
    verification: dict[str, Any],
    run: dict[str, Any],
    now: datetime,
    prior_receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    failures: list[str] = []
    try:
        require_initial_verification(verification)
    except ValueError:
        failures.append("initial_scope_verification_invalid")
    if (
        set(expected_record) != RECORD_KEYS
        or expected_record.get("schema_version") != CONSUMPTION_SCHEMA
        or expected_record.get("status") != "CONSUMED_ONCE"
    ):
        failures.append("expected_consumption_record_invalid")
    if (
        expected_record.get("workflow_run_id") != run.get("id")
        or expected_record.get("workflow_run_attempt")
        != run.get("run_attempt")
        or expected_record.get("workflow_run_created_at")
        != verification.get("workflow_run_created_at")
        or expected_record.get("workflow_run_lease_expires_at")
        != verification.get("workflow_run_lease_expires_at")
        or expected_record.get("attestation_comment_id")
        != verification.get("comment_id")
        or expected_record.get("attestation_body_sha256")
        != verification.get("comment_body_sha256")
        or expected_record.get("request_nonce")
        != verification.get("request_nonce")
    ):
        failures.append("consumption_record_binding_mismatch")

    comment_id = comment.get("id")
    if type(comment_id) is not int or comment_id <= 0:
        failures.append("consumption_comment_id_invalid")
        comment_id = 0
    expected_api_url = (
        f"https://api.github.com/repos/{REPOSITORY}/issues/comments/"
        f"{comment_id}"
    )
    expected_issue_url = (
        f"https://api.github.com/repos/{REPOSITORY}/issues/"
        f"{ANCHOR_ISSUE_NUMBER}"
    )
    expected_html_url = (
        f"https://github.com/{REPOSITORY}/issues/{ANCHOR_ISSUE_NUMBER}"
        f"#issuecomment-{comment_id}"
    )
    if comment.get("url") != expected_api_url:
        failures.append("consumption_comment_api_url_mismatch")
    if comment.get("issue_url") != expected_issue_url:
        failures.append("consumption_comment_anchor_issue_mismatch")
    if comment.get("html_url") != expected_html_url:
        failures.append("consumption_comment_html_url_mismatch")
    exact_actions_bot(comment.get("user"), failures)
    if comment.get("created_at") != comment.get("updated_at"):
        failures.append("consumption_comment_was_edited")

    created_at = parse_utc(
        comment.get("created_at"),
        label="consumption_comment_created_at",
        failures=failures,
    )
    updated_at = parse_utc(
        comment.get("updated_at"),
        label="consumption_comment_updated_at",
        failures=failures,
    )
    consumed_at = parse_utc(
        expected_record.get("consumed_at"),
        label="consumption_record_consumed_at",
        failures=failures,
    )
    run_lease_expires_at = parse_utc(
        expected_record.get("workflow_run_lease_expires_at"),
        label="workflow_run_lease_expires_at",
        failures=failures,
    )
    now = now.astimezone(timezone.utc)
    if created_at is not None and consumed_at is not None:
        if created_at < consumed_at - timedelta(seconds=60):
            failures.append("consumption_comment_predates_record")
        if created_at > consumed_at + timedelta(
            seconds=MAX_POST_DELAY_SECONDS
        ):
            failures.append("consumption_comment_posted_too_late")
        if now < created_at - timedelta(seconds=60):
            failures.append("consumption_comment_created_in_future")
    if (
        run_lease_expires_at is not None
        and now > run_lease_expires_at
    ):
        failures.append("workflow_run_lease_expired")
    if created_at is not None and updated_at is not None:
        if created_at != updated_at:
            failures.append("consumption_comment_was_edited")

    body = comment.get("body")
    if not isinstance(body, str):
        failures.append("consumption_comment_body_invalid")
        body_sha256 = ""
    else:
        body_sha256 = hashlib.sha256(body.encode("utf-8")).hexdigest()
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            failures.append("consumption_comment_body_not_json")
        else:
            if not isinstance(payload, dict):
                failures.append("consumption_comment_body_not_object")
            elif (
                body != canonical_json(payload)
                or payload != expected_record
            ):
                failures.append("consumption_comment_record_mismatch")

    immutable_receipt = {
        "attestation_comment_id": verification.get("comment_id"),
        "attestation_body_sha256": verification.get(
            "comment_body_sha256"
        ),
        "request_nonce": verification.get("request_nonce"),
        "consumption_comment_id": comment_id,
        "consumption_comment_body_sha256": body_sha256,
        "workflow_run_id": verification.get("workflow_run_id"),
        "workflow_run_attempt": 1,
    }
    if prior_receipt is not None:
        if (
            prior_receipt.get("schema_version") != RECEIPT_SCHEMA
            or prior_receipt.get("status") != "CONSUMPTION_RECORDED"
            or prior_receipt.get("verification_phase") != "INITIAL"
            or prior_receipt.get("allowed") is not True
            or prior_receipt.get("failures") != []
        ):
            failures.append("prior_consumption_receipt_invalid")
        for key, expected in immutable_receipt.items():
            if prior_receipt.get(key) != expected:
                failures.append(f"prior_consumption_{key}_mismatch")

    failures = sorted(set(failures))
    allowed = not failures
    phase = "REVERIFICATION" if prior_receipt is not None else "INITIAL"
    updates: dict[str, str] = {}
    if allowed and phase == "INITIAL":
        updates = {
            "RUN287_DURABLE_SCOPE_CONSUMED": "yes",
            "RUN287_DURABLE_SCOPE_CONSUMPTION_COMMENT_ID": str(
                comment_id
            ),
        }
    elif allowed:
        updates = {
            "RUN287_DURABLE_SCOPE_CONSUMPTION_REVERIFIED": "yes"
        }
    return {
        "schema_version": RECEIPT_SCHEMA,
        "status": (
            "CONSUMPTION_RECORDED"
            if allowed
            else "BLOCKED_CONSUMPTION_RECORD"
        ),
        "verification_phase": phase,
        "allowed": allowed,
        **immutable_receipt,
        "verified_at": utc_text(now),
        "failures": failures,
        "github_env_updates": updates,
    }


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def parse_now(value: str) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    failures: list[str] = []
    parsed = parse_utc(value, label="now", failures=failures)
    if parsed is None:
        raise ValueError("--now must use UTC YYYY-MM-DDTHH:MM:SSZ")
    return parsed


def prepare(args: argparse.Namespace) -> int:
    try:
        verification = read_json_object(
            args.verification,
            "verification",
        )
        run = read_json_object(args.run, "run")
        inventory = json.loads(
            args.existing_comments.read_text(encoding="utf-8")
        )
        comments = flatten_comment_pages(inventory)
        record = build_consumption_record(
            verification=verification,
            run=run,
            existing_comments=comments,
            now=parse_now(args.now),
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"[run287-scope-consumption] BLOCKED: {exc}")
        return 2
    write_json(args.record_output, record)
    write_json(
        args.request_output,
        {"body": canonical_json(record)},
    )
    print(
        json.dumps(
            {
                "status": "READY_TO_RECORD_CONSUMPTION",
                "attestation_comment_id": record[
                    "attestation_comment_id"
                ],
                "workflow_run_id": record["workflow_run_id"],
            },
            sort_keys=True,
        )
    )
    return 0


def verify(args: argparse.Namespace) -> int:
    try:
        result = verify_consumption_comment(
            comment=read_json_object(args.comment, "comment"),
            expected_record=read_json_object(
                args.expected_record,
                "expected record",
            ),
            verification=read_json_object(
                args.verification,
                "verification",
            ),
            run=read_json_object(args.run, "run"),
            now=parse_now(args.now),
            prior_receipt=(
                read_json_object(
                    args.prior_receipt,
                    "prior receipt",
                )
                if args.prior_receipt
                else None
            ),
        )
    except ValueError as exc:
        print(f"[run287-scope-consumption] BLOCKED: {exc}")
        return 2
    write_json(args.output, result)
    append_github_env(args.github_env, result["github_env_updates"])
    print(json.dumps(result, sort_keys=True))
    return 0 if result["allowed"] else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--verification", type=Path, required=True)
    prepare_parser.add_argument("--run", type=Path, required=True)
    prepare_parser.add_argument(
        "--existing-comments",
        type=Path,
        required=True,
    )
    prepare_parser.add_argument("--now", default="")
    prepare_parser.add_argument(
        "--record-output",
        type=Path,
        required=True,
    )
    prepare_parser.add_argument(
        "--request-output",
        type=Path,
        required=True,
    )
    prepare_parser.set_defaults(handler=prepare)

    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--comment", type=Path, required=True)
    verify_parser.add_argument(
        "--expected-record",
        type=Path,
        required=True,
    )
    verify_parser.add_argument(
        "--verification",
        type=Path,
        required=True,
    )
    verify_parser.add_argument("--run", type=Path, required=True)
    verify_parser.add_argument("--prior-receipt", type=Path)
    verify_parser.add_argument("--now", default="")
    verify_parser.add_argument("--output", type=Path, required=True)
    verify_parser.add_argument("--github-env", default="")
    verify_parser.set_defaults(handler=verify)

    args = parser.parse_args()
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
