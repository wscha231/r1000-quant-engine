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
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REPOSITORY = "wscha231/r1000-quant-engine"
SCHEMA_VERSION = "run287-u0-v2-github-census-v1"
SHA_RE = re.compile(r"[0-9a-f]{40}")
EXPERIMENT_PATH_RE = re.compile(
    r"(^|/)(backtest|research|aggressive|auto_learning|experiments?)(/|$)|"
    r"(challenger|replay|selector|scor|target|promotion|experiment|"
    r"relative_strength|sector|crisis|reserve|form4|13f|fundamental|"
    r"earnings|ohlcv|execution_cost|broker)",
    re.IGNORECASE,
)
EXPERIMENT_TEXT_RE = re.compile(
    r"\b(backtest|challenger|experiment|ablation|grid|sweep|alpha|"
    r"relative strength|sector leadership|crisis|reserve|form 4|13f|"
    r"fundamental|earnings|ohlcv|expected return|cagr|mdd)\b",
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


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def run_json(command: list[str]) -> Any:
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError("GitHub metadata command failed")
    return json.loads(completed.stdout)


def collect_repository(repository: str) -> dict[str, Any]:
    return run_json(["gh", "api", f"repos/{repository}"])


def collect_branches(repository: str) -> list[dict[str, Any]]:
    pages = run_json(
        [
            "gh", "api", "--paginate", "--slurp",
            f"repos/{repository}/branches?per_page=100",
        ]
    )
    return [item for page in pages for item in page]


def collect_pull_requests(repository: str) -> list[dict[str, Any]]:
    # A single ``gh pr list --limit 1000`` query with nested files, commits,
    # reviews, and checks exceeds GitHub's 500k potential-node GraphQL cap for
    # this repository.  Enumerate the immutable PR identity fields through the
    # paginated REST collection and resolve changed paths from the pinned Git
    # objects below.  Review/check state is deliberately outside this census;
    # it belongs to the per-PR merge gate, not experiment identity.
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
            "number,state,isDraft,mergeCommit,mergedAt,closedAt,headRefOid",
        ]
    )
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
        status_merge = (
            status.get("mergeCommit")
            if isinstance(status.get("mergeCommit"), dict)
            else {}
        )
        merge_sha = clean_sha(
            status_merge.get("oid") or raw.get("merge_commit_sha")
        )
        rows.append(
            {
                "number": number,
                "title": raw.get("title"),
                "state": status.get("state") or raw.get("state"),
                "isDraft": bool(status.get("isDraft", raw.get("draft"))),
                "headRefName": head.get("ref"),
                "headRefOid": head.get("sha"),
                "baseRefName": base.get("ref"),
                "baseRefOid": base.get("sha"),
                "mergeCommit": {"oid": merge_sha} if merge_sha else None,
                "mergedAt": status.get("mergedAt") or raw.get("merged_at"),
                "closedAt": status.get("closedAt") or raw.get("closed_at"),
                "createdAt": raw.get("created_at"),
                "updatedAt": raw.get("updated_at"),
                "author": {"login": user.get("login")},
                "labels": raw.get("labels") or [],
                "url": raw.get("html_url"),
                "body": raw.get("body") or "",
                "files": [],
                "changedFiles": -1,
                "changedPathsSource": "UNRESOLVED_BLOCKED",
                "commitCount": raw.get("commits"),
            }
        )
    return rows


