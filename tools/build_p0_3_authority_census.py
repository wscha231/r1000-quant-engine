#!/usr/bin/env python3
"""Build the read-only P0-3 branch, PR, and workflow authority census.

The collector consumes the repository's exact-head U0 GitHub census, verifies
that the live branch and PR identities have not moved, resolves Git ancestry
from locally fetched objects, and statically inventories every workflow.  It
does not dispatch a workflow, mutate a GitHub namespace, write a target or
ledger, or authorize production/live behavior.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import re
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd
import pyarrow as pa
import yaml


REPOSITORY = "wscha231/r1000-quant-engine"
CENSUS_REPOSITORY_DIR = Path("docs/run287_p0_3_authority_census")
SCHEMA_VERSION = "run287-p0-3-authority-census-v1"
POLICY_SCHEMA = "run287-p0-3-workflow-authority-policy-v1"
U0_SCHEMA = "run287-u0-v2-github-census-v1"
PR_SUPPLEMENT_SCHEMA = "run287-p0-3-frozen-pr-supplement-v2"
LEGACY_PR_SUPPLEMENT_SCHEMA = "run287-p0-3-frozen-pr-supplement-v1"
LEGACY_PR_SUPPLEMENT_SHA256 = (
    "29bd41bcbd07a7a739856ccc870b91711491986c464efc4342a7081d391b554c"
)
FROZEN_U0_UNCOMPRESSED_SHA256 = (
    "5c9741b84fe9cfff74619322bc99402d92f25979974d42a405e30091ff461216"
)
FROZEN_PR_SUPPLEMENT_V2_UNCOMPRESSED_SHA256 = (
    "362f0b7245ca05360ac206c122077a4c07b2111c748a2cd72e8b8af58244689a"
)
FROZEN_BRANCH_SUPPLEMENT_SHA256 = (
    "12ea17046e062707437b995b95cc610ccf2ef0398dbdf9ff05c0011ff810f530"
)
FROZEN_WORKFLOW_POLICY_SHA256 = (
    "01977fda9c76c2513244b07d118cbb8bae620e6db03c0d6c3060763e36b9d3f7"
)
FROZEN_RUNTIME_REQUIREMENTS_SHA256 = (
    "8c74d7c2c73e36c06bee51001a8ffc2579ea71555bb392cfb89a6ce0e05047ca"
)
BRANCH_SUPPLEMENT_SCHEMA = "run287-p0-3-frozen-branch-supplement-v1"
GENERATOR_RUNTIME_VERSIONS = {
    "pandas": "2.3.3",
    "pyarrow": "23.0.1",
    "PyYAML": "6.0.3",
}
REQUIRED_OFFICIAL_AUTHORITY = {
    "us_target_writer_workflow": "daily_operating_selection_refresh.yml",
    "paper_ledger_consumer_workflow": "daily_operating_selection_refresh.yml",
    "paper_ledger_mode": "SIMULATED_FILL_ONLY",
    "accepted_state_store": "GOOGLE_DRIVE_CANONICAL_PAPER_STATE",
    "live_broker_writer_workflow": None,
}
REQUIRED_OFFICIAL_WORKFLOW_POLICY = {
    "declared_role": "official_us_target_and_simulated_fill_paper_operation",
    "decision": "KEEP",
    "target_authority": "OFFICIAL_CURRENT_US_TARGET_WRITER",
    "paper_ledger_authority": "OFFICIAL_SIMULATED_FILL_CONSUMER_AND_WRITER",
    "durable_write_scope": "CANONICAL_PAPER_ACCEPTED_STATE_FAIL_CLOSED",
    "human_approval_requirement": (
        "SCHEDULE_FAIL_CLOSED; "
        "LEGACY_PARENT_MIGRATION_REQUIRES_EXPLICIT_ONE_TIME_WORKFLOW_DISPATCH_AUTHORIZATION"
    ),
}
REQUIRED_PROMOTION_BLOCKERS = [
    "branch_only_experiment_candidates_require_recovery",
    "duplicate_code_head_sha_groups_require_canonical_deduplication",
    "experiment_candidates_require_canonical_mapping",
    "historical_return_series_and_trial_deduplication_not_recovered",
    "one_or_more_git_ancestry_results_are_unverified",
    "one_or_more_pr_changed_path_lists_are_truncated",
    "one_or_more_pr_check_metadata_sets_are_unresolved",
    "one_or_more_pr_review_metadata_sets_are_unresolved",
    "parameter_and_data_hash_duplicate_groups_not_yet_recovered",
]
REQUIRED_GLOBAL_GUARDS = {
    "live_broker_execution_enabled": False,
    "automatic_model_promotion_enabled": False,
    "production_authority_default": "NONE_RESEARCH_ONLY",
    "model_promotion_authority_default": "NONE_AUTOMATIC_DISABLED",
    "unlisted_workflow_policy": "FAIL_CLOSED",
}
BRANCH_EVIDENCE_FIELDS = (
    "merge_base_sha",
    "ahead_count",
    "behind_count",
    "last_commit_at",
    "author_or_agent",
    "changed_paths",
    "workflow_changes",
    "data_or_model_changes",
    "test_changes",
    "artifact_references",
    "executable_changes",
)
BRANCH_JSON_FIELDS = {
    "changed_paths",
    "workflow_changes",
    "data_or_model_changes",
    "test_changes",
    "artifact_references",
    "executable_changes",
}
SHA_RE = re.compile(r"[0-9a-f]{40}")
ISSUE_RE = re.compile(
    r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)", re.IGNORECASE
)
SECRET_RE = re.compile(r"\bsecrets\.([A-Za-z_][A-Za-z0-9_]*)")
VAR_RE = re.compile(r"\bvars\.([A-Za-z_][A-Za-z0-9_]*)")
OUTPUT_ARG_RE = re.compile(
    r"--(?:output|output-dir|report-dir|artifact-dir)\s+[\"']?([^\s\"'\\]+)"
)
ALPHA_RE = re.compile(
    r"\b(alpha|challenger|ablation|sweep|selector|score|scoring|strategy|"
    r"expected[-_ ]return|leadership|momentum|crisis|overlay|regime)\b",
    re.IGNORECASE,
)
BUGFIX_RE = re.compile(
    r"\b(fix|bug|repair|restore|harden|correct|integrity|lifecycle|guard|"
    r"fail[-_ ]closed|recovery)\b",
    re.IGNORECASE,
)
SUPERSEDED_RE = re.compile(
    r"\b(failed|failure|superseded|obsolete|abandoned|deprecated|old|tmp|test[-_ ]only)\b",
    re.IGNORECASE,
)
DATA_MODEL_RE = re.compile(
    r"^(data(?:_|/)|models?/|model_|artifacts?/|outputs?/|cloud_results/|"
    r"cache_|docs/run287_.*(?:model|data|artifact)|r1000_(?:features|signals)\.py$)",
    re.IGNORECASE,
)
ARTIFACT_RE = re.compile(
    r"^(artifacts?/|outputs?/|cloud_results/|reports?/|data_static/|"
    r"docs/.*(?:evidence|result|manifest|snapshot))",
    re.IGNORECASE,
)
TEST_RE = re.compile(r"(^|/)(tests?/|test_[^/]+|[^/]+_test\.py$)", re.IGNORECASE)
WORKFLOW_RE = re.compile(r"^\.github/workflows/[^/]+\.ya?ml$", re.IGNORECASE)
EXECUTABLE_RE = re.compile(
    r"(?:\.py$|\.sh$|\.ps1$|requirements[^/]*\.txt$|pyproject\.toml$|"
    r"^\.github/workflows/)",
    re.IGNORECASE,
)
AUTHORITY_COMMAND_RE = re.compile(
    r"(target_book|simulated_fill_ledger|paper_archive|promotion|champion|"
    r"live_trading|alpaca|rclone\s+(?:copy|copyto|sync)|git\s+push)",
    re.IGNORECASE,
)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_bytes_sha256(content: bytes, expected: str, label: str) -> None:
    if hashlib.sha256(content).hexdigest() != expected:
        raise SystemExit(f"{label} SHA-256 mismatch")


def document_bytes(path: Path) -> bytes:
    content = path.read_bytes()
    return gzip.decompress(content) if path.suffix.lower() == ".gz" else content


def read_json(path: Path) -> Any:
    return json.loads(document_bytes(path).decode("utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(serialized)


def write_gzip(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw_handle:
        with gzip.GzipFile(
            filename="",
            fileobj=raw_handle,
            mode="wb",
            compresslevel=9,
            mtime=0,
        ) as gzip_handle:
            gzip_handle.write(content)


def canonical_text_bytes(path: Path) -> bytes:
    return path.read_text(encoding="utf-8").encode("utf-8")


def run(arguments: list[str], *, cwd: Path) -> str:
    completed = subprocess.run(
        arguments,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if completed.returncode != 0:
        command = " ".join(arguments[:4])
        raise RuntimeError(f"read-only command failed: {command}: {completed.stderr.strip()}")
    return completed.stdout


def run_json(arguments: list[str], *, cwd: Path) -> Any:
    return json.loads(run(arguments, cwd=cwd))


def clean_sha(value: Any) -> str:
    text = str(value or "").lower()
    return text if SHA_RE.fullmatch(text) else ""


def require_iso_timestamp(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} timestamp is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{label} timestamp is invalid") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{label} timestamp lacks a timezone")
    return value


def resolve_generation_timestamp(
    pr_supplement: dict[str, Any],
    branch_supplement: dict[str, Any],
    *,
    verify_live_namespace: bool,
) -> str:
    if verify_live_namespace:
        generated_at = datetime.now(timezone.utc).isoformat()
        pr_supplement["generated_at_utc"] = generated_at
        branch_supplement["generated_at_utc"] = generated_at
        return generated_at
    try:
        generated_at = require_iso_timestamp(
            pr_supplement.get("generated_at_utc"), "frozen PR supplement"
        )
        branch_generated_at = require_iso_timestamp(
            branch_supplement.get("generated_at_utc"), "frozen branch supplement"
        )
    except ValueError as error:
        raise SystemExit(str(error)) from error
    if branch_generated_at != generated_at:
        raise SystemExit("frozen branch/PR supplement timestamps mismatch")
    return generated_at


def validated_pr_identity_tuple(
    row: Mapping[str, Any],
    *,
    head_field: str,
    base_field: str,
    state_field: str,
    updated_field: str,
    label: str,
) -> tuple[str, str, str, str]:
    head_sha = clean_sha(row.get(head_field))
    base_sha = clean_sha(row.get(base_field))
    state = str(row.get(state_field) or "").upper()
    updated_at = require_iso_timestamp(row.get(updated_field), label)
    if not head_sha or not base_sha or state not in {"OPEN", "CLOSED", "MERGED"}:
        raise ValueError(f"{label} identity is incomplete or invalid")
    return head_sha, base_sha, state, updated_at


def validate_research_only_policy(policy: Mapping[str, Any], audit_sha: str) -> None:
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise SystemExit("workflow policy schema mismatch")
    if policy.get("repository") != REPOSITORY:
        raise SystemExit("workflow policy repository mismatch")
    if clean_sha(policy.get("baseline_master_sha")) != audit_sha:
        raise SystemExit("workflow policy baseline mismatch")
    if policy.get("global_guards") != REQUIRED_GLOBAL_GUARDS:
        raise SystemExit("workflow policy research-only guards mismatch")
    official = policy.get("official_authority") or {}
    if official != REQUIRED_OFFICIAL_AUTHORITY:
        raise SystemExit("workflow policy official authority mismatch")
    policy_rows = policy.get("workflows") or {}
    if (
        policy_rows.get(REQUIRED_OFFICIAL_AUTHORITY["us_target_writer_workflow"])
        != REQUIRED_OFFICIAL_WORKFLOW_POLICY
    ):
        raise SystemExit("official workflow policy authority mismatch")
    if any(
        row.get("production_live_authority") == "AUTHORIZED"
        for row in policy_rows.values()
    ):
        raise SystemExit("workflow policy must not authorize production or live execution")


def validate_runtime_requirements_bytes(content: bytes) -> dict[str, str]:
    pins: dict[str, str] = {}
    for raw_line in content.decode("utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s#]+)", line)
        if not match or match.group(1) in pins:
            raise SystemExit("generator requirements must contain unique exact pins")
        pins[match.group(1)] = match.group(2)
    if pins != GENERATOR_RUNTIME_VERSIONS:
        raise SystemExit(
            "generator requirements mismatch: "
            f"expected={GENERATOR_RUNTIME_VERSIONS}, actual={pins}"
        )
    return pins


def validate_runtime_requirements(path: Path) -> dict[str, str]:
    return validate_runtime_requirements_bytes(canonical_text_bytes(path))


def validate_u0_fail_closed_source(
    source: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    summary = source.get("summary") or {}
    branches = source.get("branches") or []
    pull_requests = source.get("pull_requests") or []
    candidates = source.get("experiment_candidates") or []
    source_contract = source.get("source_contract") or {}
    if source_contract.get("normalized_branch_rows_sha256") != canonical_sha256(
        branches
    ):
        raise SystemExit("source normalized branch rows hash mismatch")
    if source_contract.get(
        "normalized_pull_request_rows_sha256"
    ) != canonical_sha256(pull_requests):
        raise SystemExit("source normalized PR rows hash mismatch")
    expected_summary = {
        "branch_count": len(branches),
        "pull_request_count": len(pull_requests),
        "experiment_candidate_count": len(candidates),
        "branch_only_experiment_candidate_count": sum(
            row.get("record_type") == "BRANCH" for row in candidates
        ),
        "pull_request_experiment_candidate_count": sum(
            row.get("record_type") == "PULL_REQUEST" for row in candidates
        ),
        "unmapped_experiment_candidate_count": sum(
            row.get("experiment_identity_status") == "UNMAPPED_BLOCKED"
            for row in candidates
        ),
        "run287_named_branch_count": sum(bool(row.get("run287_named")) for row in branches),
        "run287_named_pr_count": sum(
            "run287" in str(row.get("head_branch") or "").lower()
            for row in pull_requests
        ),
        "branch_ancestry_counts": dict(
            sorted(Counter(str(row.get("ancestry") or "") for row in branches).items())
        ),
        "pull_request_head_ancestry_counts": dict(
            sorted(
                Counter(str(row.get("ancestry") or "") for row in pull_requests).items()
            )
        ),
        "pull_request_state_counts": dict(
            sorted(Counter(str(row.get("state") or "") for row in pull_requests).items())
        ),
    }
    for key, expected in expected_summary.items():
        if summary.get(key) != expected:
            raise SystemExit(f"source summary mismatch: {key}")
    blockers = source.get("promotion_blockers")
    if blockers != REQUIRED_PROMOTION_BLOCKERS:
        raise SystemExit("source promotion blockers do not match the frozen fail-closed set")
    if summary.get("historical_experiment_census_complete") is not False:
        raise SystemExit("source historical experiment census must remain incomplete")
    if summary.get("historical_challenger_allowed") is not False:
        raise SystemExit("source historical challenger authority must remain disabled")
    unmapped = summary.get("unmapped_experiment_candidate_count")
    if type(unmapped) is not int or unmapped <= 0 or unmapped != len(candidates):
        raise SystemExit("source experiment candidates must remain unmapped and blocked")
    return dict(summary), list(blockers)


def validate_generator_runtime() -> None:
    actual = {
        "pandas": pd.__version__,
        "pyarrow": pa.__version__,
        "PyYAML": yaml.__version__,
    }
    if actual != GENERATOR_RUNTIME_VERSIONS:
        raise SystemExit(
            "generator runtime mismatch: "
            f"expected={GENERATOR_RUNTIME_VERSIONS}, actual={actual}; "
            "install docs/run287_p0_3_authority_census/requirements.txt"
        )


def require_audit_commit(repo_root: Path, audit_sha: str) -> None:
    completed = subprocess.run(
        ["git", "cat-file", "-e", f"{audit_sha}^{{commit}}"],
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(f"audit commit is unavailable: {audit_sha}")


def require_exact_keys(actual: Iterable[str], expected: Iterable[str], label: str) -> None:
    actual_set = set(actual)
    expected_set = set(expected)
    if actual_set != expected_set:
        raise ValueError(
            f"{label} mismatch: missing={sorted(expected_set - actual_set)}, "
            f"extra={sorted(actual_set - expected_set)}"
        )


def branch_live_identity_from_rows(value: Any) -> dict[str, tuple[str, bool]]:
    records: list[Mapping[str, Any]] = []

    def collect(item: Any) -> None:
        if isinstance(item, list):
            for child in item:
                collect(child)
        elif isinstance(item, Mapping):
            records.append(item)
        else:
            raise RuntimeError("invalid remote branch metadata payload")

    collect(value)
    result: dict[str, tuple[str, bool]] = {}
    for row in records:
        name = str(row.get("name") or "")
        commit = row.get("commit")
        sha = clean_sha(commit.get("sha") if isinstance(commit, Mapping) else "")
        protected = row.get("protected")
        if (
            not name
            or not sha
            or type(protected) is not bool
            or name in result
        ):
            raise RuntimeError("duplicate or invalid remote branch metadata row")
        result[name] = (sha, protected)
    return result


def live_branch_identity(repo_root: Path) -> dict[str, tuple[str, bool]]:
    pages = run_json(
        [
            "gh",
            "api",
            "--paginate",
            "--slurp",
            f"repos/{REPOSITORY}/branches?per_page=100",
        ],
        cwd=repo_root,
    )
    return branch_live_identity_from_rows(pages)


def source_branch_identity(census: Mapping[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in census.get("branches") or []:
        name = str(row.get("name") or "")
        sha = clean_sha(row.get("head_sha"))
        if not name or not sha or name in result:
            raise ValueError("source branch identity is invalid")
        result[name] = sha
    return result


def source_branch_live_identity(
    census: Mapping[str, Any],
) -> dict[str, tuple[str, bool]]:
    result: dict[str, tuple[str, bool]] = {}
    for row in census.get("branches") or []:
        name = str(row.get("name") or "")
        sha = clean_sha(row.get("head_sha"))
        protected = row.get("protected")
        if (
            not name
            or not sha
            or type(protected) is not bool
            or name in result
        ):
            raise ValueError("source branch live identity is invalid")
        result[name] = (sha, protected)
    return result


def source_pr_identity(census: Mapping[str, Any]) -> dict[int, tuple[str, str, str, str]]:
    result: dict[int, tuple[str, str, str, str]] = {}
    for row in census.get("pull_requests") or []:
        number = row.get("number")
        if type(number) is not int or number <= 0 or number in result:
            raise ValueError("source PR identity is invalid")
        result[number] = validated_pr_identity_tuple(
            row,
            head_field="head_sha",
            base_field="base_sha",
            state_field="state",
            updated_field="updated_at",
            label=f"source PR #{number}",
        )
    return result


PR_FIELDS = (
    "number,title,state,isDraft,headRefName,headRefOid,baseRefName,baseRefOid,"
    "mergeCommit,mergedAt,closedAt,updatedAt,reviewDecision,statusCheckRollup,"
    "latestReviews,closingIssuesReferences"
)


def collect_pr_supplement(repo_root: Path) -> list[dict[str, Any]]:
    rows = run_json(
        [
            "gh",
            "pr",
            "list",
            "--repo",
            REPOSITORY,
            "--state",
            "all",
            "--limit",
            "1000",
            "--json",
            PR_FIELDS,
        ],
        cwd=repo_root,
    )
    if not isinstance(rows, list) or len(rows) >= 1000:
        raise RuntimeError("PR supplement is missing or limit-capped")
    return rows


def supplement_pr_identity(rows: Iterable[Mapping[str, Any]]) -> dict[int, tuple[str, str, str, str]]:
    result: dict[int, tuple[str, str, str, str]] = {}
    for row in rows:
        number = row.get("number")
        if type(number) is not int or number <= 0 or number in result:
            raise ValueError("PR supplement identity is invalid")
        result[number] = validated_pr_identity_tuple(
            row,
            head_field="headRefOid",
            base_field="baseRefOid",
            state_field="state",
            updated_field="updatedAt",
            label=f"live PR #{number}",
        )
    return result


def git_lines(repo_root: Path, arguments: list[str]) -> list[str]:
    return [line for line in run(["git", *arguments], cwd=repo_root).splitlines() if line]


def git_branch_evidence(
    repo_root: Path, *, audit_sha: str, branch: str, head_sha: str
) -> dict[str, Any]:
    run(["git", "cat-file", "-e", f"{head_sha}^{{commit}}"], cwd=repo_root)
    merge_base = run(["git", "merge-base", audit_sha, head_sha], cwd=repo_root).strip()
    if not clean_sha(merge_base):
        raise RuntimeError(f"branch {branch} lacks a valid merge base")
    counts = run(
        ["git", "rev-list", "--left-right", "--count", f"{audit_sha}...{head_sha}"],
        cwd=repo_root,
    ).strip().split()
    if len(counts) != 2:
        raise RuntimeError(f"branch {branch} has invalid ancestry counts")
    behind_count, ahead_count = (int(value) for value in counts)
    metadata = run(
        ["git", "show", "-s", "--format=%cI%x1f%an", head_sha], cwd=repo_root
    ).strip().split("\x1f", maxsplit=1)
    if len(metadata) != 2:
        raise RuntimeError(f"branch {branch} has invalid commit metadata")
    changed_paths = git_lines(
        repo_root,
        ["diff", "--no-renames", "--name-only", f"{merge_base}..{head_sha}"],
    )
    workflow_paths = sorted(path for path in changed_paths if WORKFLOW_RE.search(path))
    data_model_paths = sorted(path for path in changed_paths if DATA_MODEL_RE.search(path))
    test_paths = sorted(path for path in changed_paths if TEST_RE.search(path))
    artifact_paths = sorted(path for path in changed_paths if ARTIFACT_RE.search(path))
    executable_paths = sorted(path for path in changed_paths if EXECUTABLE_RE.search(path))
    return {
        "merge_base_sha": merge_base,
        "ahead_count": ahead_count,
        "behind_count": behind_count,
        "last_commit_at": metadata[0],
        "author_or_agent": metadata[1],
        "changed_paths": changed_paths,
        "workflow_changes": workflow_paths,
        "data_or_model_changes": data_model_paths,
        "test_changes": test_paths,
        "artifact_references": artifact_paths,
        "executable_changes": executable_paths,
    }


def classify_branch(
    *,
    branch: str,
    evidence: Mapping[str, Any],
    associated_pr_rows: list[Mapping[str, Any]],
) -> tuple[str, str, str]:
    ahead = int(evidence["ahead_count"])
    if ahead == 0:
        return (
            "A",
            "already_integrated_or_fully_duplicate",
            "NO_MERGE; PRESERVE UNTIL SEPARATE CLEANUP APPROVAL",
        )
    text = " ".join(
        [branch]
        + [str(row.get("title") or "") for row in associated_pr_rows]
    )
    states = {str(row.get("state") or "").upper() for row in associated_pr_rows}
    closed_unmerged = any(
        str(row.get("state") or "").upper() == "CLOSED"
        and not row.get("merged_at")
        for row in associated_pr_rows
    )
    if SUPERSEDED_RE.search(text) or (closed_unmerged and "OPEN" not in states):
        return (
            "B",
            "failed_or_superseded_experiment",
            "QUARANTINE; NEVER AUTO-MERGE; CLEANUP REQUIRES SEPARATE APPROVAL",
        )
    executable = list(evidence["executable_changes"])
    workflows = list(evidence["workflow_changes"])
    tests = list(evidence["test_changes"])
    data_or_model = list(evidence["data_or_model_changes"])
    artifacts = list(evidence["artifact_references"])
    if (data_or_model or artifacts) and not executable and not workflows and not tests:
        return (
            "E",
            "data_model_or_artifact_value_only",
            "PRESERVE HASHED VALUE; DO NOT MERGE CODE OR PROMOTE RESULTS",
        )
    if ALPHA_RE.search(text):
        return (
            "D",
            "plausible_alpha_requiring_preregistration",
            "PREREGISTER ONE CAUSAL CHALLENGER; REQUIRE FRESH PIT VALIDATION",
        )
    if BUGFIX_RE.search(text):
        return (
            "C",
            "bug_fix_candidate_requiring_current_master_reconstruction",
            "RECONSTRUCT MINIMAL DIFF ON CURRENT MASTER; NEW PR AND EXACT-HEAD CHECKS",
        )
    return (
        "F",
        "unknown_lineage",
        "QUARANTINE; NEVER AUTO-MERGE; REQUIRE MANUAL LINEAGE RECOVERY",
    )


def normalize_check(row: Mapping[str, Any]) -> dict[str, Any]:
    if row.get("__typename") == "StatusContext":
        return {
            "type": "STATUS_CONTEXT",
            "name": str(row.get("context") or ""),
            "workflow": "",
            "status": str(row.get("state") or ""),
            "conclusion": str(row.get("state") or ""),
            "details_url": str(row.get("targetUrl") or ""),
        }
    return {
        "type": "CHECK_RUN",
        "name": str(row.get("name") or ""),
        "workflow": str(row.get("workflowName") or ""),
        "status": str(row.get("status") or ""),
        "conclusion": str(row.get("conclusion") or ""),
        "details_url": str(row.get("detailsUrl") or ""),
    }


def check_summary(checks: list[dict[str, Any]]) -> dict[str, Any]:
    conclusions = Counter(
        str(row.get("conclusion") or row.get("status") or "UNKNOWN").upper()
        for row in checks
    )
    required = {"validate", "portfolio_guard", "review_complete"}
    success_names = {
        row["name"] for row in checks if str(row.get("conclusion") or "").upper() == "SUCCESS"
    }
    return {
        "count": len(checks),
        "conclusion_counts": dict(sorted(conclusions.items())),
        "required_success_observed": required.issubset(success_names),
        "required_success_names": sorted(required & success_names),
    }


def validated_frozen_checks(
    supplement: Mapping[str, Any], number: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    checks = [dict(item) for item in supplement["checks"]]
    summary = check_summary(checks)
    if summary != supplement["check_summary"]:
        raise SystemExit(f"frozen PR check summary mismatch: #{number}")
    return checks, summary


def review_summary(row: Mapping[str, Any]) -> dict[str, Any]:
    reviews = []
    for item in row.get("latestReviews") or []:
        author = item.get("author") if isinstance(item.get("author"), dict) else {}
        reviews.append(
            {
                "author": str(author.get("login") or ""),
                "state": str(item.get("state") or ""),
                "submitted_at": str(item.get("submittedAt") or ""),
            }
        )
    reviews.sort(
        key=lambda item: (
            item["author"],
            item["state"],
            item["submitted_at"],
        )
    )
    states = Counter(item["state"] for item in reviews)
    return {
        "review_decision": str(row.get("reviewDecision") or "UNSPECIFIED"),
        "latest_review_count": len(reviews),
        "latest_review_state_counts": dict(sorted(states.items())),
        "latest_reviews": reviews,
        "unresolved_thread_state": "NOT_COLLECTED_FAIL_CLOSED",
    }


def supplement_pr_mutable_evidence(
    rows: Iterable[Mapping[str, Any]],
) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for row in rows:
        number = row.get("number")
        if type(number) is not int or number <= 0 or number in result:
            raise ValueError("PR supplement evidence identity is invalid")
        checks = sorted(
            (
                normalize_check(item)
                for item in row.get("statusCheckRollup") or []
            ),
            key=canonical_json,
        )
        result[number] = {
            "checks": checks,
            "check_summary": check_summary(checks),
            "review_state": review_summary(row),
            "closing_issue_numbers": sorted(
                int(item["number"])
                for item in row.get("closingIssuesReferences") or []
                if type(item.get("number")) is int and int(item["number"]) > 0
            ),
        }
    return result


def pr_disposition(row: Mapping[str, Any], checks: Mapping[str, Any]) -> str:
    state = str(row.get("state") or "").upper()
    if state == "MERGED":
        return "INTEGRATED_NO_FURTHER_MERGE"
    if state == "CLOSED":
        return "CLOSED_UNMERGED_QUARANTINE"
    if bool(row.get("is_draft")):
        return "OPEN_DRAFT_REVIEW_REQUIRED"
    if checks.get("required_success_observed"):
        return "OPEN_EXACT_HEAD_REVIEW_AND_DISPOSITION_REQUIRED"
    return "OPEN_BLOCKED_CHECKS_OR_REVIEW_REQUIRED"


def scalar_values(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for nested in value.values():
            yield from scalar_values(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from scalar_values(nested)


def workflow_steps(document: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    for job in (document.get("jobs") or {}).values():
        if not isinstance(job, Mapping):
            continue
        for step in job.get("steps") or []:
            if isinstance(step, Mapping):
                yield step


def permission_rows(document: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"workflow": document.get("permissions") or {}}
    jobs: dict[str, Any] = {}
    for job_name, job in (document.get("jobs") or {}).items():
        if isinstance(job, Mapping) and job.get("permissions"):
            jobs[str(job_name)] = job.get("permissions")
    result["jobs"] = jobs
    return result


def trigger_rows(document: Mapping[str, Any]) -> dict[str, Any]:
    trigger = document.get("on") or {}
    if isinstance(trigger, str):
        trigger = {trigger: {}}
    elif isinstance(trigger, list):
        trigger = {str(item): {} for item in trigger}
    if not isinstance(trigger, Mapping):
        raise ValueError("workflow trigger is malformed")
    schedules: list[str] = []
    schedule = trigger.get("schedule") or []
    if isinstance(schedule, list):
        schedules = [str(item.get("cron") or "") for item in schedule if isinstance(item, Mapping)]
    dispatch = trigger.get("workflow_dispatch") or {}
    dispatch_inputs = dispatch.get("inputs") or {} if isinstance(dispatch, Mapping) else {}
    inputs: list[dict[str, Any]] = []
    for name, item in dispatch_inputs.items():
        item = item if isinstance(item, Mapping) else {}
        inputs.append(
            {
                "name": str(name),
                "type": str(item.get("type") or "string"),
                "required": str(item.get("required") or "false").lower() == "true",
                "default": item.get("default"),
            }
        )
    return {
        "events": sorted(str(key) for key in trigger),
        "schedules": schedules,
        "workflow_dispatch_inputs": inputs,
    }


def artifact_upload_rows(steps: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for step in steps:
        if not str(step.get("uses") or "").startswith("actions/upload-artifact@"):
            continue
        with_values = step.get("with") if isinstance(step.get("with"), Mapping) else {}
        result.append(
            {
                "name": str(with_values.get("name") or ""),
                "path": str(with_values.get("path") or ""),
            }
        )
    return result


def workflow_git_blob(repo_root: Path, audit_sha: str, relative_path: str) -> str:
    value = run(["git", "rev-parse", f"{audit_sha}:{relative_path}"], cwd=repo_root).strip()
    if not SHA_RE.fullmatch(value):
        raise RuntimeError(f"workflow blob identity is invalid: {relative_path}")
    return value


def audited_workflow_paths(repo_root: Path, audit_sha: str) -> list[Path]:
    paths = git_lines(
        repo_root,
        [
            "ls-tree",
            "-r",
            "--name-only",
            audit_sha,
            "--",
            ".github/workflows",
        ],
    )
    workflows = sorted(
        path for path in paths if WORKFLOW_RE.fullmatch(path)
    )
    if not workflows:
        raise RuntimeError("audit commit has no workflow YAML files")
    return [repo_root / Path(path) for path in workflows]


def workflow_git_blob_bytes(repo_root: Path, audit_sha: str, relative_path: str) -> bytes:
    completed = subprocess.run(
        ["git", "cat-file", "blob", f"{audit_sha}:{relative_path}"],
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"workflow blob read failed: {relative_path}: "
            f"{completed.stderr.decode('utf-8', errors='replace').strip()}"
        )
    return completed.stdout


def scan_workflow(
    *,
    repo_root: Path,
    audit_sha: str,
    path: Path,
    policy: Mapping[str, Any],
    globals_policy: Mapping[str, Any],
) -> dict[str, Any]:
    relative = path.relative_to(repo_root).as_posix()
    blob_bytes = workflow_git_blob_bytes(repo_root, audit_sha, relative)
    raw = blob_bytes.decode("utf-8-sig")
    document = yaml.load(raw, Loader=yaml.BaseLoader)
    if not isinstance(document, Mapping):
        raise ValueError(f"workflow is not an object: {path.name}")
    steps = list(workflow_steps(document))
    runs = [str(step.get("run") or "") for step in steps if step.get("run")]
    uses = sorted({str(step.get("uses") or "") for step in steps if step.get("uses")})
    scalar_text = "\n".join(scalar_values(document))
    authority_lines = sorted(
        {
            line.strip()
            for block in runs
            for line in block.splitlines()
            if AUTHORITY_COMMAND_RE.search(line)
        }
    )
    output_paths = sorted({match.group(1) for block in runs for match in OUTPUT_ARG_RE.finditer(block)})
    long_expression_blocks = [
        {"length": len(block), "expression_count": block.count("${{")}
        for block in runs
        if "${{" in block and len(block) > 21_000
    ]
    permissions = permission_rows(document)
    permission_text = canonical_json(permissions).lower()
    contents_write = '"contents":"write"' in permission_text or bool(
        re.search(r"\bgit\s+push\b", "\n".join(runs), re.IGNORECASE)
    )
    target_reference = bool(re.search(r"target_book", scalar_text, re.IGNORECASE))
    ledger_reference = bool(
        re.search(r"simulated_fill_ledger|paper_archive|paper[-_ ]ledger", scalar_text, re.IGNORECASE)
    )
    broker_reference = bool(re.search(r"alpaca|live_trading|broker", scalar_text, re.IGNORECASE))
    broker_execution_command = bool(
        re.search(
            r"r1000_paper_executor|--execute\s+--confirm|submit_order|place_order",
            "\n".join(runs),
            re.IGNORECASE,
        )
    )
    promotion_reference = bool(re.search(r"promotion|champion", scalar_text, re.IGNORECASE))
    known_blocker = str(policy.get("known_blocker") or "")
    platform_blockers = []
    authority_blockers = list(policy.get("authority_blockers") or [])
    if known_blocker:
        platform_blockers.append(known_blocker)
    if long_expression_blocks:
        platform_blockers.append("STATIC_LONG_EXPRESSION_SCALAR_EXCEEDS_21000")
    return {
        "file": path.name,
        "path": relative,
        "display_name": str(document.get("name") or path.name),
        "workflow_blob_sha": workflow_git_blob(repo_root, audit_sha, relative),
        "workflow_sha256": hashlib.sha256(blob_bytes).hexdigest(),
        "trigger": trigger_rows(document),
        "job_count": len(document.get("jobs") or {}),
        "permissions": permissions,
        "secrets": sorted(set(SECRET_RE.findall(raw))),
        "variables": sorted(set(VAR_RE.findall(raw))),
        "actions": uses,
        "artifact_uploads": artifact_upload_rows(steps),
        "declared_output_paths": output_paths,
        "authority_command_evidence": authority_lines,
        "static_authority_references": {
            "target": target_reference,
            "paper_ledger": ledger_reference,
            "broker_or_live_named": broker_reference,
            "broker_execution_command": broker_execution_command,
            "promotion_or_champion": promotion_reference,
            "contents_write": contents_write,
            "rclone_write": bool(re.search(r"rclone\s+(?:copy|copyto|sync)", scalar_text, re.IGNORECASE)),
        },
        "declared_role": policy["declared_role"],
        "decision": policy["decision"],
        "target_authority": policy["target_authority"],
        "paper_ledger_authority": policy["paper_ledger_authority"],
        "durable_write_scope": policy["durable_write_scope"],
        "production_live_authority": policy.get(
            "production_live_authority", globals_policy["production_authority_default"]
        ),
        "model_promotion_authority": globals_policy["model_promotion_authority_default"],
        "human_approval_requirement": policy["human_approval_requirement"],
        "platform_validation_blockers": sorted(set(platform_blockers)),
        "authority_blockers": sorted(set(authority_blockers)),
        "long_expression_blocks": long_expression_blocks,
    }


def parquet_safe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        converted: dict[str, Any] = {}
        for key, value in row.items():
            if isinstance(value, (list, dict)):
                converted[key] = canonical_json(value)
            else:
                converted[key] = value
        result.append(converted)
    return result


def write_parquet(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(parquet_safe_rows(rows))
    frame.to_parquet(path, index=False, compression="zstd")
    reread = pd.read_parquet(path)
    if len(reread) != len(rows) or list(reread.columns) != list(frame.columns):
        raise RuntimeError(f"parquet round-trip failed: {path}")


def read_branch_supplement_bytes(content: bytes) -> dict[str, Any]:
    frame = pd.read_parquet(io.BytesIO(content))
    if frame.empty:
        raise ValueError("frozen branch supplement is empty")
    metadata_fields = (
        "schema_version",
        "audit_master_sha",
        "generated_at_utc",
        "branch_namespace_sha256",
    )
    metadata: dict[str, str] = {}
    for field in metadata_fields:
        values = {str(value) for value in frame[field]}
        if len(values) != 1:
            raise ValueError(f"frozen branch supplement {field} is not singular")
        metadata[field] = values.pop()
    rows = []
    for record in frame.to_dict(orient="records"):
        row = {
            "branch": str(record["branch"]),
            "tip_sha": str(record["tip_sha"]),
        }
        for field in BRANCH_EVIDENCE_FIELDS:
            value = record[field]
            if field in BRANCH_JSON_FIELDS:
                value = json.loads(str(value))
            elif field in {"ahead_count", "behind_count"}:
                value = int(value)
            row[field] = value
        rows.append(row)
    return {**metadata, "rows": rows}


def read_branch_supplement(path: Path) -> dict[str, Any]:
    return read_branch_supplement_bytes(path.read_bytes())


def write_branch_supplement(path: Path, document: Mapping[str, Any]) -> None:
    metadata = {
        field: document[field]
        for field in (
            "schema_version",
            "audit_master_sha",
            "generated_at_utc",
            "branch_namespace_sha256",
        )
    }
    rows = [{**metadata, **row} for row in document["rows"]]
    write_parquet(path, rows)


def write_registry(path: Path, registry: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = yaml.safe_dump(
        dict(registry),
        allow_unicode=True,
        sort_keys=False,
        width=120,
    )
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(serialized)


def write_readme(path: Path, summary: Mapping[str, Any]) -> None:
    counts = summary["counts"]
    classification = summary["branch_classification_counts"]
    decisions = summary["workflow_decision_counts"]
    source_artifact = summary["source_artifact"]
    source_pr_supplement = summary["source_pr_supplement_artifact"]
    source_branch_supplement = summary["source_branch_supplement_artifact"]
    source_policy = summary["source_workflow_policy_artifact"]
    runtime_requirements = summary["generator_runtime_requirements_artifact"]
    source_experiment = summary["source_experiment_completeness"]
    promotion_blockers = summary["source_promotion_blockers"]
    incomplete_pr_changed_paths = summary["evidence_limitations"][
        "incomplete_changed_path_prs"
    ]
    text = f"""# Run287 P0-3 authority census

