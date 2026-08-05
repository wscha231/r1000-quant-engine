#!/usr/bin/env python3
"""Build a fail-closed GitHub branch/PR census for Run287 research history.

This exporter enumerates repository branches and pull requests at one pinned
default-branch commit.  It identifies likely research capabilities, preserves
immutable GitHub locators, and reports every experiment-like record that still
lacks a canonical trial identity.  It never authorizes a historical challenger,
runs a backtest, mutates a portfolio, or changes a champion.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


REPOSITORY = "wscha231/r1000-quant-engine"
SCHEMA_VERSION = "run287-u0-v2-github-census-v1"
COLLECTION_CACHE_SCHEMA_VERSION = "run287-u0-v2-github-collection-cache-v3"
COLLECTION_IDENTITY_SNAPSHOT_SOURCE = (
    "GITHUB_NAMESPACE_AND_MUTABLE_EVIDENCE_PINNED_V1"
)
SHA_RE = re.compile(r"[0-9a-f]{40}")
EXPERIMENT_PATH_RE = re.compile(
    r"(^|/)(backtest|research|aggressive|auto_learning|experiments?)(/|$)|"
    r"(challenger|replay|selector|scor|target|promotion|experiment|"
    r"relative_strength|sector|crisis|reserve|form4|13f|fundamental|"
    r"earnings|actual_results|rolling_review|ohlcv|execution_cost|broker)",
    re.IGNORECASE,
)
KNOWN_REGISTRY_OUTSIDE_EXPERIMENT_PRS = frozenset({229, 230, 237})
EXPERIMENT_TEXT_RE = re.compile(
    r"\b(backtest|challenger|experiments?|ablation|grid|sweep|alpha|"
    r"relative strength|sector leadership|crisis|reserve|form 4|13f|"
    r"fundamental|earnings|ohlcv|expected return|cagr|mdd)\b",
    re.IGNORECASE,
)
BRANCH_EXPERIMENT_NAME_RE = re.compile(
    r"(^|[-_./\\])(backtest|research|aggressive|auto[-_./\\]?learning|"
    r"experiments?|challenger|replay|selector|scor(?:e|ing)?|target|"
    r"promotion(?:[-_./\\]?test)?|relative[-_./\\]?strength|sector|"
    r"crisis|reserve|form4|13f|fundamental|earnings|"
    r"actual[-_./\\]?results|rolling[-_./\\]?review|ohlcv|"
    r"execution[-_./\\]?cost|broker)([-_./\\]|$)",
    re.IGNORECASE,
)
CAPABILITY_RULES: dict[str, tuple[str, ...]] = {
    "EXPECTED_RETURN_AND_SCORING": (
        "expected return", "scor", "selector", "prediction", "alpha",
    ),
    "RELATIVE_STRENGTH_AND_LEADERSHIP": (
        "relative strength", "relative_strength", "sector", "leadership",
        "leader", "rs_",
    ),
    "RISK_CASH_AND_CRISIS": (
        "crisis", "risk", "reserve", "cash", "drawdown", "reentry",
    ),
    "FUNDAMENTAL_EARNINGS_AND_SEC": (
        "fundamental", "earnings", "estimate", "form4", "form 4", "13f",
        "sec_",
    ),
    "EXECUTION_COST_AND_LEDGER": (
        "broker", "ledger", "execution", "slippage", "turnover", "cost",
        "target_book",
    ),
    "PIT_DATA_AND_INTEGRITY": (
        "pit", "exact_close", "exact-close", "freshness", "manifest",
        "integrity", "lifecycle",
    ),
    "LEARNING_PROMOTION_AND_ROLLBACK": (
        "learning", "outcome", "promotion", "rollback", "champion",
        "challenger",
    ),
}


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, nested in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = nested
    return value


def read_json(path: Path) -> Any:
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicate_json_keys,
    )


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def run_json(command: list[str]) -> Any:
    # GitHub metadata reads are safe to retry.  Keep the bound explicit and do
    # not apply this helper to any mutation or ledger operation.
    for attempt in range(3):
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if completed.returncode == 0:
            return json.loads(completed.stdout)
        if attempt < 2:
            time.sleep(0.25 * (attempt + 1))
    raise RuntimeError("GitHub metadata command failed after two retries")


def collect_repository(repository: str) -> dict[str, Any]:
    return run_json(["gh", "api", f"repos/{repository}"])


def collect_remote_branch_sha(repository: str, branch: str) -> str:
    """Read one remote ref without consuming the REST metadata quota."""
    if repository != REPOSITORY:
        raise ValueError("remote Git repository identity mismatch")
    remote_url = f"https://github.com/{repository}.git"
    for attempt in range(3):
        completed = subprocess.run(
            [
                "git", "ls-remote", "--exit-code", remote_url,
                f"refs/heads/{branch}",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if completed.returncode == 0:
            sha = clean_sha(completed.stdout.split()[0] if completed.stdout.split() else "")
            if sha:
                return sha
        if attempt < 2:
            time.sleep(0.25 * (attempt + 1))
    raise RuntimeError("remote Git branch lookup failed after two retries")


def collect_remote_branch_identity(repository: str) -> dict[str, str]:
    if repository != REPOSITORY:
        raise ValueError("remote Git repository identity mismatch")
    remote_url = f"https://github.com/{repository}.git"
    for attempt in range(3):
        completed = subprocess.run(
            ["git", "ls-remote", "--heads", remote_url],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if completed.returncode == 0:
            identity: dict[str, str] = {}
            valid = True
            for line in completed.stdout.splitlines():
                fields = line.split(maxsplit=1)
                if len(fields) != 2 or not fields[1].startswith("refs/heads/"):
                    valid = False
                    break
                sha = clean_sha(fields[0])
                name = fields[1][len("refs/heads/"):]
                if not sha or not name or name in identity:
                    valid = False
                    break
                identity[name] = sha
            if valid:
                return identity
        if attempt < 2:
            time.sleep(0.25 * (attempt + 1))
    raise RuntimeError("remote Git branch snapshot failed after two retries")


def rest_branch_identity(pages: Any) -> dict[str, str]:
    if not isinstance(pages, list) or not all(
        isinstance(page, list) for page in pages
    ):
        raise RuntimeError("REST branch pagination payload is invalid")
    identity: dict[str, str] = {}
    for item in (row for page in pages for row in page):
        if not isinstance(item, dict):
            raise RuntimeError("REST branch pagination row is invalid")
        name = str(item.get("name") or "")
        commit = item.get("commit") if isinstance(item.get("commit"), dict) else {}
        sha = clean_sha(commit.get("sha"))
        if not name or not sha or name in identity:
            raise RuntimeError("REST branch pagination has invalid identities")
        identity[name] = sha
    return identity


def collect_branches(repository: str) -> list[dict[str, Any]]:
    identity_before = collect_remote_branch_identity(repository)
    pages = run_json(
        [
            "gh", "api", "--paginate", "--slurp",
            f"repos/{repository}/branches?per_page=100",
        ]
    )
    identity_after = collect_remote_branch_identity(repository)
    identity_rest = rest_branch_identity(pages)
    if identity_before != identity_rest or identity_after != identity_rest:
        raise RuntimeError("branch namespace moved during paginated collection")
    return [item for page in pages for item in page]


def graphql_pr_identity(
    rows: Any,
) -> dict[int, tuple[str, str, str, str, str, str]]:
    if not isinstance(rows, list) or len(rows) >= 1000:
        raise RuntimeError("PR identity snapshot is invalid or limit-capped")
    identity: dict[int, tuple[str, str, str, str, str, str]] = {}
    for item in rows:
        if not isinstance(item, dict):
            raise RuntimeError("PR identity snapshot row is invalid")
        number = item.get("number")
        if (
            not isinstance(number, int)
            or isinstance(number, bool)
            or number <= 0
            or number in identity
        ):
            raise RuntimeError("PR identity snapshot contains invalid identities")
        if any(
            field not in item or not isinstance(item.get(field), str)
            for field in ("title", "body", "headRefName", "baseRefName")
        ):
            raise RuntimeError("PR identity snapshot lacks explicit evidence fields")
        base_sha = clean_sha(item.get("baseRefOid"))
        base_name = str(item.get("baseRefName") or "")
        if not base_sha or not base_name:
            raise RuntimeError("PR identity snapshot has invalid base identity")
        identity[number] = (
            clean_sha(item.get("headRefOid")),
            str(item.get("title") or ""),
            str(item.get("body") or ""),
            str(item.get("headRefName") or ""),
            base_sha,
            base_name,
        )
    return identity


def rest_pr_identity(
    pages: Any,
) -> dict[int, tuple[str, str, str, str, str, str]]:
    if not isinstance(pages, list) or not all(
        isinstance(page, list) for page in pages
    ):
        raise RuntimeError("REST PR pagination payload is invalid")
    identity: dict[int, tuple[str, str, str, str, str, str]] = {}
    for item in (row for page in pages for row in page):
        if not isinstance(item, dict):
            raise RuntimeError("REST PR pagination row is invalid")
        number = item.get("number")
        if (
            not isinstance(number, int)
            or isinstance(number, bool)
            or number <= 0
            or number in identity
        ):
            raise RuntimeError("REST PR pagination contains invalid identities")
        head = item.get("head") if isinstance(item.get("head"), dict) else {}
        base = item.get("base") if isinstance(item.get("base"), dict) else {}
        base_sha = clean_sha(base.get("sha"))
        base_name = str(base.get("ref") or "")
        if not base_sha or not base_name:
            raise RuntimeError("REST PR pagination has invalid base identity")
        identity[number] = (
            clean_sha(head.get("sha")),
            str(item.get("title") or ""),
            str(item.get("body") or ""),
            str(head.get("ref") or ""),
            base_sha,
            base_name,
        )
    return identity


def collect_pull_requests(repository: str) -> list[dict[str, Any]]:
    # A single ``gh pr list --limit 1000`` query with nested files, commits,
    # reviews, and checks exceeds GitHub's 500k potential-node GraphQL cap for
    # this repository.  Enumerate the immutable PR identity fields through the
    # paginated REST collection and resolve changed paths from the pinned Git
    # objects below.  Review/check state is deliberately outside this census;
    # it belongs to the per-PR merge gate, not experiment identity.
    identity_before_rows = run_json(
        [
            "gh", "pr", "list", "--repo", repository, "--state", "all",
            "--limit", "1000", "--json",
            "number,headRefOid,title,body,headRefName,baseRefOid,baseRefName",
        ]
    )
    identity_before = graphql_pr_identity(identity_before_rows)
    pages = run_json(
        [
            "gh", "api", "--paginate", "--slurp",
            f"repos/{repository}/pulls?state=all&per_page=100",
        ]
    )
    status_rows = run_json(
        [
            "gh", "pr", "list", "--repo", repository, "--state", "all",
            "--limit", "1000", "--json",
            "number,state,isDraft,mergeCommit,mergedAt,closedAt,headRefOid,"
            "title,body,headRefName,baseRefOid,baseRefName",
        ]
    )
    identity_after = graphql_pr_identity(status_rows)
    identity_rest = rest_pr_identity(pages)
    if identity_before != identity_rest or identity_after != identity_rest:
        raise RuntimeError("PR namespace moved during paginated collection")
    status_by_number = {
        int(item.get("number") or 0): item
        for item in status_rows
        if isinstance(item, dict) and int(item.get("number") or 0) > 0
    }
    rows: list[dict[str, Any]] = []
    for raw in (item for page in pages for item in page):
        head = raw.get("head") if isinstance(raw.get("head"), dict) else {}
        base = raw.get("base") if isinstance(raw.get("base"), dict) else {}
        user = raw.get("user") if isinstance(raw.get("user"), dict) else {}
        number = int(raw.get("number") or 0)
        status = status_by_number.get(number, {})
        captured_head = clean_sha(head.get("sha"))
        status_head = clean_sha(status.get("headRefOid"))
        status_head_matches = bool(
            status and status_head and captured_head and status_head == captured_head
        )
        pinned_status = status if status_head_matches else {}
        status_merge = (
            pinned_status.get("mergeCommit")
            if isinstance(pinned_status.get("mergeCommit"), dict)
            else {}
        )
        merge_sha = clean_sha(
            status_merge.get("oid") or raw.get("merge_commit_sha")
        )
        rows.append(
            {
                "number": number,
                "title": raw.get("title"),
                "state": pinned_status.get("state") or raw.get("state"),
                "isDraft": bool(pinned_status.get("isDraft", raw.get("draft"))),
                "headRefName": head.get("ref"),
                "headRefOid": head.get("sha"),
                "baseRefName": base.get("ref"),
                "baseRefOid": base.get("sha"),
                "mergeCommit": {"oid": merge_sha} if merge_sha else None,
                "mergedAt": pinned_status.get("mergedAt") or raw.get("merged_at"),
                "closedAt": pinned_status.get("closedAt") or raw.get("closed_at"),
                "createdAt": raw.get("created_at"),
                "updatedAt": raw.get("updated_at"),
                "author": {"login": user.get("login")},
                "labels": raw.get("labels") or [],
                "url": raw.get("html_url"),
                "body": raw.get("body") or "",
                "files": [],
                "changedFiles": -1,
                "changedFilesGraphql": None,
                "changedPathsSource": "UNRESOLVED_BLOCKED",
                "commitCount": raw.get("commits"),
                "statusMetadataHeadOid": status_head,
                "statusMetadataHeadMatches": status_head_matches,
                "statusMetadataSource": (
                    "GRAPHQL_STATUS_HEAD_PINNED"
                    if status_head_matches
                    else "REST_ONLY_STATUS_HEAD_DRIFT_BLOCKED"
                ),
            }
        )
    return rows


def enrich_remote_changed_paths(
    repository: str,
    pull_requests: list[dict[str, Any]],
) -> None:
    """Resolve PR paths from the API while pinning both sides to one PR.

    GitHub caps the PR-files endpoint at 3,000 files.  The PR detail endpoint's
    ``changed_files`` count is therefore retained as the authoritative count;
    equality with the fetched unique paths is required downstream.  Open PRs
    can advance or be retargeted while the census runs, so detail is read both
    before and after pagination and any head or base drift remains unresolved.
    """
    if len(pull_requests) > 1:
        # Eight workers keep the audit practical without approaching GitHub's
        # core REST concurrency/rate limits.  Each worker owns exactly one row;
        # final artifacts are sorted later, so scheduling cannot affect bytes.
        with ThreadPoolExecutor(max_workers=8) as executor:
            list(
                executor.map(
                    lambda row: enrich_remote_changed_paths(repository, [row]),
                    pull_requests,
                )
            )
        return
    for raw in pull_requests:
        number = int(raw.get("number") or 0)
        if number <= 0:
            continue
        captured_head = clean_sha(raw.get("headRefOid"))
        captured_base = clean_sha(raw.get("baseRefOid"))
        if not captured_head or not captured_base:
            continue
        try:
            detail_before = run_json(
                ["gh", "api", f"repos/{repository}/pulls/{number}"]
            )
            before_head = clean_sha(
                ((detail_before.get("head") or {}).get("sha"))
            )
            before_base = clean_sha(
                ((detail_before.get("base") or {}).get("sha"))
            )
            detail_count = int(detail_before.get("changed_files"))
            if (
                before_head != captured_head
                or before_base != captured_base
                or detail_count < 0
            ):
                continue
            pages = run_json(
                [
                    "gh", "api", "--paginate", "--slurp",
                    f"repos/{repository}/pulls/{number}/files?per_page=100",
                ]
            )
            detail_after = run_json(
                ["gh", "api", f"repos/{repository}/pulls/{number}"]
            )
            after_head = clean_sha(
                ((detail_after.get("head") or {}).get("sha"))
            )
            after_base = clean_sha(
                ((detail_after.get("base") or {}).get("sha"))
            )
            after_count = int(detail_after.get("changed_files"))
        except (RuntimeError, TypeError, ValueError):
            continue
        if (
            after_head != captured_head
            or after_base != captured_base
            or after_count != detail_count
        ):
            continue
        paths = sorted(
            {
                str(item.get("filename") or "")
                for page in pages
                for item in page
                if isinstance(item, dict) and str(item.get("filename") or "")
            }
        )
        renamed_from_paths = sorted(
            {
                str(item.get("previous_filename") or "")
                for page in pages
                for item in page
                if isinstance(item, dict)
                and str(item.get("previous_filename") or "")
            }
        )
        graphql_count: int | None = None
        if detail_count == 0 and paths:
            try:
                graphql_detail = run_json(
                    [
                        "gh", "pr", "view", str(number), "--repo", repository,
                        "--json", "changedFiles,headRefOid,baseRefOid",
                    ]
                )
                if (
                    clean_sha(graphql_detail.get("headRefOid")) != captured_head
                    or clean_sha(graphql_detail.get("baseRefOid"))
                    != captured_base
                ):
                    continue
                graphql_count = int(graphql_detail.get("changedFiles") or 0)
            except (RuntimeError, TypeError, ValueError):
                # A zero detail count conflicts with returned paths.  Without
                # an independently pinned positive GraphQL count it remains
                # incomplete; never synthesize the count from the path list.
                graphql_count = None
        # The REST detail count is authoritative.  A GraphQL read is retained
        # only as contradiction evidence; it must never repair a conflicting
        # zero count by replacing it with the fetched path length.
        declared_count = detail_count
        cap_reached = len(paths) >= 3000
        declared_mismatch = declared_count != len(paths)
        raw["files"] = [{"path": path} for path in paths]
        raw["renamedFromPaths"] = [
            {"path": path} for path in renamed_from_paths
        ]
        raw["changedFiles"] = declared_count
        raw["changedFilesGraphql"] = graphql_count
        raw["changedFilesDetail"] = detail_count
        raw["changedPathsComplete"] = not cap_reached and not declared_mismatch
        raw["changedPathsApiCapReached"] = cap_reached
        raw["changedPathsSource"] = "GITHUB_HEAD_AND_BASE_PINNED_PR_FILES_API"
        raw["changedPathsHeadBefore"] = before_head
        raw["changedPathsHeadAfter"] = after_head
        raw["changedPathsBaseBefore"] = before_base
        raw["changedPathsBaseAfter"] = after_base


def collect_local_ancestry(
    *, audit_sha: str, shas: Iterable[str]
) -> dict[str, str]:
    results: dict[str, str] = {}
    for sha in sorted({clean_sha(value) for value in shas if clean_sha(value)}):
        if sha == audit_sha:
            results[sha] = "ANCESTOR_OF_AUDIT_HEAD"
            continue
        exists = subprocess.run(
            ["git", "cat-file", "-e", f"{sha}^{{commit}}"],
            capture_output=True,
            check=False,
        )
        if exists.returncode != 0:
            continue
        ancestry = subprocess.run(
            ["git", "merge-base", "--is-ancestor", sha, audit_sha],
            capture_output=True,
            check=False,
        )
        if ancestry.returncode == 0:
            results[sha] = "ANCESTOR_OF_AUDIT_HEAD"
        elif ancestry.returncode == 1:
            results[sha] = "ORPHANED_FROM_AUDIT_HEAD"
    return results


def clean_sha(value: Any) -> str:
    text = str(value or "").lower()
    return text if SHA_RE.fullmatch(text) else ""


def path_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return sorted(
        {
            str(item.get("path") or "")
            for item in raw
            if isinstance(item, dict) and str(item.get("path") or "")
        }
    )


def capability_families(text: str, paths: Iterable[str]) -> list[str]:
    haystack = re.sub(r"[-_./\\]+", " ", " ".join([text, *paths]).lower())
    return sorted(
        family
        for family, needles in CAPABILITY_RULES.items()
        if any(
            re.sub(r"[-_./\\]+", " ", needle.lower()) in haystack
            for needle in needles
        )
    )


def experiment_like_text(value: Any) -> bool:
    """Classify branch/PR names across Git and path separator conventions."""
    text = str(value or "")
    normalized_text = re.sub(r"[-_./\\]+", " ", text)
    normalized_name = re.sub(r"[-_./\\\s]+", "_", text)
    return bool(
        "run287" in text.lower()
        or BRANCH_EXPERIMENT_NAME_RE.search(text)
        or BRANCH_EXPERIMENT_NAME_RE.search(normalized_name)
        or EXPERIMENT_TEXT_RE.search(normalized_text)
    )


def normalized_evidence_identity(value: Any) -> str:
    return re.sub(r"[-_./\\\s]+", "_", str(value or "").lower()).strip("_")


def matched_registry_ids_for_evidence(
    do_not_repeat_ids: set[str] | Mapping[str, tuple[str, ...]],
    evidence_values: Iterable[Any],
) -> list[str]:
    normalized_evidence = [
        normalized_evidence_identity(value) for value in evidence_values
    ]
    descriptors = (
        do_not_repeat_ids
        if isinstance(do_not_repeat_ids, Mapping)
        else {item: () for item in do_not_repeat_ids}
    )
    matched: list[str] = []
    for identifier, fields in descriptors.items():
        normalized_identifier = normalized_evidence_identity(identifier)
        id_match = bool(
            normalized_identifier
            and any(
                normalized_identifier in evidence
                for evidence in normalized_evidence
            )
        )
        normalized_fields = [
            normalized_evidence_identity(value) for value in fields
        ]
        descriptor_match = bool(
            normalized_fields
            and all(normalized_fields)
            and all(
                any(field in evidence for evidence in normalized_evidence)
                for field in normalized_fields
            )
        )
        if id_match or descriptor_match:
            matched.append(identifier)
    return sorted(matched)


def validated_do_not_repeat_entries(
    registry: Any,
) -> dict[str, tuple[str, ...]]:
    if not isinstance(registry, dict):
        raise ValueError("do-not-repeat registry must be an object")
    if registry.get("schema_version") != "run287-do-not-repeat-registry-v1":
        raise ValueError("do-not-repeat registry schema mismatch")
    match_fields = registry.get("match_fields")
    if match_fields != ["signal", "mechanism", "book", "window"]:
        raise ValueError("do-not-repeat registry match_fields mismatch")
    entries = registry.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ValueError("do-not-repeat registry entries must be a non-empty list")
    descriptors: dict[str, tuple[str, ...]] = {}
    for index, item in enumerate(entries):
        if not isinstance(item, dict):
            raise ValueError(
                f"do-not-repeat registry entry {index} must be an object"
            )
        identifier = str(item.get("id") or "").strip()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_]*", identifier):
            raise ValueError(
                f"do-not-repeat registry entry {index} has invalid id"
            )
        for field in match_fields:
            if not str(item.get(field) or "").strip():
                raise ValueError(
                    f"do-not-repeat registry entry {identifier} missing {field}"
                )
        if not str(item.get("status") or "").strip():
            raise ValueError(
                f"do-not-repeat registry entry {identifier} missing status"
            )
        if item.get("blocked_reuse") is not True:
            raise ValueError(
                f"do-not-repeat registry entry {identifier} is not blocked"
            )
        if identifier in descriptors:
            raise ValueError("do-not-repeat registry contains duplicate ids")
        descriptors[identifier] = tuple(
            str(item[field]).strip() for field in match_fields
        )
    identifiers = list(descriptors)
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("do-not-repeat registry contains duplicate ids")
    normalized_identifiers = [
        normalized_evidence_identity(identifier) for identifier in identifiers
    ]
    if len(normalized_identifiers) != len(set(normalized_identifiers)):
        raise ValueError(
            "do-not-repeat registry contains normalized duplicate ids"
        )
    normalized_descriptor_tuples = [
        tuple(normalized_evidence_identity(value) for value in values)
        for values in descriptors.values()
    ]
    if any(not all(values) for values in normalized_descriptor_tuples):
        raise ValueError(
            "do-not-repeat registry contains invalid normalized descriptors"
        )
    if len(normalized_descriptor_tuples) != len(
        set(normalized_descriptor_tuples)
    ):
        raise ValueError(
            "do-not-repeat registry contains duplicate normalized descriptors"
        )
    return descriptors


def validated_do_not_repeat_ids(registry: Any) -> set[str]:
    return set(validated_do_not_repeat_entries(registry))


def changed_path_evidence(raw: dict[str, Any], paths: list[str]) -> tuple[int, bool]:
    """Return a declared count and completeness only for pinned path evidence."""
    declared = raw.get("changedFiles")
    count_valid = (
        isinstance(declared, int)
        and not isinstance(declared, bool)
        and declared >= 0
    )
    changed_files = int(declared) if count_valid else -1
    detail = raw.get("changedFilesDetail")
    graphql = raw.get("changedFilesGraphql")
    detail_valid = (
        isinstance(detail, int) and not isinstance(detail, bool) and detail >= 0
    )
    graphql_absent = graphql is None
    graphql_valid = graphql_absent or (
        isinstance(graphql, int)
        and not isinstance(graphql, bool)
        and graphql >= 0
    )
    provenance_consistent = bool(
        detail_valid
        and graphql_valid
        and changed_files == int(detail)
        and (graphql_absent or changed_files == int(graphql))
    )
    head_sha = clean_sha(raw.get("headRefOid"))
    base_sha = clean_sha(raw.get("baseRefOid"))
    pinned = bool(
        raw.get("changedPathsComplete") is True
        and raw.get("changedPathsSource")
        == "GITHUB_HEAD_AND_BASE_PINNED_PR_FILES_API"
        and clean_sha(raw.get("changedPathsHeadBefore")) == head_sha
        and clean_sha(raw.get("changedPathsHeadAfter")) == head_sha
        and clean_sha(raw.get("changedPathsBaseBefore")) == base_sha
        and clean_sha(raw.get("changedPathsBaseAfter")) == base_sha
        and head_sha
        and base_sha
    )
    complete = bool(
        count_valid
        and pinned
        and provenance_consistent
        and changed_files == len(paths)
        and len(paths) < 3000
        and raw.get("changedPathsApiCapReached") is not True
    )
    return changed_files, complete


def load_bound_ancestry_payload(payload: Any, audit_sha: str) -> dict[str, str]:
    """Accept cached ancestry only when its audit-commit identity is explicit."""
    if not isinstance(payload, dict):
        raise ValueError("ancestry payload must be an object")
    if clean_sha(payload.get("audit_sha")) != clean_sha(audit_sha):
        raise ValueError("cached ancestry audit SHA mismatch")
    statuses = payload.get("statuses")
    if not isinstance(statuses, dict):
        raise ValueError("cached ancestry statuses are missing")
    allowed = {
        "ANCESTOR_OF_AUDIT_HEAD",
        "ORPHANED_FROM_AUDIT_HEAD",
    }
    normalized: dict[str, str] = {}
    for raw_sha, status in statuses.items():
        sha = clean_sha(raw_sha)
        if not sha or status not in allowed:
            raise ValueError("cached ancestry status is invalid")
        if sha in normalized:
            raise ValueError("cached ancestry contains normalized duplicate SHAs")
        normalized[sha] = str(status)
    return normalized


def cached_collection_identity(
    records: list[dict[str, Any]], collection_kind: str
) -> list[dict[str, Any]]:
    """Derive the namespace identity that a v3 cache must pin twice."""
    if collection_kind == "branches":
        identity: list[dict[str, Any]] = []
        seen: set[str] = set()
        for record in records:
            name = str(record.get("name") or "")
            commit = (
                record.get("commit")
                if isinstance(record.get("commit"), dict)
                else {}
            )
            sha = clean_sha(commit.get("sha"))
            if not name or not sha or name in seen:
                raise ValueError("cached branch collection has invalid identities")
            seen.add(name)
            identity.append({"name": name, "head_sha": sha})
        return sorted(identity, key=lambda item: item["name"])

    identity = []
    seen_numbers: set[int] = set()
    for record in records:
        number = record.get("number")
        if (
            not isinstance(number, int)
            or isinstance(number, bool)
            or number <= 0
            or number in seen_numbers
        ):
            raise ValueError("cached PR collection has invalid PR number")
        head_sha = clean_sha(record.get("headRefOid"))
        if not head_sha:
            raise ValueError("cached PR collection has invalid head SHA")
        required_text = ("title", "body", "headRefName", "baseRefName")
        if any(
            field not in record or not isinstance(record.get(field), str)
            for field in required_text
        ):
            raise ValueError(
                "cached PR collection lacks explicit mutable/base identity fields"
            )
        if not record["title"].strip() or not record["headRefName"].strip():
            raise ValueError(
                "cached PR collection has invalid mutable identity fields"
            )
        base_sha = clean_sha(record.get("baseRefOid"))
        if not base_sha or not record["baseRefName"].strip():
            raise ValueError("cached PR collection has invalid base identity")
        seen_numbers.add(number)
        identity.append(
            {
                "number": number,
                "head_sha": head_sha,
                "title": str(record.get("title") or ""),
                "body": str(record.get("body") or ""),
                "head_ref_name": str(record.get("headRefName") or ""),
                "base_sha": base_sha,
                "base_ref_name": str(record.get("baseRefName") or ""),
            }
        )
    return sorted(identity, key=lambda item: item["number"])


def load_bound_collection_payload(
    payload: Any,
    *,
    audit_sha: str,
    collection_kind: str,
) -> list[dict[str, Any]]:
    """Load a cached complete collection only with immutable audit evidence."""
    if collection_kind not in {"branches", "pull_requests"}:
        raise ValueError("unsupported cached collection kind")
    if not isinstance(payload, dict):
        raise ValueError("cached collection must be an evidence object")
    if payload.get("schema_version") != COLLECTION_CACHE_SCHEMA_VERSION:
        raise ValueError("cached collection schema mismatch")
    if payload.get("repository") != REPOSITORY:
        raise ValueError("cached collection repository mismatch")
    if clean_sha(payload.get("audit_sha")) != clean_sha(audit_sha):
        raise ValueError("cached collection audit SHA mismatch")
    if payload.get("collection_kind") != collection_kind:
        raise ValueError("cached collection kind mismatch")
    if payload.get("pagination_complete") is not True:
        raise ValueError("cached collection pagination is not complete")
    records = payload.get("records")
    if not isinstance(records, list) or not all(
        isinstance(item, dict) for item in records
    ):
        raise ValueError("cached collection records are invalid")
    declared_count = payload.get("record_count")
    if (
        not isinstance(declared_count, int)
        or isinstance(declared_count, bool)
        or declared_count != len(records)
    ):
        raise ValueError("cached collection record count mismatch")
    if payload.get("records_sha256") != canonical_sha256(records):
        raise ValueError("cached collection record hash mismatch")
    identity = cached_collection_identity(records, collection_kind)
    identity_hash = canonical_sha256(identity)
    if (
        payload.get("identity_snapshot_source")
        != COLLECTION_IDENTITY_SNAPSHOT_SOURCE
        or payload.get("identity_snapshot_record_count") != len(identity)
        or payload.get("identity_snapshot_before_sha256") != identity_hash
        or payload.get("identity_snapshot_after_sha256") != identity_hash
    ):
        raise ValueError("cached collection identity snapshots are missing or stale")
    if collection_kind == "pull_requests" and any(
        "renamedFromPaths" not in item
        or not isinstance(item.get("renamedFromPaths"), list)
        for item in records
    ):
        raise ValueError("cached PR collection lacks rename provenance")
    if collection_kind == "pull_requests":
        for record in records:
            number = record.get("number")
            if (
                not isinstance(number, int)
                or isinstance(number, bool)
                or number <= 0
            ):
                raise ValueError("cached PR collection has invalid PR number")
            for field in ("files", "renamedFromPaths"):
                items = record.get(field)
                if not isinstance(items, list):
                    raise ValueError(
                        f"cached PR collection has invalid {field} provenance"
                    )
                paths = [
                    item.get("path")
                    for item in items
                    if isinstance(item, dict)
                ]
                if (
                    len(paths) != len(items)
                    or any(
                        not isinstance(path, str) or not path.strip()
                        for path in paths
                    )
                    or len(paths) != len(set(paths))
                ):
                    raise ValueError(
                        f"cached PR collection has malformed {field} provenance"
                    )
    return records


def merge_ancestry_evidence(
    local: dict[str, str], cached: dict[str, str]
) -> dict[str, str]:
    conflicts = sorted(
        sha for sha in set(local) & set(cached) if local[sha] != cached[sha]
    )
    if conflicts:
        raise ValueError(
            "local and cached ancestry conflict:" + ",".join(conflicts)
        )
    return {**local, **cached}


def ancestry_status(
    sha: str,
    audit_sha: str,
    ancestry_by_sha: dict[str, str],
) -> str:
    if sha == audit_sha:
        return "IDENTICAL_TO_AUDIT_HEAD"
    value = ancestry_by_sha.get(sha, "")
    if value in {"ANCESTOR_OF_AUDIT_HEAD", "ORPHANED_FROM_AUDIT_HEAD"}:
        return value
    return "UNVERIFIED_BLOCKED"


def normalize_branch(
    raw: dict[str, Any],
    *,
    audit_sha: str,
    ancestry_by_sha: dict[str, str],
) -> dict[str, Any]:
    name = str(raw.get("name") or "")
    commit = raw.get("commit") if isinstance(raw.get("commit"), dict) else {}
    sha = clean_sha(commit.get("sha"))
    return {
        "record_id": f"github-branch:{name}",
        "record_type": "BRANCH",
        "name": name,
        "head_sha": sha,
        "protected": bool(raw.get("protected")),
        "run287_named": "run287" in name.lower(),
        "ancestry": ancestry_status(sha, audit_sha, ancestry_by_sha),
        "linked_pr_numbers": [],
        "experiment_candidate": False,
        "experiment_identity_status": "NOT_EXPERIMENT",
        "promotion_blockers": [],
    }


def normalize_pr(
    raw: dict[str, Any],
    *,
    audit_sha: str,
    ancestry_by_sha: dict[str, str],
    do_not_repeat_ids: set[str] | Mapping[str, tuple[str, ...]],
) -> dict[str, Any]:
    number = int(raw.get("number") or 0)
    title = str(raw.get("title") or "")
    body = str(raw.get("body") or "")
    head_name = str(raw.get("headRefName") or "")
    head_sha = clean_sha(raw.get("headRefOid"))
    paths = path_list(raw.get("files"))
    renamed_from_paths = path_list(raw.get("renamedFromPaths"))
    changed_files, changed_paths_complete = changed_path_evidence(raw, paths)
    text = " ".join((title, body, head_name))
    normalized_text = re.sub(r"[-_./\\]+", " ", text)
    all_evidence_paths = [*paths, *renamed_from_paths]
    families = capability_families(normalized_text, all_evidence_paths)
    matched_registry_ids = matched_registry_ids_for_evidence(
        do_not_repeat_ids,
        (title, body, head_name, *all_evidence_paths),
    )
    experiment_like = bool(
        number in KNOWN_REGISTRY_OUTSIDE_EXPERIMENT_PRS
        or matched_registry_ids
        or experiment_like_text(head_name)
        or experiment_like_text(text)
        or EXPERIMENT_TEXT_RE.search(normalized_text)
        or any(
            EXPERIMENT_PATH_RE.search(path) or experiment_like_text(path)
            for path in all_evidence_paths
        )
    )
    raw_commits = raw.get("commits")
    declared_commit_count = raw.get("commitCount")
    commit_count = (
        int(declared_commit_count)
        if isinstance(declared_commit_count, int)
        and not isinstance(declared_commit_count, bool)
        and declared_commit_count >= 0
        else None
    )
    observed_commit_oids = (
        [clean_sha(item.get("oid")) for item in raw_commits]
        if isinstance(raw_commits, list)
        and all(isinstance(item, dict) for item in raw_commits)
        else []
    )
    commit_oids_complete = bool(
        isinstance(raw_commits, list)
        and commit_count is not None
        and len(raw_commits) == commit_count
        and len(observed_commit_oids) == len(set(observed_commit_oids))
        and all(observed_commit_oids)
        and head_sha in observed_commit_oids
    )
    commit_oids = observed_commit_oids if commit_oids_complete else None
    labels = sorted(
        str(item.get("name") or "")
        for item in raw.get("labels") or []
        if isinstance(item, dict) and str(item.get("name") or "")
    )
    reviews = raw.get("reviews") if isinstance(raw.get("reviews"), list) else None
    checks = (
        raw.get("statusCheckRollup")
        if isinstance(raw.get("statusCheckRollup"), list)
        else None
    )
    merged = bool(raw.get("mergedAt"))
    state = "MERGED" if merged else str(raw.get("state") or "UNKNOWN").upper()
    blockers: list[str] = []
    if experiment_like:
        blockers.extend(
            [
                "canonical_experiment_id_missing",
                "exact_parameter_and_data_hash_unverified",
                "synchronized_daily_after_cost_return_column_unverified",
                "target_book_and_cash_cost_contract_unverified",
            ]
        )
    if not changed_paths_complete:
        blockers.append("changed_paths_truncated")
    if reviews is None:
        blockers.append("pr_review_metadata_unresolved")
    if checks is None:
        blockers.append("pr_check_metadata_unresolved")
    status_head_oid = clean_sha(raw.get("statusMetadataHeadOid"))
    status_head_matches = bool(
        raw.get("statusMetadataHeadMatches") is True
        and bool(head_sha)
        and bool(status_head_oid)
        and status_head_oid == head_sha
        and raw.get("statusMetadataSource") == "GRAPHQL_STATUS_HEAD_PINNED"
    )
    if not status_head_matches:
        blockers.append("pr_status_identity_unverified")
    if experiment_like and not commit_oids_complete:
        blockers.append("commit_oids_unresolved")
    if ancestry_status(head_sha, audit_sha, ancestry_by_sha) == "UNVERIFIED_BLOCKED":
        blockers.append("head_ancestry_unverified")
    return {
        "record_id": f"github-pr:{number}",
        "record_type": "PULL_REQUEST",
        "number": number,
        "url": str(raw.get("url") or ""),
        "title": title,
        "state": state,
        "is_draft": bool(raw.get("isDraft")),
        "head_branch": head_name,
        "head_sha": head_sha,
        "base_branch": str(raw.get("baseRefName") or ""),
        "base_sha": clean_sha(raw.get("baseRefOid")),
        "status_metadata_head_oid": status_head_oid,
        "status_metadata_head_matches": status_head_matches,
        "status_metadata_source": str(
            raw.get("statusMetadataSource") or "UNRESOLVED_BLOCKED"
        ),
        "merge_commit_sha": clean_sha(
            (raw.get("mergeCommit") or {}).get("oid")
            if isinstance(raw.get("mergeCommit"), dict)
            else ""
        ),
        "ancestry": ancestry_status(head_sha, audit_sha, ancestry_by_sha),
        "created_at": raw.get("createdAt"),
        "updated_at": raw.get("updatedAt"),
        "merged_at": raw.get("mergedAt"),
        "closed_at": raw.get("closedAt"),
        "author_login": str((raw.get("author") or {}).get("login") or ""),
        "labels": labels,
        "changed_file_count": changed_files,
        "github_graphql_changed_file_count": (
            int(raw["changedFilesGraphql"])
            if isinstance(raw.get("changedFilesGraphql"), int)
            and not isinstance(raw.get("changedFilesGraphql"), bool)
            else None
        ),
        "github_detail_changed_file_count": (
            int(raw["changedFilesDetail"])
            if isinstance(raw.get("changedFilesDetail"), int)
            and not isinstance(raw.get("changedFilesDetail"), bool)
            else None
        ),
        "changed_paths": paths,
        "renamed_from_paths": renamed_from_paths,
        "changed_paths_complete": changed_paths_complete,
        "changed_paths_api_cap_reached": bool(
            raw.get("changedPathsApiCapReached")
        ),
        "changed_paths_source": str(
            raw.get("changedPathsSource") or "UNRESOLVED_BLOCKED"
        ),
        "changed_paths_head_before": clean_sha(
            raw.get("changedPathsHeadBefore")
        ),
        "changed_paths_head_after": clean_sha(
            raw.get("changedPathsHeadAfter")
        ),
        "changed_paths_base_before": clean_sha(
            raw.get("changedPathsBaseBefore")
        ),
        "changed_paths_base_after": clean_sha(
            raw.get("changedPathsBaseAfter")
        ),
        "changed_paths_sha256": canonical_sha256(paths),
        "renamed_from_paths_sha256": canonical_sha256(renamed_from_paths),
        "commit_oids": commit_oids,
        "commit_oids_sha256": (
            canonical_sha256(commit_oids) if commit_oids_complete else None
        ),
        "commit_oids_complete": commit_oids_complete,
        "commit_count": commit_count,
        "review_count": len(reviews) if reviews is not None else None,
        "check_count": len(checks) if checks is not None else None,
        "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "experiment_candidate": experiment_like,
        "capability_family_candidates": families,
        "matched_do_not_repeat_ids": matched_registry_ids,
        "experiment_identity_status": (
            "UNMAPPED_BLOCKED" if experiment_like else "NOT_EXPERIMENT"
        ),
        "promotion_blockers": sorted(set(blockers)),
    }


def build_census(
    *,
    repository_payload: dict[str, Any],
    branches: list[dict[str, Any]],
    pull_requests: list[dict[str, Any]],
    audit_sha: str,
    ancestry_by_sha: dict[str, str],
    do_not_repeat_ids: set[str] | Mapping[str, tuple[str, ...]],
) -> dict[str, Any]:
    audit_sha = clean_sha(audit_sha)
    if not audit_sha:
        raise ValueError("audit SHA must be an exact 40-character commit")
    if repository_payload.get("full_name") != REPOSITORY:
        raise ValueError("repository identity mismatch")
    default_branch = str(repository_payload.get("default_branch") or "")
    if default_branch != "master":
        raise ValueError("default branch identity mismatch")
    if repository_payload.get("default_branch_post_collection") != default_branch:
        raise ValueError("default branch identity moved during GitHub collection")
    default_sha = clean_sha(
        ((repository_payload.get("default_branch_commit") or {}).get("sha"))
    )
    if not default_sha:
        raise ValueError("repository payload missing pinned default branch commit")
    if default_sha != audit_sha:
        raise ValueError("remote default branch moved from the pinned audit SHA")
    post_collection_sha = clean_sha(
        (
            repository_payload.get("default_branch_commit_post_collection")
            or {}
        ).get("sha")
    )
    if not post_collection_sha:
        raise ValueError("repository payload missing post-collection default pin")
    if post_collection_sha != audit_sha:
        raise ValueError("remote default branch moved during GitHub collection")
    master_rows = [
        item for item in branches
        if isinstance(item, dict)
        and str(item.get("name") or "") == default_branch
    ]
    master_branch_sha = clean_sha(
        ((master_rows[0].get("commit") or {}).get("sha"))
        if len(master_rows) == 1
        and isinstance(master_rows[0].get("commit"), dict)
        else ""
    )
    if len(master_rows) != 1 or master_branch_sha != audit_sha:
        raise ValueError("branch census is not bound to the pinned audit SHA")

    branch_rows = [
        normalize_branch(
            item, audit_sha=audit_sha, ancestry_by_sha=ancestry_by_sha
        )
        for item in branches
    ]
    pr_rows = [
        normalize_pr(
            item,
            audit_sha=audit_sha,
            ancestry_by_sha=ancestry_by_sha,
            do_not_repeat_ids=do_not_repeat_ids,
        )
        for item in pull_requests
    ]
    pr_numbers_by_branch: dict[str, list[int]] = {}
    pr_numbers_by_head: dict[str, list[int]] = {}
    for row in pr_rows:
        pr_numbers_by_branch.setdefault(row["head_branch"], []).append(row["number"])
        if row["head_sha"]:
            pr_numbers_by_head.setdefault(row["head_sha"], []).append(row["number"])
    pr_rows_by_number = {row["number"]: row for row in pr_rows}
    for row in branch_rows:
        linked = sorted(set(pr_numbers_by_head.get(row["head_sha"], [])))
        name_only_mismatches = sorted(
            number
            for number in pr_numbers_by_branch.get(row["name"], [])
            if number not in linked
        )
        row["linked_pr_numbers"] = linked
        row["name_only_mismatched_pr_numbers"] = name_only_mismatches
        branch_registry_ids = matched_registry_ids_for_evidence(
            do_not_repeat_ids, [row["name"]]
        )
        row["matched_do_not_repeat_ids"] = branch_registry_ids
        branch_name_candidate = bool(
            experiment_like_text(row["name"]) or branch_registry_ids
        )
        if linked and branch_name_candidate:
            for number in linked:
                linked_pr = pr_rows_by_number[number]
                aliases = set(linked_pr.get("experiment_evidence_branch_aliases") or [])
                aliases.add(row["name"])
                linked_pr["experiment_evidence_branch_aliases"] = sorted(aliases)
                linked_pr["matched_do_not_repeat_ids"] = sorted(
                    set(linked_pr["matched_do_not_repeat_ids"])
                    | set(branch_registry_ids)
                )
                linked_pr["capability_family_candidates"] = sorted(
                    set(linked_pr["capability_family_candidates"])
                    | set(capability_families(row["name"], []))
                )
                if linked_pr.get("commit_oids_complete") is not True:
                    linked_pr["promotion_blockers"] = sorted(
                        set(linked_pr["promotion_blockers"])
                        | {"commit_oids_unresolved"}
                    )
                if not linked_pr["experiment_candidate"]:
                    linked_pr["experiment_candidate"] = True
                    linked_pr["experiment_identity_status"] = "UNMAPPED_BLOCKED"
                    linked_pr["promotion_blockers"] = sorted(
                        set(linked_pr["promotion_blockers"])
                        | {
                            "canonical_experiment_id_missing",
                            "exact_parameter_and_data_hash_unverified",
                            "synchronized_daily_after_cost_return_column_unverified",
                            "target_book_and_cash_cost_contract_unverified",
                        }
                    )
        branch_only_candidate = not linked and bool(
            branch_name_candidate
        )
        if branch_only_candidate:
            row["experiment_candidate"] = True
            row["experiment_identity_status"] = "UNMAPPED_BLOCKED"
            row["capability_family_candidates"] = capability_families(
                row["name"], []
            )
            row["promotion_blockers"] = [
                "branch_changed_paths_unrecovered",
                "canonical_experiment_id_missing",
                "exact_parameter_and_data_hash_unverified",
                "synchronized_daily_after_cost_return_column_unverified",
                "target_book_and_cash_cost_contract_unverified",
            ]
            if row["ancestry"] == "UNVERIFIED_BLOCKED":
                row["promotion_blockers"].append("head_ancestry_unverified")
        else:
            row["capability_family_candidates"] = []
    for row in pr_rows:
        row.setdefault("experiment_evidence_branch_aliases", [])

    branch_ids = [row["record_id"] for row in branch_rows]
    pr_ids = [row["record_id"] for row in pr_rows]
    if len(branch_ids) != len(set(branch_ids)):
        raise ValueError("duplicate branch identity")
    if len(pr_ids) != len(set(pr_ids)):
        raise ValueError("duplicate PR identity")
    pr_candidates = [row for row in pr_rows if row["experiment_candidate"]]
    branch_only_candidates = [
        row for row in branch_rows if row["experiment_candidate"]
    ]
    candidates = [*pr_candidates, *branch_only_candidates]
    candidate_records_by_head: dict[str, list[dict[str, Any]]] = {}
    for row in candidates:
        if row["head_sha"]:
            candidate_records_by_head.setdefault(row["head_sha"], []).append(row)
    duplicate_head_groups = []
    for sha, rows in sorted(candidate_records_by_head.items()):
        if len(rows) <= 1:
            continue
        duplicate_head_groups.append(
            {
                "head_sha": sha,
                "record_ids": sorted(row["record_id"] for row in rows),
                "pr_numbers": sorted(
                    row["number"] for row in rows
                    if row["record_type"] == "PULL_REQUEST"
                ),
                "branch_names": sorted(
                    row["name"] for row in rows
                    if row["record_type"] == "BRANCH"
                ),
            }
        )
    for group in duplicate_head_groups:
        members = set(group["record_ids"])
        for row in candidates:
            if row["record_id"] in members:
                row["duplicate_head_record_ids"] = group["record_ids"]
                row["duplicate_head_pr_numbers"] = group["pr_numbers"]
                row["promotion_blockers"] = sorted(
                    set(row["promotion_blockers"])
                    | {"duplicate_code_head_sha_requires_canonical_deduplication"}
                )
    for row in branch_rows + pr_rows:
        row.setdefault("duplicate_head_record_ids", [])
        row.setdefault("duplicate_head_pr_numbers", [])

    unresolved = [
        row for row in candidates if row["experiment_identity_status"] != "MAPPED"
    ]
    branch_ancestry = Counter(row["ancestry"] for row in branch_rows)
    pr_ancestry = Counter(row["ancestry"] for row in pr_rows)
    pr_states = Counter(row["state"] for row in pr_rows)
    blockers = []
    if unresolved:
        blockers.append("experiment_candidates_require_canonical_mapping")
    if any(not row["changed_paths_complete"] for row in pr_rows):
        blockers.append("one_or_more_pr_changed_path_lists_are_truncated")
    if any(not row["status_metadata_head_matches"] for row in pr_rows):
        blockers.append("one_or_more_pr_status_rows_are_not_head_pinned")
    if any(row["review_count"] is None for row in pr_rows):
        blockers.append("one_or_more_pr_review_metadata_sets_are_unresolved")
    if any(row["check_count"] is None for row in pr_rows):
        blockers.append("one_or_more_pr_check_metadata_sets_are_unresolved")
    if any(row["ancestry"] == "UNVERIFIED_BLOCKED" for row in branch_rows + pr_rows):
        blockers.append("one_or_more_git_ancestry_results_are_unverified")
    if branch_only_candidates:
        blockers.append("branch_only_experiment_candidates_require_recovery")
    if duplicate_head_groups:
        blockers.append("duplicate_code_head_sha_groups_require_canonical_deduplication")
    blockers.append("parameter_and_data_hash_duplicate_groups_not_yet_recovered")
    blockers.append("historical_return_series_and_trial_deduplication_not_recovered")
    normalized_branches = sorted(branch_rows, key=lambda row: row["name"])
    normalized_pull_requests = sorted(pr_rows, key=lambda row: row["number"])
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "repository": REPOSITORY,
        "audit_default_branch": "master",
        "audit_default_branch_sha": audit_sha,
        "source_contract": {
            "branch_api": "GET /repos/{owner}/{repo}/branches",
            "pull_request_api": "GET /repos/{owner}/{repo}/pulls?state=all",
            "changed_paths": (
                "GitHub PR files API pinned by before/after head and base SHA"
            ),
            "default_branch_identity": (
                "initial and post-collection repository default-branch names "
                "must match; both heads and the matching branch census row "
                "must equal the audit SHA"
            ),
            "cached_ancestry_identity": (
                "cached statuses require an explicit matching audit SHA"
            ),
            "cached_collection_identity": (
                "cached branch and PR lists require a complete paginated "
                "v3 collection envelope bound by repository, audit SHA, count, "
                "canonical record hash, and matching before/after namespace "
                "plus mutable PR/base identity snapshots"
            ),
            "pull_request_status_identity": (
                "GraphQL state and merge metadata are used only when its head "
                "SHA equals the REST PR row head SHA"
            ),
            "branch_payload_sha256": canonical_sha256(branches),
            "pull_request_payload_sha256": canonical_sha256(pull_requests),
            "normalized_branch_rows_sha256": canonical_sha256(
                normalized_branches
            ),
            "normalized_pull_request_rows_sha256": canonical_sha256(
                normalized_pull_requests
            ),
            "metadata_only": True,
            "fullrun_executed": False,
            "production_or_live_mutated": False,
            "champion_changed": False,
        },
        "summary": {
            "branch_count": len(branch_rows),
            "run287_named_branch_count": sum(row["run287_named"] for row in branch_rows),
            "pull_request_count": len(pr_rows),
            "run287_named_pr_count": sum("run287" in row["head_branch"].lower() for row in pr_rows),
            "pull_request_state_counts": dict(sorted(pr_states.items())),
            "branch_ancestry_counts": dict(sorted(branch_ancestry.items())),
            "pull_request_head_ancestry_counts": dict(sorted(pr_ancestry.items())),
            "experiment_candidate_count": len(candidates),
            "pull_request_experiment_candidate_count": len(pr_candidates),
            "branch_only_experiment_candidate_count": len(branch_only_candidates),
            "unmapped_experiment_candidate_count": len(unresolved),
            "historical_experiment_census_complete": False,
            "historical_challenger_allowed": False,
        },
        "promotion_blockers": sorted(set(blockers)),
        "duplicate_code_identity": {
            "key": "experiment_candidate_head_sha",
            "group_count": len(duplicate_head_groups),
            "groups": duplicate_head_groups,
            "parameter_data_hash_groups_recovered": False,
        },
        "experiment_candidates": sorted(
            candidates,
            key=lambda row: (row["record_type"], row["record_id"]),
        ),
        "branches": normalized_branches,
        "pull_requests": normalized_pull_requests,
    }


def write_candidate_csv(path: Path, census: dict[str, Any]) -> None:
    fields = [
        "record_type", "record_id", "number", "name", "state", "head_branch",
        "head_sha", "ancestry", "title",
        "experiment_identity_status", "capability_family_candidates",
        "experiment_evidence_branch_aliases",
        "matched_do_not_repeat_ids", "promotion_blockers", "url",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in census["experiment_candidates"]:
            item = {field: row.get(field, "") for field in fields}
            for field in (
                "capability_family_candidates", "experiment_evidence_branch_aliases",
                "matched_do_not_repeat_ids", "promotion_blockers",
            ):
                item[field] = "|".join(item[field])
            writer.writerow(item)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=REPOSITORY)
    parser.add_argument("--audit-sha", required=True)
    parser.add_argument("--repository-json", type=Path)
    parser.add_argument("--branches-json", type=Path)
    parser.add_argument("--pull-requests-json", type=Path)
    parser.add_argument("--ancestry-json", type=Path)
    parser.add_argument(
        "--collect-local-ancestry",
        action="store_true",
        help=(
            "Resolve ancestry from locally available Git objects; missing "
            "objects remain UNVERIFIED_BLOCKED."
        ),
    )
    parser.add_argument(
        "--do-not-repeat",
        type=Path,
        default=Path("docs/run287_do_not_repeat_registry.json"),
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.repository != REPOSITORY:
        raise SystemExit("repository identity mismatch")
    audit_sha = clean_sha(args.audit_sha)
    if not audit_sha:
        raise SystemExit("audit SHA must be an exact 40-character commit")
    repository = (
        read_json(args.repository_json)
        if args.repository_json
        else collect_repository(args.repository)
    )
    if not args.repository_json:
        default_branch = str(repository.get("default_branch") or "")
        if not default_branch:
            raise SystemExit("repository default branch is missing")
        repository["default_branch_commit"] = {
            "sha": collect_remote_branch_sha(args.repository, default_branch)
        }
    initial_default_sha = clean_sha(
        ((repository.get("default_branch_commit") or {}).get("sha"))
    )
    if initial_default_sha != audit_sha:
        raise SystemExit("remote default branch does not equal the audit SHA")
    branches = (
        load_bound_collection_payload(
            read_json(args.branches_json),
            audit_sha=audit_sha,
            collection_kind="branches",
        )
        if args.branches_json
        else collect_branches(args.repository)
    )
    pull_requests = (
        load_bound_collection_payload(
            read_json(args.pull_requests_json),
            audit_sha=audit_sha,
            collection_kind="pull_requests",
        )
        if args.pull_requests_json
        else collect_pull_requests(args.repository)
    )
    if not args.pull_requests_json:
        enrich_remote_changed_paths(args.repository, pull_requests)
    live_collection = not (
        args.repository_json and args.branches_json and args.pull_requests_json
    )
    if live_collection:
        repository_after = collect_repository(args.repository)
        default_branch_after = str(
            repository_after.get("default_branch") or ""
        )
        repository["default_branch_post_collection"] = default_branch_after
        if default_branch_after != str(repository.get("default_branch") or ""):
            raise SystemExit("remote default branch changed during GitHub collection")
        repository["default_branch_commit_post_collection"] = {
            "sha": collect_remote_branch_sha(
                args.repository, default_branch_after
            )
        }
        if clean_sha(
            (
                repository.get("default_branch_commit_post_collection")
                or {}
            ).get("sha")
        ) != audit_sha:
            raise SystemExit("remote default branch moved during GitHub collection")
    cached_ancestry = (
        load_bound_ancestry_payload(read_json(args.ancestry_json), audit_sha)
        if args.ancestry_json
        else {}
    )
    ancestry = cached_ancestry
    if args.collect_local_ancestry:
        branch_shas = [
            clean_sha((item.get("commit") or {}).get("sha"))
            for item in branches
            if isinstance(item, dict) and isinstance(item.get("commit"), dict)
        ]
        pr_shas = [
            clean_sha(item.get("headRefOid"))
            for item in pull_requests
            if isinstance(item, dict)
        ]
        local_ancestry = collect_local_ancestry(
            audit_sha=audit_sha,
            shas=[*branch_shas, *pr_shas],
        )
        ancestry = merge_ancestry_evidence(local_ancestry, cached_ancestry)
    registry = read_json(args.do_not_repeat)
    registry_entries = validated_do_not_repeat_entries(registry)
    census = build_census(
        repository_payload=repository,
        branches=branches,
        pull_requests=pull_requests,
        audit_sha=audit_sha,
        ancestry_by_sha=ancestry,
        do_not_repeat_ids=registry_entries,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.output_dir / "github_census.json", census)
    write_json(
        args.output_dir / "github_census_summary.json",
        {
            "schema_version": SCHEMA_VERSION,
            "repository": census["repository"],
            "audit_default_branch_sha": census["audit_default_branch_sha"],
            "summary": census["summary"],
            "promotion_blockers": census["promotion_blockers"],
            "github_census_sha256": canonical_sha256(census),
        },
    )
    write_candidate_csv(
        args.output_dir / "experiment_candidates.csv", census
    )
    print(json.dumps(census["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
