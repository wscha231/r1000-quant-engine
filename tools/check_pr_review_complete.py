#!/usr/bin/env python3
"""Fail-closed evaluator for the Run287 Codex review-complete merge gate.

The GitHub workflow collects trusted API payloads and this module decides
whether the current pull-request head has independent Codex review evidence.
It deliberately does not inspect or execute code from the pull-request head.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "run287-review-complete-gate-v2"
PASS_STATUS = "PASS_REVIEW_COMPLETE"
BLOCKED_STATUS = "BLOCKED_REVIEW_INCOMPLETE"
DEFAULT_REVIEWERS = {
    "chatgpt-codex-connector",
    "chatgpt-codex-connector[bot]",
}
ACCEPTED_REVIEW_STATES = {"APPROVED", "COMMENTED"}
WRITE_PERMISSIONS = {"admin", "maintain", "write"}


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def flatten_records(value: Any) -> list[dict[str, Any]]:
    """Flatten gh --paginate --slurp payloads without accepting scalars."""

    rows: list[dict[str, Any]] = []
    if isinstance(value, dict):
        rows.append(value)
    elif isinstance(value, list):
        for item in value:
            rows.extend(flatten_records(item))
    return rows


def login(record: dict[str, Any]) -> str:
    user = record.get("user")
    if not isinstance(user, dict):
        return ""
    return str(user.get("login") or "").strip().lower()


def parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def exact_head_reviews(
    reviews: Iterable[dict[str, Any]],
    *,
    head_sha: str,
    head_observed_at: datetime,
    attested_at: datetime,
    reviewers: set[str],
) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    for review in reviews:
        if login(review) not in reviewers:
            continue
        if str(review.get("state") or "").upper() not in ACCEPTED_REVIEW_STATES:
            continue
        if str(review.get("commit_id") or "").lower() != head_sha:
            continue
        submitted_at = parse_time(review.get("submitted_at"))
        if submitted_at is None:
            continue
        if submitted_at < head_observed_at or submitted_at > attested_at:
            continue
        matched.append(review)
    return matched


def fresh_clean_reactions(
    reactions: Iterable[dict[str, Any]],
    *,
    head_observed_at: datetime,
    attested_at: datetime,
    reviewers: set[str],
) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    for reaction in reactions:
        if login(reaction) not in reviewers:
            continue
        if str(reaction.get("content") or "") != "+1":
            continue
        created_at = parse_time(reaction.get("created_at"))
        if created_at is None:
            continue
        if created_at < head_observed_at or created_at > attested_at:
            continue
        matched.append(reaction)
    return matched


def evaluate(
    *,
    pull_request: dict[str, Any],
    head_observation: dict[str, Any],
    attestation: dict[str, Any] | None,
    reviews: list[dict[str, Any]],
    reactions: list[dict[str, Any]],
    reviewers: set[str] | None = None,
) -> dict[str, Any]:
    allowed = {value.lower() for value in (reviewers or DEFAULT_REVIEWERS)}
    head = pull_request.get("head")
    head_sha = str(head.get("sha") if isinstance(head, dict) else "").strip().lower()
    failures: list[str] = []
    if len(head_sha) != 40:
        failures.append("missing_or_invalid_head_sha")
    if bool(pull_request.get("draft")):
        failures.append("pull_request_is_draft")

    observed_sha = str(head_observation.get("head_sha") or "").strip().lower()
    observed_at = parse_time(head_observation.get("observed_at"))
    if observed_sha != head_sha:
        failures.append("head_observation_sha_mismatch")
    if observed_at is None:
        failures.append("missing_head_observation_timestamp")

    attestation = attestation if isinstance(attestation, dict) else {}
    attested_sha = str(attestation.get("head_sha") or "").strip().lower()
    attested_at = parse_time(attestation.get("created_at"))
    attestor_permission = str(attestation.get("permission") or "").strip().lower()
    attestor = str(attestation.get("actor") or "").strip()
    if not attestation:
        failures.append("missing_maintainer_attestation")
    else:
        if attested_sha != head_sha:
            failures.append("attestation_sha_mismatch")
        if attested_at is None:
            failures.append("missing_attestation_timestamp")
        if attestor_permission not in WRITE_PERMISSIONS:
            failures.append("attestor_lacks_write_permission")
        if not attestor:
            failures.append("missing_attestor")
        if observed_at is not None and attested_at is not None and attested_at < observed_at:
            failures.append("attestation_predates_head_observation")

    exact_reviews = exact_head_reviews(
        reviews,
        head_sha=head_sha,
        head_observed_at=observed_at,
        attested_at=attested_at,
        reviewers=allowed,
    ) if head_sha and observed_at is not None and attested_at is not None else []
    clean_reactions = fresh_clean_reactions(
        reactions,
        head_observed_at=observed_at,
        attested_at=attested_at,
        reviewers=allowed,
    ) if observed_at is not None and attested_at is not None else []

    evidence_type = ""
    evidence_id: int | str | None = None
    evidence_at = ""
    if exact_reviews:
        selected = max(
            exact_reviews,
            key=lambda row: parse_time(row.get("submitted_at")) or datetime.min.replace(tzinfo=timezone.utc),
        )
        evidence_type = "ATTESTED_EXACT_HEAD_REVIEW"
        evidence_id = selected.get("id")
        evidence_at = str(selected.get("submitted_at") or "")
    elif clean_reactions:
        selected = max(
            clean_reactions,
            key=lambda row: parse_time(row.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc),
        )
        evidence_type = "MAINTAINER_BOUND_CLEAN_REACTION"
        evidence_id = selected.get("id")
        evidence_at = str(selected.get("created_at") or "")
    else:
        failures.append("no_codex_evidence_for_current_head")

    passed = not failures
    return {
        "schema_version": SCHEMA_VERSION,
        "status": PASS_STATUS if passed else BLOCKED_STATUS,
        "passed": passed,
        "pull_request_number": pull_request.get("number"),
        "head_sha": head_sha,
        "head_observed_at": observed_at.isoformat() if observed_at else None,
        "head_observation_check_run_id": head_observation.get("check_run_id"),
        "attestor": attestor or None,
        "attestor_permission": attestor_permission or None,
        "attested_at": attested_at.isoformat() if attested_at else None,
        "attestation_source": attestation.get("source") or None,
        "accepted_reviewer_logins": sorted(allowed),
        "evidence_type": evidence_type or None,
        "evidence_id": evidence_id,
        "evidence_at": evidence_at or None,
        "exact_head_review_count": len(exact_reviews),
        "fresh_clean_reaction_count": len(clean_reactions),
        "failures": sorted(set(failures)),
        "unresolved_conversations_checked_by": "github_branch_protection",
        "automatic_merge_authorized": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "fullrun_executed": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pull-request", required=True)
    parser.add_argument("--head-observation", required=True)
    parser.add_argument("--attestation")
    parser.add_argument("--reviews", required=True)
    parser.add_argument("--reactions", required=True)
    parser.add_argument("--reviewer", action="append", default=[])
    parser.add_argument("--output")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = evaluate(
        pull_request=read_json(args.pull_request),
        head_observation=read_json(args.head_observation),
        attestation=read_json(args.attestation) if args.attestation else None,
        reviews=flatten_records(read_json(args.reviews)),
        reactions=flatten_records(read_json(args.reactions)),
        reviewers=set(args.reviewer) if args.reviewer else None,
    )
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        destination = Path(args.output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if payload["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