This directory is the read-only census required by Issue #371.  The snapshot is
bound to `master` `{summary['audit_master_sha']}` and was observed at
`{summary['generated_at_utc']}`.

## Coverage

- Remote branches: `{counts['branches']}`
- Pull requests: `{counts['pull_requests']}`
- Workflow YAML files: `{counts['workflows']}`
- Branch classifications: `{canonical_json(classification)}`
- Workflow decisions: `{canonical_json(decisions)}`

## Reproducible source

The exact U0 GitHub input is tracked as
`{source_artifact['repository_path']}` (deterministic gzip, SHA-256
`{source_artifact['compressed_sha256']}`). The collector accepts this `.gz`
file directly; its decompressed SHA-256 is
`{source_artifact['uncompressed_sha256']}`.
Frozen normalized PR check/review metadata is tracked separately as
`{source_pr_supplement['repository_path']}` (SHA-256
`{source_pr_supplement['compressed_sha256']}`).
Frozen branch ancestry/path evidence is tracked as
`{source_branch_supplement['repository_path']}` (SHA-256
`{source_branch_supplement['sha256']}`).
The frozen workflow authority policy is tracked as
`{source_policy['repository_path']}` (SHA-256 `{source_policy['sha256']}`).
By default regeneration uses these four frozen sources;
`--verify-live-namespace` is reserved for the original generation-time
equality guard.

