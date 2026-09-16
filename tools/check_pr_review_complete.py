#!/usr/bin/env python3
"""Fail-closed risk-tiered review-complete gate for Run287.

R0/R1 may complete without Codex only for changes that cannot directly mutate
portfolio/live/durable state. R2/R3 require exact-head Codex evidence.
All tiers require exact-head maintainer attestation, canonical PR checks, and
zero unresolved review threads.
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
CANONICAL_WORKFLOWS = {
    "validate": ".github/workflows/pr_validation.yml",
    "portfolio_guard": ".github/workflows/portfolio_system_guard.yml",
}

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
    r"(^|[/_.-])(broker|brokerage|orders?|fills?|ledger|kill[-_]?switch|secrets?|"
    r"credentials?|production|live|trade|trading)([/_.-]|$)"
    r"|accepted[-_](paper|account|ledger|publication|state)",
    re.I,
)
R2_PATH_RE = re.compile(
    r"(^|[/_.-])(portfolio|targets?|sizing|allocation|weights?|selector|regime|"
    r"risk[-_]?overlay|crisis[-_]?state|champion|promotion|execution|"
    r"cost[-_]?model)([/_.-]|$)",
    re.I,
)
R1_PATH_RE = re.compile(
    r"(^|[/_.-])(data|collector|ingest|lake|macro|calendar|vintage|provenance|"
    r"pit|universe|sec|prices?|estimates?|fred|alfred|liquidity|research)([/_.-]|$)",
    re.I,
)
EXECUTABLE_SUFFIXES = {
    ".py", ".pyw", ".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat", ".cmd",
    ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".rb", ".pl", ".php", ".lua",
    ".go", ".rs", ".java", ".kt", ".scala", ".sql", ".ipynb", ".yml", ".yaml",
    ".toml",
}
EXECUTABLE_BASENAMES = {
    "dockerfile", "makefile", "justfile", "procfile", "rakefile", "gemfile",
    "package.json",
}
EXECUTABLE_PREFIXES = ("tools/", "scripts/", "bin/", ".github/actions/")
DOC_SUFFIXES = {".md", ".rst", ".txt", ".adoc"}
DATA_PREFIXES = ("data/", "data_static/", "fixtures/")
RESEARCH_ONLY_PREFIX = "research_only/"

R3_AUTHORITY_CHANGE_RE = re.compile(
    r"\b(orders?_allowed|target_mutation_allowed|canonical_regime_mutation_allowed|"
    r"live_trading_enabled|production_activation_allowed|kill[-_]?switch|"
    r"auto[-_]?promot\w*|accepted[-_](state|ledger|account|publication|paper))\b",
    re.I,
)
R3_WORKFLOW_CHANGE_RE = re.compile(
    r"(?i)(\bschedule\b|\bcron\b|\bsecrets\b|\brepository_dispatch\b|"
    r"\bpull_request_target\b|\bworkflow_run\b|:\s*write(?:-all)?\b|\bwrite-all\b)"
)
R2_POLICY_CHANGE_RE = re.compile(
    r"\b(cash_weight|target_weight|portfolio_weight|risk_limit|regime_threshold|"
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


def tier_max(a: str, b: str) -> str:
    return RISK_TIERS[max(RISK_TIERS.index(a), RISK_TIERS.index(b))]


def normalize_path(value: Any) -> str:
    return str(value or "").strip().replace("\\", "/")


def is_executable_path(path: str) -> bool:
    lower = path.lower()
    base = Path(lower).name
    if lower.startswith(RESEARCH_ONLY_PREFIX):
        return Path(lower).suffix in EXECUTABLE_SUFFIXES or base in EXECUTABLE_BASENAMES
    return (
        lower.startswith(EXECUTABLE_PREFIXES)
        or lower.startswith(".github/workflows/")
        or Path(lower).suffix in EXECUTABLE_SUFFIXES
        or base in EXECUTABLE_BASENAMES
    )


def changed_patch_lines(patch: Any) -> list[str]:
    if not isinstance(patch, str):
        return []
    rows: list[str] = []
    for line in patch.splitlines():
        if line.startswith(("+++", "---", "@@")):
            continue
        if line.startswith(("+", "-")):
            rows.append(line[1:])
    return rows


def classify_path(path: str) -> tuple[str, list[str]]:
    lower = normalize_path(path).lower()
    base = Path(lower).name
    reasons: list[str] = []
    if not lower:
        return "R3", ["missing_filename"]
    if base == "agents.md" or lower in GOVERNANCE_R3_PATHS:
        return "R3", ["governance_or_gate_path"]
    if R3_PATH_RE.search(lower):
        return "R3", ["live_durable_or_secret_path"]
    if R2_PATH_RE.search(lower):
        return "R2", ["portfolio_or_policy_path"]
    if lower.startswith(".github/workflows/"):
        return "R2", ["workflow_change"]
    if lower.startswith(EXECUTABLE_PREFIXES):
        return "R2", ["executable_tool_or_action"]
    if lower.startswith(RESEARCH_ONLY_PREFIX):
        return "R1", ["isolated_research_only_path"]
    if lower.startswith(DATA_PREFIXES):
        return "R1", ["research_data_path"]
    if lower.startswith("tests/"):
        return "R0", ["general_test_only"]
    if lower.startswith("docs/") and Path(lower).suffix in DOC_SUFFIXES:
        return "R0", ["documentation_only"]
    if lower.endswith(tuple(DOC_SUFFIXES)):
        return "R0", ["documentation_only"]
    if Path(lower).suffix in EXECUTABLE_SUFFIXES or base in EXECUTABLE_BASENAMES:
        return "R2", ["unclassified_executable_code"]
    if R1_PATH_RE.search(lower):
        return "R1", ["research_or_data_asset"]
    return "R1", ["unclassified_nonexecuting_asset"]


def classify_file(record: dict[str, Any]) -> dict[str, Any]:
    path = normalize_path(record.get("filename"))
    previous = normalize_path(record.get("previous_filename"))
    status = str(record.get("status") or "").lower()
    tier, reasons = classify_path(path)

    if previous:
        previous_tier, previous_reasons = classify_path(previous)
        if RISK_TIERS.index(previous_tier) > RISK_TIERS.index(tier):
            tier = previous_tier
        reasons.extend("previous:" + reason for reason in previous_reasons)
    elif status == "renamed":
        tier = "R3"
        reasons.append("renamed_without_previous_filename")

    patch = record.get("patch")
    if patch is None and (is_executable_path(path) or (previous and is_executable_path(previous))):
        tier = "R3"
        reasons.append("executable_patch_unavailable")

    lines = changed_patch_lines(patch)
    if any(R3_AUTHORITY_CHANGE_RE.search(line) for line in lines):
        tier = "R3"
        reasons.append("authority_control_changed")
    if (path.lower().startswith(".github/workflows/") or
            previous.lower().startswith(".github/workflows/")):
        if any(R3_WORKFLOW_CHANGE_RE.search(line) for line in lines):
            tier = "R3"
            reasons.append("workflow_scheduler_secret_or_write_change")
    if any(R2_POLICY_CHANGE_RE.search(line) for line in lines):
        tier = tier_max(tier, "R2")
        reasons.append("portfolio_policy_marker_changed")

    return {
        "filename": path,
        "previous_filename": previous or None,
        "status": status or None,
        "tier": tier,
        "reasons": sorted(set(reasons)),
    }


def classify_change_set(files: Iterable[dict[str, Any]], *, expected_count: Any) -> dict[str, Any]:
    records = [record for record in files if isinstance(record, dict)]
    reasons: list[str] = []
    complete = True
    try:
        expected = int(expected_count)
    except (TypeError, ValueError):
        expected = -1
        complete = False
        reasons.append("missing_or_invalid_changed_files_count")

    names = [normalize_path(record.get("filename")) for record in records]
    if not records:
        complete = False
        reasons.append("missing_changed_files")
    if expected >= 0 and len(records) != expected:
        complete = False
        reasons.append("changed_file_inventory_count_mismatch")
    if len(set(names)) != len(names):
        complete = False
        reasons.append("duplicate_changed_file_records")

    classified = [classify_file(record) for record in records]
    tier = "R0"
    for row in classified:
        tier = tier_max(tier, row["tier"])
    if not complete:
        tier = "R3"
    reasons.extend(reason for row in classified for reason in row["reasons"])
    return {
        "risk_tier": tier,
        "independent_review_required": tier in INDEPENDENT_REVIEW_TIERS,
        "files": classified,
        "reasons": sorted(set(reasons)),
        "classification_complete": complete,
        "expected_changed_files": expected if expected >= 0 else None,
        "observed_changed_files": len(records),
    }


def extract_workflow_runs(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if isinstance(value.get("workflow_runs"), list):
            for item in value["workflow_runs"]:
                rows.extend(extract_workflow_runs(item))
        elif value.get("path") and value.get("id"):
            rows.append(value)
        else:
            for item in value.values():
                if isinstance(item, (dict, list)):
                    rows.extend(extract_workflow_runs(item))
    elif isinstance(value, list):
        for item in value:
            rows.extend(extract_workflow_runs(item))
    return rows


def required_run_failures(value: Any, *, head_sha: str) -> list[str]:
    rows = extract_workflow_runs(value)
    failures: list[str] = []
    for check_name, workflow_path in CANONICAL_WORKFLOWS.items():
        candidates = [
            row for row in rows
            if str(row.get("path") or "") == workflow_path
            and str(row.get("head_sha") or "").lower() == head_sha
            and str(row.get("event") or "") == "pull_request"
        ]
        if not candidates:
            failures.append("missing_required_check:" + check_name)
            continue

        def key(row: dict[str, Any]):
            stamp = (
                parse_time(row.get("run_started_at"))
                or parse_time(row.get("created_at"))
                or parse_time(row.get("updated_at"))
                or datetime.min.replace(tzinfo=timezone.utc)
            )
            return stamp, int(row.get("id") or 0)

        latest = max(candidates, key=key)
        if latest.get("status") != "completed" or latest.get("conclusion") != "success":
            failures.append("required_check_not_green:" + check_name)
    return failures


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


def trusted_change_requests(
    reviews: Iterable[dict[str, Any]], *, head_sha: str,
    author_login: str, codex_reviewers: set[str],
) -> list[dict[str, Any]]:
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


def evaluate(
    *, pull_request: dict[str, Any], head_observation: dict[str, Any],
    attestation: dict[str, Any] | None, reviews: list[dict[str, Any]],
    reactions: list[dict[str, Any]], files: list[dict[str, Any]],
    runs: Any, threads: Any, reviewers: set[str] | None = None,
) -> dict[str, Any]:
    allowed = {value.lower() for value in (reviewers or DEFAULT_CODEX_REVIEWERS)}
    head = pull_request.get("head")
    head_sha = str(head.get("sha") if isinstance(head, dict) else "").strip().lower()
    author_login = login(pull_request)
    failures: list[str] = []

    if len(head_sha) != 40:
        failures.append("missing_or_invalid_head_sha")
    if bool(pull_request.get("draft")):
        failures.append("pull_request_is_draft")

    change = classify_change_set(files, expected_count=pull_request.get("changed_files"))
    if not change["classification_complete"]:
        failures.append("risk_classification_incomplete")

    failures.extend(required_run_failures(runs, head_sha=head_sha))
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
        codex_reviews = exact_codex_reviews(
            reviews, head_sha=head_sha, head_observed_at=observed_at,
            attested_at=attested_at, reviewers=allowed,
        )
        clean_reactions = fresh_codex_clean_reactions(
            reactions, head_observed_at=observed_at,
            attested_at=attested_at, reviewers=allowed,
        )

    change_requests = trusted_change_requests(
        reviews, head_sha=head_sha, author_login=author_login,
        codex_reviewers=allowed,
    ) if head_sha else []
    if change_requests:
        failures.append("trusted_current_head_changes_requested")

    independent_required = bool(change["independent_review_required"])
    evidence_type = ""
    evidence_id: int | str | None = None
    evidence_at = ""
    if codex_reviews:
        selected = max(
            codex_reviews,
            key=lambda row: parse_time(row.get("submitted_at")) or datetime.min.replace(tzinfo=timezone.utc),
        )
        evidence_type = "ATTESTED_EXACT_HEAD_CODEX_REVIEW"
        evidence_id = selected.get("id")
        evidence_at = str(selected.get("submitted_at") or "")
    elif clean_reactions:
        selected = max(
            clean_reactions,
            key=lambda row: parse_time(row.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc),
        )
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
        "classification_complete": change["classification_complete"],
        "expected_changed_files": change["expected_changed_files"],
        "observed_changed_files": change["observed_changed_files"],
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
        "failures": sorted(set(failures)),
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
    parser.add_argument("--runs", required=True)
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
        runs=read_json(args.runs),
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
