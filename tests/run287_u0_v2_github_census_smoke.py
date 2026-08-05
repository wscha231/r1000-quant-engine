#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "build_run287_u0_v2_github_census.py"
SPEC = importlib.util.spec_from_file_location("u0_v2_census", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)
AUDIT_SHA = "a" * 40


def fixtures() -> tuple[dict, list[dict], list[dict], dict[str, str]]:
    repository = {
        "full_name": MOD.REPOSITORY,
        "default_branch": "master",
        "default_branch_commit": {"sha": AUDIT_SHA},
    }
    branches = [
        {"name": "master", "commit": {"sha": AUDIT_SHA}, "protected": True},
        {
            "name": "codex/run287-expected-return",
            "commit": {"sha": "b" * 40},
            "protected": False,
        },
    ]
    pulls = [
        {
            "number": 10,
            "title": "Add expected return challenger",
            "body": "Research-only 21D 63D 126D alpha model",
            "state": "OPEN",
            "isDraft": True,
            "headRefName": "codex/run287-expected-return",
            "headRefOid": "b" * 40,
            "baseRefName": "master",
            "mergeCommit": None,
            "mergedAt": None,
            "closedAt": None,
            "createdAt": "2026-08-01T00:00:00Z",
            "updatedAt": "2026-08-02T00:00:00Z",
            "author": {"login": "wscha231"},
            "labels": [{"name": "research"}],
            "changedFiles": 2,
            "files": [
                {"path": "tools/run_expected_return_challenger.py"},
                {"path": "tests/expected_return_smoke.py"},
            ],
            "reviews": [],
            "statusCheckRollup": [],
            "url": "https://github.com/wscha231/r1000-quant-engine/pull/10",
            "commits": [{"oid": "b" * 40}],
        },
        {
            "number": 11,
            "title": "Typo",
            "body": "",
            "state": "MERGED",
            "isDraft": False,
            "headRefName": "docs-typo",
            "headRefOid": "c" * 40,
            "baseRefName": "master",
            "mergeCommit": {"oid": "d" * 40},
            "mergedAt": "2026-08-02T00:00:00Z",
            "closedAt": "2026-08-02T00:00:00Z",
            "createdAt": "2026-08-01T00:00:00Z",
            "updatedAt": "2026-08-02T00:00:00Z",
            "author": {"login": "wscha231"},
            "labels": [],
            "changedFiles": 1,
            "files": [{"path": "README.md"}],
            "reviews": [{"state": "APPROVED"}],
            "statusCheckRollup": [{"conclusion": "SUCCESS"}],
            "url": "https://github.com/wscha231/r1000-quant-engine/pull/11",
            "commits": [{"oid": "c" * 40}],
        },
    ]
    ancestry = {
        "b" * 40: "ORPHANED_FROM_AUDIT_HEAD",
        "c" * 40: "ORPHANED_FROM_AUDIT_HEAD",
    }
    return repository, branches, pulls, ancestry


def test_census_is_complete_metadata_but_blocks_research_claims() -> None:
    repository, branches, pulls, ancestry = fixtures()
    census = MOD.build_census(
        repository_payload=repository,
        branches=branches,
        pull_requests=pulls,
        audit_sha=AUDIT_SHA,
        ancestry_by_sha=ancestry,
        do_not_repeat_ids={"old_failed_lane"},
    )
    summary = census["summary"]
    assert summary["branch_count"] == 2
    assert summary["pull_request_count"] == 2
    assert summary["experiment_candidate_count"] == 1
    assert summary["unmapped_experiment_candidate_count"] == 1
    assert summary["historical_experiment_census_complete"] is False
    assert summary["historical_challenger_allowed"] is False
    candidate = census["pull_requests"][0]
    assert candidate["experiment_identity_status"] == "UNMAPPED_BLOCKED"
    assert "EXPECTED_RETURN_AND_SCORING" in candidate["capability_family_candidates"]
    assert "canonical_experiment_id_missing" in candidate["promotion_blockers"]
    assert census["pull_requests"][1]["experiment_candidate"] is False


def test_truncated_paths_and_unverified_ancestry_fail_closed() -> None:
    repository, branches, pulls, ancestry = fixtures()
    pulls[0]["changedFiles"] = 3
    ancestry.pop("b" * 40)
    census = MOD.build_census(
        repository_payload=repository,
        branches=branches,
        pull_requests=pulls,
        audit_sha=AUDIT_SHA,
        ancestry_by_sha=ancestry,
        do_not_repeat_ids=set(),
    )
    row = census["pull_requests"][0]
    assert row["changed_paths_complete"] is False
    assert "changed_paths_truncated" in row["promotion_blockers"]
    assert "head_ancestry_unverified" in row["promotion_blockers"]
    assert "one_or_more_pr_changed_path_lists_are_truncated" in census["promotion_blockers"]


def test_repository_and_identity_are_pinned() -> None:
    repository, branches, pulls, ancestry = fixtures()
    repository["full_name"] = "someone/else"
    try:
        MOD.build_census(
            repository_payload=repository,
            branches=branches,
            pull_requests=pulls,
            audit_sha=AUDIT_SHA,
            ancestry_by_sha=ancestry,
            do_not_repeat_ids=set(),
        )
    except ValueError as exc:
        assert "repository identity" in str(exc)
    else:
        raise AssertionError("wrong repository was accepted")


def test_candidate_csv_contains_only_experiment_like_prs() -> None:
    repository, branches, pulls, ancestry = fixtures()
    census = MOD.build_census(
        repository_payload=repository,
        branches=branches,
        pull_requests=pulls,
        audit_sha=AUDIT_SHA,
        ancestry_by_sha=ancestry,
        do_not_repeat_ids=set(),
    )
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "candidates.csv"
        MOD.write_candidate_csv(path, census)
        text = path.read_text(encoding="utf-8")
        assert "expected-return" in text
        assert "docs-typo" not in text


def test_remote_file_fallback_only_fills_unresolved_rows() -> None:
    unresolved = {
        "number": 10,
        "changedFiles": -1,
        "files": [],
        "changedPathsSource": "UNRESOLVED_BLOCKED",
    }
    resolved = {
        "number": 11,
        "changedFiles": 1,
        "files": [{"path": "README.md"}],
        "changedPathsSource": "LOCAL_PINNED_THREE_DOT_DIFF",
    }
    original_run_json = MOD.run_json
    calls: list[list[str]] = []

    def fake_run_json(command: list[str]) -> list[list[dict[str, str]]]:
        calls.append(command)
        return [[{"filename": "tests/a.py"}, {"filename": "tools/a.py"}]]

    MOD.run_json = fake_run_json
    try:
        MOD.enrich_remote_changed_paths(MOD.REPOSITORY, [unresolved, resolved])
    finally:
        MOD.run_json = original_run_json
    assert len(calls) == 1
    assert "/pulls/10/files?per_page=100" in calls[0][-1]
    assert unresolved["changedFiles"] == 2
    assert unresolved["changedPathsSource"] == "GITHUB_PAGINATED_PR_FILES_API"
    assert resolved["files"] == [{"path": "README.md"}]


def main() -> int:
    test_census_is_complete_metadata_but_blocks_research_claims()
    test_truncated_paths_and_unverified_ancestry_fail_closed()
    test_repository_and_identity_are_pinned()
    test_candidate_csv_contains_only_experiment_like_prs()
    test_remote_file_fallback_only_fills_unresolved_rows()
    print("run287_u0_v2_github_census_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