def enrich_local_changed_paths(
    pull_requests: list[dict[str, Any]],
) -> None:
    """Resolve complete PR paths from locally fetched head/base Git objects.

    ``base...head`` uses the merge base and therefore remains stable when the
    default branch advances after a PR is opened.  A missing object or failed
    diff remains explicitly unresolved instead of being treated as zero files.
    """
    for raw in pull_requests:
        base_sha = clean_sha(raw.get("baseRefOid"))
        head_sha = clean_sha(raw.get("headRefOid"))
        if not base_sha or not head_sha:
            continue
        completed = subprocess.run(
            [
                "git", "diff", "--name-only", "--no-renames",
                f"{base_sha}...{head_sha}", "--",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if completed.returncode != 0:
            continue
        paths = sorted({line for line in completed.stdout.splitlines() if line})
        raw["files"] = [{"path": path} for path in paths]
        raw["changedFiles"] = len(paths)
        raw["changedPathsSource"] = "LOCAL_PINNED_THREE_DOT_DIFF"


def enrich_remote_changed_paths(
    repository: str,
    pull_requests: list[dict[str, Any]],
) -> None:
    """Resolve only local-diff misses through the paginated PR-files API."""
    for raw in pull_requests:
        if int(raw.get("changedFiles") or 0) >= 0:
            continue
        number = int(raw.get("number") or 0)
        if number <= 0:
            continue
        try:
            pages = run_json(
                [
                    "gh", "api", "--paginate", "--slurp",
                    f"repos/{repository}/pulls/{number}/files?per_page=100",
                ]
            )
        except RuntimeError:
            continue
        paths = sorted(
            {
                str(item.get("filename") or "")
                for page in pages
                for item in page
                if isinstance(item, dict) and str(item.get("filename") or "")
            }
        )
        raw["files"] = [{"path": path} for path in paths]
        raw["changedFiles"] = len(paths)
        raw["changedPathsSource"] = "GITHUB_PAGINATED_PR_FILES_API"


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
    haystack = " ".join([text, *paths]).lower()
    return sorted(
        family
        for family, needles in CAPABILITY_RULES.items()
        if any(needle in haystack for needle in needles)
    )


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
        "name": name,
        "head_sha": sha,
        "protected": bool(raw.get("protected")),
        "run287_named": "run287" in name.lower(),
        "ancestry": ancestry_status(sha, audit_sha, ancestry_by_sha),
    }


def normalize_pr(
    raw: dict[str, Any],
    *,
    audit_sha: str,
    ancestry_by_sha: dict[str, str],
    do_not_repeat_ids: set[str],
) -> dict[str, Any]:
    number = int(raw.get("number") or 0)
    title = str(raw.get("title") or "")
    body = str(raw.get("body") or "")
    head_name = str(raw.get("headRefName") or "")
    head_sha = clean_sha(raw.get("headRefOid"))
    paths = path_list(raw.get("files"))
    changed_files = int(raw.get("changedFiles") or 0)
    changed_paths_complete = changed_files >= 0 and changed_files == len(paths)
    text = " ".join((title, body, head_name))
    families = capability_families(text, paths)
    experiment_like = bool(
        "run287" in head_name.lower()
        or EXPERIMENT_TEXT_RE.search(text)
        or any(EXPERIMENT_PATH_RE.search(path) for path in paths)
    )
    matched_registry_ids = sorted(
        item for item in do_not_repeat_ids if item in text or item in " ".join(paths)
    )
    commit_oids = [
        clean_sha(item.get("oid"))
        for item in raw.get("commits") or []
        if isinstance(item, dict) and clean_sha(item.get("oid"))
    ]
    labels = sorted(
        str(item.get("name") or "")
        for item in raw.get("labels") or []
        if isinstance(item, dict) and str(item.get("name") or "")
    )
    reviews = raw.get("reviews") if isinstance(raw.get("reviews"), list) else []
    checks = (
        raw.get("statusCheckRollup")
        if isinstance(raw.get("statusCheckRollup"), list)
        else []
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
    if ancestry_status(head_sha, audit_sha, ancestry_by_sha) == "UNVERIFIED_BLOCKED":
        blockers.append("head_ancestry_unverified")
    return {
        "record_id": f"github-pr:{number}",
        "number": number,
        "url": str(raw.get("url") or ""),
        "title": title,
        "state": state,
        "is_draft": bool(raw.get("isDraft")),
        "head_branch": head_name,
        "head_sha": head_sha,
        "base_branch": str(raw.get("baseRefName") or ""),
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
        "changed_paths": paths,
        "changed_paths_complete": changed_paths_complete,
        "changed_paths_source": str(
            raw.get("changedPathsSource") or "GITHUB_GRAPHQL"
        ),
        "changed_paths_sha256": canonical_sha256(paths),
        "commit_oids": commit_oids,
        "commit_oids_sha256": canonical_sha256(commit_oids),
        "commit_count": int(raw.get("commitCount") or len(commit_oids)),
        "review_count": len(reviews),
        "check_count": len(checks),
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
    do_not_repeat_ids: set[str],
) -> dict[str, Any]:
    audit_sha = clean_sha(audit_sha)
    if not audit_sha:
        raise ValueError("audit SHA must be an exact 40-character commit")
    if repository_payload.get("full_name") != REPOSITORY:
        raise ValueError("repository identity mismatch")
    if repository_payload.get("default_branch") != "master":
        raise ValueError("default branch identity mismatch")
    default_sha = clean_sha(
        ((repository_payload.get("default_branch_commit") or {}).get("sha"))
    )
    if default_sha and default_sha != audit_sha:
        raise ValueError("remote default branch moved from the pinned audit SHA")

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
    branch_ids = [row["record_id"] for row in branch_rows]
    pr_ids = [row["record_id"] for row in pr_rows]
    if len(branch_ids) != len(set(branch_ids)):
        raise ValueError("duplicate branch identity")
    if len(pr_ids) != len(set(pr_ids)):
        raise ValueError("duplicate PR identity")
    candidates = [row for row in pr_rows if row["experiment_candidate"]]
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
    if any(row["ancestry"] == "UNVERIFIED_BLOCKED" for row in branch_rows + pr_rows):
        blockers.append("one_or_more_git_ancestry_results_are_unverified")
    blockers.append("historical_return_series_and_trial_deduplication_not_recovered")
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "repository": REPOSITORY,
        "audit_default_branch": "master",
        "audit_default_branch_sha": audit_sha,
        "source_contract": {
            "branch_api": "GET /repos/{owner}/{repo}/branches",
            "pull_request_api": "GET /repos/{owner}/{repo}/pulls?state=all",
            "changed_paths": "local pinned base...head Git diff",
            "branch_payload_sha256": canonical_sha256(branches),
            "pull_request_payload_sha256": canonical_sha256(pull_requests),
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
            "unmapped_experiment_candidate_count": len(unresolved),
            "historical_experiment_census_complete": False,
            "historical_challenger_allowed": False,
        },
        "promotion_blockers": sorted(set(blockers)),
        "branches": sorted(branch_rows, key=lambda row: row["name"]),
        "pull_requests": sorted(pr_rows, key=lambda row: row["number"]),
    }


def write_candidate_csv(path: Path, census: dict[str, Any]) -> None:
    fields = [
        "number", "state", "head_branch", "head_sha", "ancestry", "title",
        "experiment_identity_status", "capability_family_candidates",
        "matched_do_not_repeat_ids", "promotion_blockers", "url",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in census["pull_requests"]:
            if not row["experiment_candidate"]:
                continue
            item = {field: row.get(field, "") for field in fields}
            for field in (
                "capability_family_candidates", "matched_do_not_repeat_ids",
                "promotion_blockers",
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
    repository = (
        read_json(args.repository_json)
        if args.repository_json
        else collect_repository(args.repository)
    )
    if not args.repository_json:
        repository["default_branch_commit"] = run_json(
            ["gh", "api", f"repos/{args.repository}/branches/master"]
        ).get("commit", {})
    branches = (
        read_json(args.branches_json)
        if args.branches_json
        else collect_branches(args.repository)
    )
    pull_requests = (
        read_json(args.pull_requests_json)
        if args.pull_requests_json
        else collect_pull_requests(args.repository)
    )
    ancestry = read_json(args.ancestry_json) if args.ancestry_json else {}
    if args.collect_local_ancestry:
        enrich_local_changed_paths(pull_requests)
        enrich_remote_changed_paths(args.repository, pull_requests)
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
        ancestry = {
            **collect_local_ancestry(
                audit_sha=args.audit_sha,
                shas=[*branch_shas, *pr_shas],
            ),
            **ancestry,
        }
    registry = read_json(args.do_not_repeat)
    registry_ids = {
        str(item.get("id") or "")
        for item in registry.get("entries") or []
        if isinstance(item, dict) and str(item.get("id") or "")
    }
    census = build_census(
        repository_payload=repository,
        branches=branches,
        pull_requests=pull_requests,
        audit_sha=args.audit_sha,
        ancestry_by_sha=ancestry,
        do_not_repeat_ids=registry_ids,
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