The byte-stable generator runtime is pinned in
`{runtime_requirements['repository_path']}` (SHA-256
`{runtime_requirements['sha256']}`):
`{canonical_json(summary['generator_runtime_versions'])}`.

## Evidence limitations

Changed-path collection is incomplete for PRs
`{canonical_json(incomplete_pr_changed_paths)}`. Their rows remain useful for
identity and disposition evidence, but they are not complete recovery-path
inventories and grant no merge or promotion authority.

The frozen U0 source reports historical experiment census completeness as
`{str(source_experiment['historical_experiment_census_complete']).lower()}` and
declares these promotion blockers:
`{canonical_json(promotion_blockers)}`. This authority census preserves those
blockers and does not replace experiment recovery, ancestry verification,
trial deduplication, or historical return evidence.

The publication branch and its PR did not exist in the captured namespace.  Their
creation is the expected publication-only delta and does not authorize cleanup,
workflow dispatch, a target/ledger mutation, fullrun, promotion, production, or
live trading.

## Authority result

- Official current US target writer: `daily_operating_selection_refresh.yml`
- Official simulated-fill paper-ledger consumer/writer: `daily_operating_selection_refresh.yml`
- Live broker writer: `NONE`
- Automatic model promotion authority: `NONE`

Every other target-, broker-, ledger-, or promotion-related workflow is recorded
as research-only, noncanonical, or blocked in `workflow_registry.yaml`.

