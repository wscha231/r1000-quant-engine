#!/usr/bin/env python3
"""Fail-closed evaluator for the Run287 risk-tiered review-complete merge gate.

v3 separates low-risk research/data publication from portfolio/live-policy changes.
All tiers require a trusted exact-head observation and maintainer attestation.
R0/R1 may complete without Codex. R2/R3 additionally require independent exact-head
review evidence from Codex.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = "run287-review-complete-gate-v3"
PASS_STATUS = "PASS_REVIEW_COMPLETE"
BLOCKED_STATUS = "BLOCKED_REVIEW_INCOMPLETE"
RISK_TIERS = ("R0", "R1", "R2", "R3")
INDEPENDENT_REVIEW_TIERS = {"R2", "R3"}
DEFAULT_CODEX_REVIEWERS = {
    "chatgpt-codex-connector",
    "chatgpt-codex-connector[bot]",
}
CODEX_REVIEW_STATES = {"APPROVED", "COMMENTED"}
WRITE_PERMISSIONS = {"admin", "maintain", "write"}
REQUIRED_CODE_CHECKS = ("validate", "portfolio_guard")

GOVERNANCE_R3_PATHS = {
    "agents.md",
    "docs/run287_github_agent_operating_standard.md",
    "tools/check_pr_review_complete.py",
    "tests/run287_review_complete_gate_smoke.py",
    ".github/workflows/review_complete_gate.yml",
    "data_static/run287_review_complete_gate_contract.json",
    "tools/run_pr_validation.py",
    ".github/workflows/pr_validation.yml",
    ".github/workflows/portfolio_system_guard.yml",
}
R3_PATH_RE = re.compile(
    r"(^|[/_.-])(broker|brokerage|orders?|fills?|ledger|kill[-_]?switch|secrets?|credentials?|production|live|trade|trading)([/_.-]|$)"
    r"|accepted[-_](paper|account|ledger|publication|state)",
    re.I,
)
R2_PATH_RE = re.compile(
    r"(^|[/_.-])(portfolio|targets?|sizing|allocation|weights?|selector|regime|risk[-_]?overlay|"
    r"crisis[-_]?state|champion|promotion|execution|cost[-_]?model)([/_.-]|$)",
    re.I,
)
R1_PATH_RE = re.compile(
    r"(^|[/_.-])(data|collector|ingest|lake|macro|calendar|vintage|provenance|pit|universe|"
    r"sec|prices?|estimates?|fred|alfred|liquidity|research)([/_.-]|$)",
    re.I,
)
EXECUTABLE_SUFFIXES = {".py", ".sh", ".ps1", ".yml", ".yaml", ".json", ".toml"}
SAFE_WORKFLOW_RE = re.compile(r"(^|[_-])(ci|test|tests|smoke|validate|validation|research|preflight)([_\.-]|$)", re.I)
R3_ADDED_LINE_RE = re.compile(
    r"(^|\s)(schedule\s*:|secrets\.|orders_allowed\s*[:=]\s*true|"
    r"target_mutation_allowed\s*[:=]\s*true|canonical_regime_mutation_allowed\s*[:=]\s*true|"
    r"live_trading_enabled\s*[:=]\s*true|production_activation_allowed\s*[:=]\s*true|"
    r"auto[-_]?promot\w*\s*[:=]\s*true)",
    re.I,
)
R2_ADDED_LINE_RE = re.compile(
    r"(^|\s)(cash_weight|target_weight|portfolio_weight|risk_limit|regime_threshold|"
    r"position_size|allocation_weight)\b",
    re.I,
)


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def flatten_records(value: Any) -> list[dict[str, Any]]:
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


def extract_check_runs(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if isinstance(value.get("check_runs"), list):
            for item in value["check_runs"]:
                rows.extend(extract_check_runs(item))
        elif value.get("name"):
            rows.append(value)
    elif isinstance(value, list):
        for item in value:
            rows.extend(extract_check_runs(item))
    return rows


def extract_review_threads(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if "isResolved" in value or "is_resolved" in value:
            rows.append(value)
        for item in value.values():
            if isinstance(item, (dict, list)):
                rows.extend(extract_review_threads(item))
    elif isinstance(value, list):
        for item in value:
            rows.extend(extract_review_threads(item))
    return rows


def required_check_failures(value: Any, *, head_sha: str) -> list[str]:
    rows = extract_check_runs(value)
    failures: list[str] = []
    for name in REQUIRED_CODE_CHECKS:
        candidates = [
            row for row in rows
            if str(row.get("name") or "") == name
            and (not row.get("head_sha") or str(row.get("head_sha")).lower() == head_sha)
        ]
        if not candidates:
            failures.append("missing_required_check:" + name)
            continue
        def key(row: dict[str, Any]):
            return (parse_time(row.get("completed_at")) or parse_time(row.get("started_at"))
                    or datetime.min.replace(tzinfo=timezone.utc), int(row.get("id") or 0))
        latest = max(candidates, key=key)
        if latest.get("status") != "completed" or latest.get("conclusion") != "success":
            failures.append("required_check_not_green:" + name)
    return failures


def added_patch_lines(patch: Any) -> list[str]:
    if not isinstance(patch, str):
        return []
    return [line[1:] for line in patch.splitlines() if line.startswith("+") and not line.startswith("+++")]


def tier_max(a: str, b: str) -> str:
    return RISK_TIERS[max(RISK_TIERS.index(a), RISK_TIERS.index(b))]


def classify_file(record: dict[str, Any]) -> dict[str, Any]:
    path = str(record.get("filename") or "").strip().replace("\\", "/")
    lower = path.lower()
    reasons: list[str] = []
    tier = "R0"
    if not path:
        return {"filename": path, "tier": "R3", "reasons": ["missing_filename"]}

    if lower in GOVERNANCE_R3_PATHS:
        tier = "R3"; reasons.append("governance_or_gate_path")
    elif R3_PATH_RE.search(lower):
        tier = "R3"; reasons.append("live_durable_or_secret_path")
    elif R2_PATH_RE.search(lower):
        tier = "R2"; reasons.append("portfolio_or_policy_path")
    elif lower.startswith(".github/workflows/"):
        name = Path(lower).name
        if record.get("patch") is None:
            tier = "R3"; reasons.append("workflow_patch_unavailable")
        elif SAFE_WORKFLOW_RE.search(name):
            tier = "R1"; reasons.append("side_effect_free_workflow_name")
        else:
            tier = "R2"; reasons.append("unclassified_workflow")
    elif R1_PATH_RE.search(lower) or lower.startswith("data_static/"):
        tier = "R1"; reasons.append("research_data_or_tool_path")
    elif lower.startswith("docs/") or lower.startswith("tests/") or lower.endswith(".md"):
        tier = "R0"; reasons.append("documentation_or_general_test")
    elif lower.startswith("tools/") and Path(lower).suffix in EXECUTABLE_SUFFIXES:
        tier = "R2"; reasons.append("unclassified_tool_code")
    elif Path(lower).suffix in EXECUTABLE_SUFFIXES:
        tier = "R2"; reasons.append("unclassified_executable_code")
    else:
        tier = "R1"; reasons.append("unclassified_nonexecuting_asset")

    additions = added_patch_lines(record.get("patch"))
    if any(R3_ADDED_LINE_RE.search(line) for line in additions):
        tier = "R3"; reasons.append("r3_mutation_or_schedule_marker")
    elif any(R2_ADDED_LINE_RE.search(line) for line in additions):
        tier = tier_max(tier, "R2"); reasons.append("r2_portfolio_policy_marker")
    return {"filename": path, "tier": tier, "reasons": sorted(set(reasons))}


def classify_change_set(files: Iterable[dict[str, Any]]) -> dict[str, Any]:
    records = [record for record in files if isinstance(record, dict)]
    if not records:
        return {
            "risk_tier": "R3",
            "independent_review_required": True,
            "files": [],
            "reasons": ["missing_changed_files"],
            "classification_complete": False,
        }
    classified = [classify_file(record) for record in records]
    tier = "R0"
    for row in classified:
        tier = tier_max(tier, row["tier"])
    reasons = sorted({reason for row in classified for reason in row["reasons"]})
    return {
        "risk_tier": tier,
        "independent_review_required": tier in INDEPENDENT_REVIEW_TIERS,
        "files": classified,
        "reasons": reasons,
        "classification_complete": True,
    }


def exact_codex_reviews(
    reviews: Iterable[dict[str, Any]], *, head_sha: str, head_observed_at: datetime,
    attested_at: datetime, reviewers: set[str],
) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    for review in reviews:
        if login(review) not in reviewers:
            continue
        if str(review.get("state") or "").upper() not in CODEX_REVIEW_STATES:
            continue
        if str(review.get("commit_id") or "").lower() != head_sha:
            continue
        submitted_at = parse_time(review.get("submitted_at"))
        if submitted_at is None or submitted_at < head_observed_at or submitted_at > attested_at:
            continue
        matched.append(review)
    return matched


def fresh_codex_clean_reactions(
    reactions: Iterable[dict[str, Any]], *, head_observed_at: datetime,
    attested_at: datetime, reviewers: set[str],
) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    for reaction in reactions:
        if login(reaction) not in reviewers or str(reaction.get("content") or "") != "+1":
            continue
        created_at = parse_time(reaction.get("created_at"))
        if created_at is None or created_at < head_observed_at or created_at > attested_at:
            continue
        matched.append(reaction)
    return matched


def trusted_change_requests(reviews: Iterable[dict[str, Any]], *, head_sha: str,
                            author_login: str, codex_reviewers: set[str]) -> list[dict[str, Any]]:
    blocked: list[dict[str, Any]] = []
    for review in reviews:
        if str(review.get("state") or "").upper() != "CHANGES_REQUESTED":
            continue
        if str(review.get("commit_id") or "").lower() != head_sha:
            continue
        reviewer = login(review)
        association = str(review.get("author_association") or "").upper()
        if reviewer in codex_reviewers or (
            reviewer and reviewer != author_login and association in {"OWNER", "MEMBER", "COLLABORATOR"}
        ):
            blocked.append(review)
    return blocked


def evaluate(*, pull_request: dict[str, Any], head_observation: dict[str, Any],
             attestation: dict[str, Any] | None, reviews: list[dict[str, Any]],
             reactions: list[dict[str, Any]], files: list[dict[str, Any]],
             checks: Any, threads: Any, reviewers: set[str] | None = None) -> dict[str, Any]:
    allowed = {value.lower() for value in (reviewers or DEFAULT_CODEX_REVIEWERS)}
    head = pull_request.get("head")
    head_sha = str(head.get("sha") if isinstance(head, dict) else "").strip().lower()
    author_login = login(pull_request)
    failures: list[str] = []
    if len(head_sha) != 40:
        failures.append("missing_or_invalid_head_sha")
    if bool(pull_request.get("draft")):
        failures.append("pull_request_is_draft")

    change = classify_change_set(files)
    if not change["classification_complete"]:
        failures.append("risk_classification_incomplete")

    failures.extend(required_check_failures(checks, head_sha=head_sha))
    unresolved_threads = [
        row for row in extract_review_threads(threads)
        if not bool(row.get("isResolved", row.get("is_resolved", False)))
    ]
    if unresolved_threads:
        failures.append("unresolved_review_threads")

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

    codex_reviews: list[dict[str, Any]] = []
    clean_reactions: list[dict[str, Any]] = []
    if head_sha and observed_at is not None and attested_at is not None:
        codex_reviews = exact_codex_reviews(reviews, head_sha=head_sha,
            head_observed_at=observed_at, attested_at=attested_at, reviewers=allowed)
        clean_reactions = fresh_codex_clean_reactions(reactions,
            head_observed_at=observed_at, attested_at=attested_at, reviewers=allowed)

    change_requests = trusted_change_requests(reviews, head_sha=head_sha,
        author_login=author_login, codex_reviewers=allowed) if head_sha else []
    if change_requests:
        failures.append("trusted_current_head_changes_requested")

    independent_required = bool(change["independent_review_required"])
    evidence_type = ""
    evidence_id: int | str | None = None
    evidence_at = ""
    if codex_reviews:
        selected = max(codex_reviews, key=lambda row: parse_time(row.get("submitted_at")) or datetime.min.replace(tzinfo=timezone.utc))
        evidence_type = "ATTESTED_EXACT_HEAD_CODEX_REVIEW"
        evidence_id = selected.get("id")
        evidence_at = str(selected.get("submitted_at") or "")
    elif clean_reactions:
        selected = max(clean_reactions, key=lambda row: parse_time(row.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc))
        evidence_type = "MAINTAINER_BOUND_CODEX_CLEAN_REACTION"
        evidence_id = selected.get("id")
        evidence_at = str(selected.get("created_at") or "")
    elif not independent_required and attestation:
        evidence_type = "MAINTAINER_ATTESTED_LOW_RISK"
        evidence_at = str(attestation.get("created_at") or "")
    else:
        failures.append("independent_review_required_for_r2_r3")

    passed = not failures
    return {
        "schema_version": SCHEMA_VERSION,
        "status": PASS_STATUS if passed else BLOCKED_STATUS,
        "passed": passed,
        "pull_request_number": pull_request.get("number"),
        "head_sha": head_sha,
        "risk_tier": change["risk_tier"],
        "risk_reasons": change["reasons"],
        "risk_files": change["files"],
        "independent_review_required": independent_required,
        "head_observed_at": observed_at.isoformat() if observed_at else None,
        "head_observation_check_run_id": head_observation.get("check_run_id"),
        "attestor": attestor or None,
        "attestor_permission": attestor_permission or None,
        "attested_at": attested_at.isoformat() if attested_at else None,
        "attestation_source": attestation.get("source") or None,
        "accepted_codex_reviewer_logins": sorted(allowed),
        "evidence_type": evidence_type or None,
        "evidence_id": evidence_id,
        "evidence_at": evidence_at or None,
        "exact_head_codex_review_count": len(codex_reviews),
        "fresh_codex_clean_reaction_count": len(clean_reactions),
        "trusted_changes_requested_count": len(change_requests),
        "unresolved_review_thread_count": len(unresolved_threads),
        "required_code_checks": list(REQUIRED_CODE_CHECKS),
        "failures": sorted(set(failures)),
        "unresolved_conversations_checked_by": "review_complete_gate_graphql",
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
    parser.add_argument("--files", required=True)
    parser.add_argument("--checks", required=True)
    parser.add_argument("--threads", required=True)
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
        files=flatten_records(read_json(args.files)),
        checks=read_json(args.checks),
        threads=read_json(args.threads),
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
