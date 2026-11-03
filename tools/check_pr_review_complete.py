#!/usr/bin/env python3
"""Fail-closed evaluator for the Run287 Codex review-complete merge gate.

The GitHub workflow collects trusted API payloads and this module decides
whether the current pull-request head has independent Codex review evidence.
It deliberately does not inspect or execute code from the pull-request head.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
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
COMMENT_EVIDENCE = "MAINTAINER_BOUND_CLEAN_ISSUE_COMMENT_RECEIPT"
TRUSTED_BOT_ID = 199175422
TRUSTED_APP_ID = 1144995
TRUSTED_APP_SLUG = "chatgpt-codex-connector"
CODEX_ABOUT_DETAILS = '''<details> <summary>ℹ️ About Codex in GitHub</summary>
<br/>
[Your team has set up Codex to review pull requests in this repo](https://chatgpt.com/codex/cloud/settings/general). Reviews are triggered when you
- Open a pull request for review
- Mark a draft as ready
- Comment "@codex review".
If Codex has suggestions, it will comment; otherwise it will react with 👍.
Codex can also answer questions or update the PR. Try commenting "@codex address that feedback".
</details>'''


def _latest_unique(rows: list[dict], reason: str) -> dict:
    latest_at = max(_comment_time(row["updated_at"]) for row in rows)
    latest = [row for row in rows if _comment_time(row["updated_at"]) == latest_at]
    if len(latest) != 1:
        raise ValueError(reason)
    return latest[0]


def _normalized_details(value: str) -> str:
    return " ".join(re.sub(r">\s*<", "><", value).split())


def _comment_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", value
    ):
        return None
    return parse_time(value)


def _trusted_comment(row: dict, repository: str, number: int) -> bool:
    user, app = row.get("user"), row.get("performed_via_github_app")
    return (isinstance(user, dict) and user.get("login") == "chatgpt-codex-connector[bot]"
        and type(user.get("id")) is int and user["id"] == TRUSTED_BOT_ID and user.get("type") == "Bot"
        and isinstance(app, dict) and type(app.get("id")) is int and app["id"] == TRUSTED_APP_ID
        and app.get("slug") == TRUSTED_APP_SLUG and type(row.get("id")) is int and row["id"] > 0
        and row.get("issue_url") == f"https://api.github.com/repos/{repository}/issues/{number}"
        and isinstance(row.get("body"), str) and len(row["body"].encode()) <= 65536)


def _summary_state(body: str) -> dict | None:
    if body.count("<!-- codex-pull-request-review-summary -->") != 1:
        return None
    markers = re.findall(r"<!-- codex-review-state:v1 (.*?) -->", body)
    if len(markers) != 1:
        return None
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate summary key")
            result[key] = value
        return result
    try:
        state = json.loads(markers[0], object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite summary")))
        return state if isinstance(state, dict) else None
    except (ValueError, TypeError, RecursionError):
        return None


def _resolved_threads(pages: Any, *, repository: str, number: int, head_sha: str) -> tuple[int, int]:
    if not isinstance(pages, list) or not 0 < len(pages) <= 100:
        raise ValueError("missing_comment_thread_pages")
    ids, cursors, expected_total = set(), set(), None
    for index, page in enumerate(pages):
        if not isinstance(page, dict) or page.get("errors"):
            raise ValueError("invalid_comment_thread_page")
        repo = (page.get("data") or {}).get("repository")
        if not isinstance(repo, dict) or repo.get("nameWithOwner") != repository:
            raise ValueError("comment_thread_repository_mismatch")
        pr = repo.get("pullRequest")
        if (not isinstance(pr, dict) or type(pr.get("number")) is not int or pr["number"] != number
                or pr.get("headRefOid") != head_sha):
            raise ValueError("comment_thread_head_mismatch")
        connection = pr.get("reviewThreads")
        if not isinstance(connection, dict):
            raise ValueError("invalid_comment_thread_page")
        total = connection.get("totalCount")
        if type(total) is not int or not 0 <= total <= 10000 or (expected_total is not None and total != expected_total):
            raise ValueError("invalid_comment_thread_total")
        expected_total = total
        nodes, info = connection.get("nodes"), connection.get("pageInfo")
        if (not isinstance(nodes, list) or len(nodes) > 100 or not isinstance(info, dict)
                or type(info.get("hasNextPage")) is not bool):
            raise ValueError("invalid_comment_thread_page")
        more, cursor = info["hasNextPage"], info.get("endCursor")
        if more != (index < len(pages)-1) or (more and len(nodes) != 100) or (index > 0 and not nodes):
            raise ValueError("incomplete_comment_thread_pages")
        if nodes or more:
            if not isinstance(cursor, str) or not cursor or cursor in cursors:
                raise ValueError("stale_comment_thread_cursor")
            cursors.add(cursor)
        elif cursor is not None:
            raise ValueError("invalid_comment_thread_cursor")
        for node in nodes:
            if (not isinstance(node, dict) or not isinstance(node.get("id"), str) or not node["id"]
                    or node["id"] in ids or type(node.get("isResolved")) is not bool):
                raise ValueError("invalid_comment_thread_node")
            ids.add(node["id"])
            if not node["isResolved"]:
                raise ValueError("unresolved_comment_review_threads")
    if len(ids) != expected_total:
        raise ValueError("incomplete_comment_thread_pages")
    return len(ids), len(pages)


def parse_review_complete_command(body: Any, head_sha: str) -> dict | None:
    """Keep the legacy bare command; pins require one exact unedited line."""
    if isinstance(body, str) and body.strip() == f"/review-complete {head_sha}":
        return None
    match = re.fullmatch(r"/review-complete ([0-9a-f]{40}) codex-receipt ([1-9][0-9]{0,18}) sha256:([0-9a-f]{64})", body) if isinstance(body, str) else None
    if not match or match[1] != head_sha or int(match[2]) > 2**63-1:
        raise ValueError("invalid_pinned_attestation_command")
    return dict(receipt_comment_id=int(match[2]), receipt_body_sha256=match[3])


def _verified_attestation_pin(*, attestation: dict, api_comment: Any, event: Any,
        repository: str, number: int, head_sha: str) -> tuple[dict, dict]:
    """Bind a pin to an actual same-PR maintainer comment, never a free DTO."""
    if (attestation.get("source") != "issue_comment" or not isinstance(api_comment, dict)
            or not isinstance(event, dict) or event.get("action") != "created"
            or attestation.get("permission") not in WRITE_PERMISSIONS):
        raise ValueError("missing_authenticated_pin_comment")
    user, sender, event_comment = api_comment.get("user"), event.get("sender"), event.get("comment")
    issue = event.get("issue")
    if (not isinstance(user, dict) or not isinstance(sender, dict) or not isinstance(event_comment, dict)
            or not isinstance(issue, dict) or type(issue.get("number")) is not int or issue["number"] != number
            or (event.get("repository") or {}).get("full_name") != repository
            or (issue.get("pull_request") or {}).get("url") != f"https://api.github.com/repos/{repository}/pulls/{number}"
            or api_comment.get("issue_url") != f"https://api.github.com/repos/{repository}/issues/{number}"):
        raise ValueError("pin_comment_scope_mismatch")
    if (type(api_comment.get("id")) is not int or api_comment["id"] <= 0
            or type(event_comment.get("id")) is not int
            or type(user.get("id")) is not int or user["id"] <= 0 or user.get("type") != "User"
            or type(sender.get("id")) is not int or sender["id"] != user["id"]
            or not isinstance(user.get("login"), str) or not user["login"]
            or sender.get("login") != user["login"] or attestation.get("actor") != user["login"]
            or type(attestation.get("actor_id")) is not int or attestation["actor_id"] != user["id"]):
        raise ValueError("pin_comment_actor_mismatch")
    for key in ("id", "body", "created_at", "updated_at", "issue_url"):
        if event_comment.get(key) != api_comment.get(key):
            raise ValueError("pin_event_api_comment_mismatch")
    event_user = event_comment.get("user")
    if (not isinstance(event_user, dict) or type(event_user.get("id")) is not int
            or any(event_user.get(key) != user.get(key) for key in ("id", "login", "type"))):
        raise ValueError("pin_event_api_actor_mismatch")
    created = _comment_time(api_comment.get("created_at"))
    if (created is None or api_comment.get("created_at") != api_comment.get("updated_at")
            or api_comment.get("created_at") != attestation.get("created_at")):
        raise ValueError("pin_attestation_not_immutable")
    pin = parse_review_complete_command(api_comment.get("body"), head_sha)
    declared = attestation.get("receipt_pin")
    if (pin is None or not isinstance(declared, dict) or set(declared) != set(pin)
            or type(declared.get("receipt_comment_id")) is not int or declared != pin):
        raise ValueError("pin_attestation_binding_mismatch")
    return pin, dict(schema_version="maintainer-receipt-pin-binding-v1",
        maintainer_comment_id=api_comment["id"], maintainer_comment_body_sha256=hashlib.sha256(api_comment["body"].encode("utf-8")).hexdigest(),
        maintainer_login=user["login"], maintainer_user_id=user["id"], maintainer_created_at=api_comment["created_at"],
        receipt_comment_id=pin["receipt_comment_id"], receipt_body_sha256=pin["receipt_body_sha256"])


def paired_comment_evidence(*, comments: Any, review_comments: Any, thread_pages: Any,
        commit_binding: Any, repository: Any, pull_request: dict, head_sha: str,
        observed_at: datetime, attested_at: datetime, reviews: list[dict], receipt_pin: dict | None = None,
        pin_binding: dict | None = None) -> dict:
    """Only trusted workflow API snapshots may supply this additive evidence."""
    number = pull_request.get("number")
    if (not isinstance(repository, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)
            or type(number) is not int or number <= 0
            or ((pull_request.get("base") or {}).get("repo") or {}).get("full_name") != repository):
        raise ValueError("comment_repository_binding_missing")
    if (not isinstance(commit_binding, dict) or commit_binding.get("repository") != repository
            or commit_binding.get("requested_prefix") != head_sha[:10]
            or commit_binding.get("sha") != head_sha
            or commit_binding.get("url") != f"https://api.github.com/repos/{repository}/commits/{head_sha}"):
        raise ValueError("comment_commit_binding_mismatch")
    if not isinstance(comments, list) or not isinstance(review_comments, list):
        raise ValueError("missing_comment_evidence_snapshot")
    trusted = [row for row in comments if isinstance(row, dict) and _trusted_comment(row, repository, number)]
    summaries = [row for row in trusted if "<!-- codex-pull-request-review-summary -->" in row["body"]]
    if not summaries or any(_comment_time(row.get("updated_at")) is None for row in summaries):
        raise ValueError("missing_or_invalid_codex_summary")
    summary = _latest_unique(summaries, "ambiguous_latest_codex_summary")
    updated, created = _comment_time(summary["updated_at"]), _comment_time(summary.get("created_at"))
    if created is None or not created <= updated or not observed_at <= updated <= attested_at:
        raise ValueError("codex_summary_outside_attestation_window")
    state = _summary_state(summary["body"])
    code = state.get("code_review") if state else None
    def clean_flags(value):
        return all(key in value and (value[key] is None or value[key] is False)
                   for key in ("has_any_findings", "has_unresolved_findings"))
    if (not isinstance(code, dict) or code.get("commit_sha") != head_sha
            or code.get("status") != "completed" or not clean_flags(code)):
        raise ValueError("codex_summary_not_completed_clean_head")
    security = state.get("security_review")
    if isinstance(security, dict) and security.get("commit_sha") == head_sha:
        if security.get("status") != "completed" or not clean_flags(security):
            raise ValueError("codex_security_summary_not_clean")
    receipt_rows = [row for row in trusted if "<!-- codex-review-receipt:v1 -->" in row["body"]]
    if not receipt_rows or any(_comment_time(row.get("updated_at")) is None for row in receipt_rows):
        raise ValueError("missing_immutable_clean_codex_receipt")
    latest_receipt = _latest_unique(receipt_rows, "ambiguous_latest_codex_receipt")
    if receipt_pin is not None:
        if (latest_receipt["id"] != receipt_pin["receipt_comment_id"]
                or hashlib.sha256(latest_receipt["body"].encode("utf-8")).hexdigest() != receipt_pin["receipt_body_sha256"]):
            raise ValueError("pinned_receipt_not_latest_or_hash_mismatch")
    receipts = []
    decoration = r"(?: Keep it up!| More of your lovely PRs please\.| Breezy!| :[a-z][a-z0-9_]{0,31}:)?"
    if receipt_pin is not None:
        decoration = r"(?: Keep it up!| More of your lovely PRs please\.| [A-Za-z]{1,32}!| :[a-z][a-z0-9_]{0,31}:)?"
    pattern = (r"<!-- codex-review-receipt:v1 -->\n\s*\n"
        r"Codex Review: Didn't find any major issues\."
        + decoration + r"\n\s*\n"
        r"\*\*Reviewed commit:\*\* `([0-9a-f]{10})`\s*(?P<details><details>.*</details>)?\s*")
    for row in [latest_receipt]:
        body = row["body"].replace("\r\n", "\n")
        match = re.fullmatch(pattern, body, re.DOTALL)
        at, edited = _comment_time(row.get("created_at")), _comment_time(row.get("updated_at"))
        if (match and match[1] == head_sha[:10] and at is not None and at == edited
                and observed_at <= at <= updated <= attested_at
                and "<!-- codex-code-review-finding:v1 -->" not in body
                and re.search(r"\[P[0-3]\]", body, re.IGNORECASE) is None
                and (match["details"] is None or _normalized_details(match["details"]) == _normalized_details(CODEX_ABOUT_DETAILS))):
            receipts.append(row)
    if not receipts:
        raise ValueError("missing_immutable_clean_codex_receipt")
    receipt = max(receipts, key=lambda row: _comment_time(row["created_at"]))
    receipt_at = _comment_time(receipt["created_at"])
    for review in reviews:
        if login(review) in DEFAULT_REVIEWERS and review.get("commit_id") == head_sha:
            at = _comment_time(review.get("submitted_at"))
            if review.get("state") in {"PENDING", "CHANGES_REQUESTED"} or at is None or at > receipt_at:
                raise ValueError("newer_or_blocking_codex_review")
    for row in review_comments:
        if (login(row) in DEFAULT_REVIEWERS and head_sha in {row.get("commit_id"), row.get("original_commit_id")}
                and "<!-- codex-code-review-finding:v1 -->" in str(row.get("body") or "")):
            at = _comment_time(row.get("updated_at") or row.get("created_at"))
            if at is None or at >= receipt_at:
                raise ValueError("newer_codex_finding_for_current_head")
    count, page_count = _resolved_threads(thread_pages, repository=repository, number=number, head_sha=head_sha)
    result = dict(schema_version="trusted-codex-issue-comment-receipt-v1",
        repository=repository, pull_request_number=number, head_sha=head_sha,
        commit_prefix=head_sha[:10], receipt_comment_id=receipt["id"], receipt_created_at=receipt["created_at"],
        receipt_body_sha256=hashlib.sha256(receipt["body"].encode()).hexdigest(), summary_comment_id=summary["id"],
        summary_updated_at=summary["updated_at"], summary_body_sha256=hashlib.sha256(summary["body"].encode()).hexdigest(),
        summary_finding_flags={key: code[key] for key in ("has_any_findings", "has_unresolved_findings")},
        resolved_thread_count=count, thread_page_count=page_count,
        thread_snapshot_sha256=hashlib.sha256(json.dumps(thread_pages, sort_keys=True, separators=(",", ":")).encode()).hexdigest())
    if pin_binding is not None:
        result["pin_binding"] = pin_binding
    return result


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
    issue_comments: list[dict[str, Any]] | None = None,
    review_comments: list[dict[str, Any]] | None = None,
    review_thread_pages: list[dict[str, Any]] | None = None,
    commit_binding: dict[str, Any] | None = None,
    repository: str | None = None,
    attestation_comment: dict | None = None,
    attestation_event: dict | None = None,
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
    comment_receipt_binding = None
    pin_requested = "receipt_pin" in attestation or attestation_comment is not None or attestation_event is not None
    if pin_requested:
        try:
            pin, pin_binding = _verified_attestation_pin(attestation=attestation, api_comment=attestation_comment,
                event=attestation_event, repository=repository, number=pull_request.get("number"), head_sha=head_sha)
            if observed_at is None or attested_at is None:
                raise ValueError("missing_pin_attestation_window")
            comment_receipt_binding = paired_comment_evidence(comments=issue_comments,
                review_comments=review_comments, thread_pages=review_thread_pages, commit_binding=commit_binding,
                repository=repository, pull_request=pull_request, head_sha=head_sha,
                observed_at=observed_at, attested_at=attested_at, reviews=reviews,
                receipt_pin=pin, pin_binding=pin_binding)
            evidence_type = COMMENT_EVIDENCE
            evidence_id = comment_receipt_binding["receipt_comment_id"]
            evidence_at = comment_receipt_binding["receipt_created_at"]
        except ValueError as exc:
            failures.extend(["no_codex_evidence_for_current_head", str(exc)])
        except (TypeError, KeyError, AttributeError, OverflowError, RecursionError):
            failures.extend(["no_codex_evidence_for_current_head", "malformed_pin_evidence"])
    elif exact_reviews:
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
    elif (any(value is not None for value in (issue_comments, review_comments, review_thread_pages,
            commit_binding, repository)) and observed_at is not None and attested_at is not None):
        try:
            comment_receipt_binding = paired_comment_evidence(comments=issue_comments,
                review_comments=review_comments, thread_pages=review_thread_pages,
                commit_binding=commit_binding, repository=repository, pull_request=pull_request,
                head_sha=head_sha, observed_at=observed_at, attested_at=attested_at, reviews=reviews)
            evidence_type = COMMENT_EVIDENCE
            evidence_id = comment_receipt_binding["receipt_comment_id"]
            evidence_at = comment_receipt_binding["receipt_created_at"]
        except ValueError as exc:
            failures.extend(["no_codex_evidence_for_current_head", str(exc)])
        except (TypeError, KeyError, AttributeError, OverflowError, RecursionError):
            failures.extend(["no_codex_evidence_for_current_head", "malformed_comment_evidence"])
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
        "comment_receipt_binding": comment_receipt_binding,
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
    parser.add_argument("--issue-comments")
    parser.add_argument("--review-comments")
    parser.add_argument("--review-threads")
    parser.add_argument("--commit-binding")
    parser.add_argument("--repository")
    parser.add_argument("--attestation-comment")
    parser.add_argument("--attestation-event")
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
        issue_comments=flatten_records(read_json(args.issue_comments)) if args.issue_comments else None,
        review_comments=flatten_records(read_json(args.review_comments)) if args.review_comments else None,
        review_thread_pages=read_json(args.review_threads) if args.review_threads else None,
        commit_binding=read_json(args.commit_binding) if args.commit_binding else None,
        repository=args.repository,
        attestation_comment=read_json(args.attestation_comment) if args.attestation_comment else None,
        attestation_event=read_json(args.attestation_event) if args.attestation_event else None,
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