## Fail-closed limits

- Branch classifications C/D/E are recovery or research dispositions, never merge authority.
- Class F remains quarantined and must never be auto-merged.
- PR review-thread resolution was not bulk-collected; open PRs remain review-required.
- No branch deletion, merge, workflow execution, fullrun, target/order/ledger write,
  champion change, production enablement, or live trading occurred.
"""
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-sha", required=True)
    parser.add_argument("--source-census", type=Path, required=True)
    parser.add_argument(
        "--source-pr-supplement",
        type=Path,
        help="Frozen normalized PR checks/review metadata; defaults beside source census.",
    )
    parser.add_argument(
        "--source-branch-supplement",
        type=Path,
        help="Frozen branch ancestry/path Parquet; defaults beside source census.",
    )
    parser.add_argument(
        "--verify-live-namespace",
        action="store_true",
        help="Generation-time guard: require the live branch/PR namespace to match U0 exactly.",
    )
    parser.add_argument(
        "--policy",
        type=Path,
        help="Frozen workflow authority policy; defaults beside source census.",
    )
    parser.add_argument(
        "--runtime-requirements",
        type=Path,
        help="Pinned generator requirements; defaults beside source census.",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    audit_sha = clean_sha(args.audit_sha)
    if not audit_sha:
        raise SystemExit("audit SHA must be exact")
    require_audit_commit(repo_root, audit_sha)
    source_bytes = document_bytes(args.source_census)
    require_bytes_sha256(
        source_bytes, FROZEN_U0_UNCOMPRESSED_SHA256, "frozen U0 source"
    )
    source = json.loads(source_bytes.decode("utf-8"))
    if source.get("schema_version") != U0_SCHEMA:
        raise SystemExit("source U0 census schema mismatch")
    if source.get("repository") != REPOSITORY:
        raise SystemExit("source repository mismatch")
    if clean_sha(source.get("audit_default_branch_sha")) != audit_sha:
        raise SystemExit("source census audit SHA mismatch")
    policy_input_path = args.policy or args.source_census.with_name(
        "source_workflow_authority_policy.json"
    )
    runtime_requirements_input_path = (
        args.runtime_requirements or args.source_census.with_name("requirements.txt")
    )
    policy_input_bytes = canonical_text_bytes(policy_input_path)
    runtime_requirements_input_bytes = canonical_text_bytes(
        runtime_requirements_input_path
    )
    require_bytes_sha256(
        policy_input_bytes, FROZEN_WORKFLOW_POLICY_SHA256, "frozen workflow policy"
    )
    require_bytes_sha256(
        runtime_requirements_input_bytes,
        FROZEN_RUNTIME_REQUIREMENTS_SHA256,
        "frozen runtime requirements",
    )
    policy = json.loads(policy_input_bytes.decode("utf-8"))
    validate_research_only_policy(policy, audit_sha)
    validate_runtime_requirements_bytes(runtime_requirements_input_bytes)
    validate_generator_runtime()
    source_summary, promotion_blockers = validate_u0_fail_closed_source(source)

    source_branches = source_branch_identity(source)
    source_live_branches = source_branch_live_identity(source)
    source_prs = source_pr_identity(source)
    source_pr_by_number = {int(row["number"]): row for row in source["pull_requests"]}
    live_branches_before: dict[str, tuple[str, bool]] | None = None
    supplement_before_identity: dict[int, tuple[str, str, str, str]] | None = None
    supplement_before_evidence: dict[int, dict[str, Any]] | None = None
    live_evidence_by_number: dict[int, dict[str, Any]] | None = None
    frozen_supplement_by_number: dict[int, dict[str, Any]] | None = None
    frozen_pr_supplement_document: dict[str, Any] | None = None
    frozen_pr_supplement_bytes: bytes | None = None
    frozen_branch_by_name: dict[str, dict[str, Any]] | None = None
    frozen_branch_supplement_document: dict[str, Any] | None = None
    frozen_branch_source_bytes: bytes | None = None

    if args.verify_live_namespace:
        live_branches_before = live_branch_identity(repo_root)
        if source_live_branches != live_branches_before:
            raise SystemExit(
                "branch namespace, head, or protection state moved after U0 collection"
            )
        pr_supplement_before = collect_pr_supplement(repo_root)
        supplement_before_identity = supplement_pr_identity(pr_supplement_before)
        if source_prs != supplement_before_identity:
            raise SystemExit("PR namespace or mutable identity moved after U0 collection")
        supplement_before_evidence = supplement_pr_mutable_evidence(
            pr_supplement_before
        )
        live_evidence_by_number = supplement_before_evidence
    else:
        frozen_branch_path = args.source_branch_supplement or args.source_census.with_name(
            "source_branch_supplement.parquet"
        )
        frozen_branch_source_bytes = frozen_branch_path.read_bytes()
        require_bytes_sha256(
            frozen_branch_source_bytes,
            FROZEN_BRANCH_SUPPLEMENT_SHA256,
            "frozen branch supplement",
        )
        frozen_branch_supplement_document = read_branch_supplement_bytes(
            frozen_branch_source_bytes
        )
        if (
            frozen_branch_supplement_document.get("schema_version")
            != BRANCH_SUPPLEMENT_SCHEMA
        ):
            raise SystemExit("frozen branch supplement schema mismatch")
        if clean_sha(
            frozen_branch_supplement_document.get("audit_master_sha")
        ) != audit_sha:
            raise SystemExit("frozen branch supplement audit SHA mismatch")
        if frozen_branch_supplement_document.get(
            "branch_namespace_sha256"
        ) != canonical_sha256(source_branches):
            raise SystemExit("frozen branch supplement namespace hash mismatch")
        frozen_branch_rows = frozen_branch_supplement_document.get("rows") or []
        frozen_branch_by_name = {
            str(row["branch"]): row
            for row in frozen_branch_rows
        }
        if len(frozen_branch_by_name) != len(frozen_branch_rows):
            raise SystemExit("frozen branch supplement contains duplicate branches")
        require_exact_keys(
            frozen_branch_by_name,
            source_branches,
            "frozen branch supplement coverage",
        )

        frozen_path = args.source_pr_supplement or args.source_census.with_name(
            "source_pr_supplement.json.gz"
        )
        frozen_pr_input_bytes = document_bytes(frozen_path)
        frozen_pr_supplement_document = json.loads(
            frozen_pr_input_bytes.decode("utf-8")
        )
        frozen_schema = frozen_pr_supplement_document.get("schema_version")
        if frozen_schema == LEGACY_PR_SUPPLEMENT_SCHEMA:
            if hashlib.sha256(frozen_pr_input_bytes).hexdigest() != (
                LEGACY_PR_SUPPLEMENT_SHA256
            ):
                raise SystemExit("untrusted legacy frozen PR supplement")
            for row in frozen_pr_supplement_document.get("rows") or []:
                source_row = source_pr_by_number[int(row["number"])]
                row.update(
                    {
                        "head_sha": source_row["head_sha"],
                        "base_sha": source_row["base_sha"],
                        "state": source_row["state"],
                        "updated_at": source_row["updated_at"],
                    }
                )
            frozen_pr_supplement_document["schema_version"] = PR_SUPPLEMENT_SCHEMA
        elif frozen_schema != PR_SUPPLEMENT_SCHEMA:
            raise SystemExit("frozen PR supplement schema mismatch")
        else:
            require_bytes_sha256(
                frozen_pr_input_bytes,
                FROZEN_PR_SUPPLEMENT_V2_UNCOMPRESSED_SHA256,
                "frozen PR supplement v2",
            )
        frozen_pr_supplement_bytes = (
            json.dumps(
                frozen_pr_supplement_document,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
            + "\n"
        ).encode("utf-8")
        require_bytes_sha256(
            frozen_pr_supplement_bytes,
            FROZEN_PR_SUPPLEMENT_V2_UNCOMPRESSED_SHA256,
            "canonical frozen PR supplement v2",
        )
        if clean_sha(frozen_pr_supplement_document.get("audit_master_sha")) != audit_sha:
            raise SystemExit("frozen PR supplement audit SHA mismatch")
        if frozen_pr_supplement_document.get(
            "pull_request_namespace_sha256"
        ) != canonical_sha256(source_prs):
            raise SystemExit("frozen PR supplement namespace hash mismatch")
        frozen_pr_rows = frozen_pr_supplement_document.get("rows") or []
        frozen_supplement_by_number = {}
        frozen_supplement_identity: dict[
            int, tuple[str, str, str, str]
        ] = {}
        for row in frozen_pr_rows:
            number = row.get("number")
            if type(number) is not int or number <= 0:
                raise SystemExit("frozen PR supplement contains an invalid PR number")
            frozen_supplement_by_number[number] = row
            frozen_supplement_identity[number] = validated_pr_identity_tuple(
                row,
                head_field="head_sha",
                base_field="base_sha",
                state_field="state",
                updated_field="updated_at",
                label=f"frozen PR #{number}",
            )
        if len(frozen_supplement_by_number) != len(frozen_pr_rows):
            raise SystemExit("frozen PR supplement contains duplicate PRs")
        require_exact_keys(
            (str(number) for number in frozen_supplement_by_number),
            (str(number) for number in source_prs),
            "frozen PR supplement coverage",
        )
        if frozen_supplement_identity != source_prs:
            raise SystemExit("frozen PR supplement mutable identity mismatch")

    issue_numbers_by_pr = {
        number: (
            list(frozen_supplement_by_number[number]["associated_issue"])
            if frozen_supplement_by_number is not None
            else sorted(
                set(live_evidence_by_number[number]["closing_issue_numbers"])
                | {
                    int(value)
                    for value in ISSUE_RE.findall(
                        str(source_pr_by_number[number].get("title") or "")
                    )
                }
            )
        )
        for number in source_pr_by_number
    }

    branch_rows: list[dict[str, Any]] = []
    for source_row in sorted(source["branches"], key=lambda row: row["name"]):
        branch = str(source_row["name"])
        head_sha = clean_sha(source_row["head_sha"])
        if frozen_branch_by_name is not None:
            frozen_branch = frozen_branch_by_name[branch]
            if clean_sha(frozen_branch.get("tip_sha")) != head_sha:
                raise SystemExit(f"frozen branch tip mismatch: {branch}")
            evidence = {
                field: frozen_branch[field] for field in BRANCH_EVIDENCE_FIELDS
            }
        else:
            evidence = git_branch_evidence(
                repo_root, audit_sha=audit_sha, branch=branch, head_sha=head_sha
            )
        pr_numbers = sorted(int(value) for value in source_row.get("linked_pr_numbers") or [])
        associated_pr_rows = [source_pr_by_number[number] for number in pr_numbers]
        issue_numbers = sorted(
            {
                issue
                for number in pr_numbers
                for issue in issue_numbers_by_pr[number]
            }
        )
        classification, classification_reason, recommendation = classify_branch(
            branch=branch,
            evidence=evidence,
            associated_pr_rows=associated_pr_rows,
        )
        branch_rows.append(
            {
                "branch": branch,
                "tip_sha": head_sha,
                **evidence,
                "associated_pr": pr_numbers,
                "associated_issue": issue_numbers,
                "classification": classification,
                "classification_reason": classification_reason,
                "recommended_action": recommendation,
                "protected": bool(source_row.get("protected")),
                "source_record_id": source_row.get("record_id"),
            }
        )

    if frozen_branch_supplement_document is None:
        frozen_branch_supplement_document = {
            "schema_version": BRANCH_SUPPLEMENT_SCHEMA,
            "audit_master_sha": audit_sha,
            "branch_namespace_sha256": canonical_sha256(source_branches),
            "rows": [
                {
                    "branch": row["branch"],
                    "tip_sha": row["tip_sha"],
                    **{field: row[field] for field in BRANCH_EVIDENCE_FIELDS},
                }
                for row in branch_rows
            ],
        }

    pr_rows: list[dict[str, Any]] = []
    for source_row in sorted(source["pull_requests"], key=lambda row: row["number"]):
        number = int(source_row["number"])
        if frozen_supplement_by_number is not None:
            supplement = frozen_supplement_by_number[number]
            checks, checks_summary = validated_frozen_checks(supplement, number)
            reviews = dict(supplement["review_state"])
        else:
            evidence = live_evidence_by_number[number]
            checks = [dict(item) for item in evidence["checks"]]
            checks_summary = dict(evidence["check_summary"])
            reviews = dict(evidence["review_state"])
        issues = issue_numbers_by_pr[number]
        row = {
            "number": number,
            "title": str(source_row.get("title") or ""),
            "state": str(source_row.get("state") or ""),
            "is_draft": bool(source_row.get("is_draft")),
            "head_branch": str(source_row.get("head_branch") or ""),
            "head_sha": clean_sha(source_row.get("head_sha")),
            "base_branch": str(source_row.get("base_branch") or ""),
            "base_sha": clean_sha(source_row.get("base_sha")),
            "merge_commit_sha": clean_sha(source_row.get("merge_commit_sha")),
            "created_at": str(source_row.get("created_at") or ""),
            "updated_at": str(source_row.get("updated_at") or ""),
            "merged_at": str(source_row.get("merged_at") or ""),
            "closed_at": str(source_row.get("closed_at") or ""),
            "author_or_agent": str(source_row.get("author_login") or ""),
            "associated_issue": issues,
            "changed_paths": list(source_row.get("changed_paths") or []),
            "changed_paths_complete": bool(source_row.get("changed_paths_complete")),
            "checks": checks,
            "check_summary": checks_summary,
            "review_state": reviews,
            "disposition": pr_disposition(source_row, checks_summary),
            "url": str(source_row.get("url") or ""),
        }
        pr_rows.append(row)

    if frozen_pr_supplement_document is None:
        frozen_pr_supplement_document = {
            "schema_version": PR_SUPPLEMENT_SCHEMA,
            "audit_master_sha": audit_sha,
            "pull_request_namespace_sha256": canonical_sha256(source_prs),
            "rows": [
                {
                    "number": row["number"],
                    "head_sha": row["head_sha"],
                    "base_sha": row["base_sha"],
                    "state": row["state"],
                    "updated_at": row["updated_at"],
                    "associated_issue": row["associated_issue"],
                    "checks": row["checks"],
                    "check_summary": row["check_summary"],
                    "review_state": row["review_state"],
                }
                for row in pr_rows
            ],
        }

    workflow_paths = audited_workflow_paths(repo_root, audit_sha)
    policy_rows = policy.get("workflows") or {}
    require_exact_keys(
        (path.name for path in workflow_paths), policy_rows.keys(), "workflow policy coverage"
    )
    workflows = [
        scan_workflow(
            repo_root=repo_root,
            audit_sha=audit_sha,
            path=path,
            policy=policy_rows[path.name],
            globals_policy=policy["global_guards"],
        )
        for path in workflow_paths
    ]
    official = policy["official_authority"]
    official_target = [
        row["file"] for row in workflows if row["target_authority"] == "OFFICIAL_CURRENT_US_TARGET_WRITER"
    ]
    official_ledger = [
        row["file"]
        for row in workflows
        if row["paper_ledger_authority"] == "OFFICIAL_SIMULATED_FILL_CONSUMER_AND_WRITER"
    ]
    if official_target != [official["us_target_writer_workflow"]]:
        raise SystemExit("official target writer is not singular")
    if official_ledger != [official["paper_ledger_consumer_workflow"]]:
        raise SystemExit("official paper ledger consumer is not singular")

    incomplete_pr_changed_paths = sorted(
        row["number"] for row in pr_rows if not row["changed_paths_complete"]
    )

    if args.verify_live_namespace:
        live_branches_after = live_branch_identity(repo_root)
        if live_branches_after != live_branches_before:
            raise SystemExit(
                "branch namespace, head, or protection state moved during P0-3 collection"
            )
        pr_supplement_after = collect_pr_supplement(repo_root)
        if supplement_pr_identity(pr_supplement_after) != supplement_before_identity:
            raise SystemExit("PR namespace or mutable identity moved during P0-3 collection")
        if (
            supplement_pr_mutable_evidence(pr_supplement_after)
            != supplement_before_evidence
        ):
            raise SystemExit("PR check, review, or issue evidence moved during P0-3 collection")
        remote_master = run(
            [
                "git",
                "ls-remote",
                f"https://github.com/{REPOSITORY}.git",
                "refs/heads/master",
            ],
            cwd=repo_root,
        ).split()[0]
        if remote_master != audit_sha:
            raise SystemExit("remote master moved during P0-3 collection")

    generated_at = resolve_generation_timestamp(
        frozen_pr_supplement_document,
        frozen_branch_supplement_document,
        verify_live_namespace=args.verify_live_namespace,
    )
    registry = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at,
        "repository": REPOSITORY,
        "audit_master_sha": audit_sha,
        "namespace_binding": {
            "branch_count": len(source_branches),
            "branch_identity_sha256": canonical_sha256(source_branches),
            "pull_request_count": len(source_prs),
            "pull_request_identity_sha256": canonical_sha256(source_prs),
            "workflow_count": len(workflows),
            "workflow_identity_sha256": canonical_sha256(
                [
                    {
                        "path": row["path"],
                        "blob_sha": row["workflow_blob_sha"],
                        "sha256": row["workflow_sha256"],
                    }
                    for row in workflows
                ]
            ),
            "publication_delta": "THIS_CENSUS_BRANCH_AND_PR_ABSENT_AT_SNAPSHOT_EXPECTED",
        },
        "global_guards": policy["global_guards"],
        "official_authority": official,
        "workflows": workflows,
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    branch_path = args.output_dir / "branch_census.parquet"
    pr_path = args.output_dir / "pr_census.parquet"
    registry_path = args.output_dir / "workflow_registry.yaml"
    source_artifact_path = args.output_dir / "source_u0_github_census.json.gz"
    source_pr_supplement_path = args.output_dir / "source_pr_supplement.json.gz"
    source_branch_supplement_path = args.output_dir / "source_branch_supplement.parquet"
    source_policy_path = args.output_dir / "source_workflow_authority_policy.json"
    runtime_requirements_path = args.output_dir / "requirements.txt"
    write_parquet(branch_path, branch_rows)
    write_parquet(pr_path, pr_rows)
    write_registry(registry_path, registry)
    write_gzip(source_artifact_path, source_bytes)
    if frozen_pr_supplement_bytes is None:
        frozen_pr_supplement_bytes = (
            json.dumps(
                frozen_pr_supplement_document,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
            + "\n"
        ).encode("utf-8")
    write_gzip(source_pr_supplement_path, frozen_pr_supplement_bytes)
    if frozen_branch_source_bytes is None:
        write_branch_supplement(
            source_branch_supplement_path, frozen_branch_supplement_document
        )
    else:
        source_branch_supplement_path.write_bytes(frozen_branch_source_bytes)
    source_policy_path.write_bytes(policy_input_bytes)
    runtime_requirements_path.write_bytes(runtime_requirements_input_bytes)
    source_repository_path = (
        CENSUS_REPOSITORY_DIR / source_artifact_path.name
    ).as_posix()
    source_pr_supplement_repository_path = (
        CENSUS_REPOSITORY_DIR / source_pr_supplement_path.name
    ).as_posix()
    source_branch_supplement_repository_path = (
        CENSUS_REPOSITORY_DIR / source_branch_supplement_path.name
    ).as_posix()
    source_policy_repository_path = (
        CENSUS_REPOSITORY_DIR / source_policy_path.name
    ).as_posix()
    runtime_requirements_repository_path = (
        CENSUS_REPOSITORY_DIR / runtime_requirements_path.name
    ).as_posix()

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at,
        "repository": REPOSITORY,
        "audit_master_sha": audit_sha,
        "source_artifact": {
            "repository_path": source_repository_path,
            "media_type": "application/gzip",
            "compressed_bytes": source_artifact_path.stat().st_size,
            "compressed_sha256": file_sha256(source_artifact_path),
            "uncompressed_bytes": len(source_bytes),
            "uncompressed_sha256": hashlib.sha256(source_bytes).hexdigest(),
        },
        "source_pr_supplement_artifact": {
            "repository_path": source_pr_supplement_repository_path,
            "media_type": "application/gzip",
            "compressed_bytes": source_pr_supplement_path.stat().st_size,
            "compressed_sha256": file_sha256(source_pr_supplement_path),
            "uncompressed_bytes": len(frozen_pr_supplement_bytes),
            "uncompressed_sha256": hashlib.sha256(
                frozen_pr_supplement_bytes
            ).hexdigest(),
        },
        "source_branch_supplement_artifact": {
            "repository_path": source_branch_supplement_repository_path,
            "media_type": "application/vnd.apache.parquet",
            "bytes": source_branch_supplement_path.stat().st_size,
            "sha256": file_sha256(source_branch_supplement_path),
            "rows": len(frozen_branch_supplement_document["rows"]),
        },
        "source_workflow_policy_artifact": {
            "repository_path": source_policy_repository_path,
            "media_type": "application/json",
            "bytes": source_policy_path.stat().st_size,
            "sha256": file_sha256(source_policy_path),
        },
        "generator_runtime_requirements_artifact": {
            "repository_path": runtime_requirements_repository_path,
            "media_type": "text/plain",
            "bytes": runtime_requirements_path.stat().st_size,
            "sha256": file_sha256(runtime_requirements_path),
        },
        "generator_runtime_versions": GENERATOR_RUNTIME_VERSIONS,
        "source_experiment_completeness": {
            "historical_experiment_census_complete": source_summary[
                "historical_experiment_census_complete"
            ],
            "historical_challenger_allowed": source_summary.get(
                "historical_challenger_allowed"
            ),
            "unmapped_experiment_candidate_count": source_summary.get(
                "unmapped_experiment_candidate_count"
            ),
        },
        "source_promotion_blockers": list(promotion_blockers),
        "counts": {
            "branches": len(branch_rows),
            "pull_requests": len(pr_rows),
            "workflows": len(workflows),
        },
        "evidence_limitations": {
            "all_pr_changed_paths_complete": not incomplete_pr_changed_paths,
            "incomplete_changed_path_prs": incomplete_pr_changed_paths,
        },
        "branch_classification_counts": dict(
            sorted(Counter(row["classification"] for row in branch_rows).items())
        ),
        "pr_state_counts": dict(sorted(Counter(row["state"] for row in pr_rows).items())),
        "pr_disposition_counts": dict(
            sorted(Counter(row["disposition"] for row in pr_rows).items())
        ),
        "workflow_decision_counts": dict(
            sorted(Counter(row["decision"] for row in workflows).items())
        ),
        "authority_findings": {
            "official_target_writers": official_target,
            "official_paper_ledger_consumers": official_ledger,
            "live_broker_writers": [],
            "automatic_model_promotion_writers": [],
            "noncanonical_or_research_target_references": sorted(
                row["file"]
                for row in workflows
                if row["static_authority_references"]["target"]
                and row["file"] not in official_target
            ),
            "contents_write_workflows": sorted(
                row["file"]
                for row in workflows
                if row["static_authority_references"]["contents_write"]
            ),
            "rclone_write_workflows": sorted(
                row["file"]
                for row in workflows
                if row["static_authority_references"]["rclone_write"]
            ),
            "nonofficial_paper_ledger_references": sorted(
                row["file"]
                for row in workflows
                if row["static_authority_references"]["paper_ledger"]
                and row["file"] not in official_ledger
            ),
            "broker_or_live_named_workflows": sorted(
                row["file"]
                for row in workflows
                if row["static_authority_references"]["broker_or_live_named"]
            ),
            "noncanonical_broker_execution_paths": sorted(
                row["file"]
                for row in workflows
                if row["static_authority_references"]["broker_execution_command"]
                and row["production_live_authority"] != "AUTHORIZED"
            ),
            "promotion_or_champion_reference_workflows": sorted(
                row["file"]
                for row in workflows
                if row["static_authority_references"]["promotion_or_champion"]
            ),
            "platform_blocked_workflows": sorted(
                row["file"] for row in workflows if row["platform_validation_blockers"]
            ),
            "authority_blocked_workflows": sorted(
                row["file"] for row in workflows if row["authority_blockers"]
            ),
        },
        "source_hashes": {
            "source_u0_census_sha256": hashlib.sha256(source_bytes).hexdigest(),
            "source_pr_supplement_sha256": hashlib.sha256(
                frozen_pr_supplement_bytes
            ).hexdigest(),
            "source_branch_supplement_sha256": file_sha256(
                source_branch_supplement_path
            ),
            "workflow_policy_sha256": file_sha256(source_policy_path),
            "generator_runtime_requirements_sha256": file_sha256(
                runtime_requirements_path
            ),
            "branch_namespace_sha256": canonical_sha256(source_branches),
            "pull_request_namespace_sha256": canonical_sha256(source_prs),
        },
        "output_hashes": {
            "branch_census.parquet": file_sha256(branch_path),
            "pr_census.parquet": file_sha256(pr_path),
            "workflow_registry.yaml": file_sha256(registry_path),
            "source_u0_github_census.json.gz": file_sha256(source_artifact_path),
            "source_pr_supplement.json.gz": file_sha256(source_pr_supplement_path),
            "source_branch_supplement.parquet": file_sha256(
                source_branch_supplement_path
            ),
            "source_workflow_authority_policy.json": file_sha256(
                source_policy_path
            ),
            "requirements.txt": file_sha256(runtime_requirements_path),
        },
        "safety": {
            "metadata_only": True,
            "branch_merge_delete_or_history_rewrite": False,
            "workflow_dispatched": False,
            "fullrun_executed": False,
            "target_order_or_ledger_mutated": False,
            "champion_or_production_changed": False,
            "live_trading_enabled": False,
        },
        "completeness": {
            "every_visible_branch_classified": len(branch_rows) == len(source_branches),
            "every_visible_pr_dispositioned": len(pr_rows) == len(source_prs),
            "all_pr_changed_paths_complete": not incomplete_pr_changed_paths,
            "every_workflow_profiled": len(workflows) == len(policy_rows),
            "open_pr_review_threads_bulk_collected": False,
            "unknown_lineage_fail_closed": True,
            "publication_branch_and_pr_expected_delta": True,
            "historical_experiment_census_complete": source_summary[
                "historical_experiment_census_complete"
            ],
        },
    }
    write_readme(args.output_dir / "README.md", summary)
    summary["output_hashes"]["README.md"] = file_sha256(
        args.output_dir / "README.md"
    )
    write_json(args.output_dir / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
