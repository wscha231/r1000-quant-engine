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
            "baseRefOid": AUDIT_SHA,
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
            "baseRefOid": AUDIT_SHA,
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
    for pull in pulls:
        pull.update(
            {
                "changedPathsComplete": True,
                "changedPathsApiCapReached": False,
                "changedPathsSource": "GITHUB_HEAD_AND_BASE_PINNED_PR_FILES_API",
                "changedPathsHeadBefore": pull["headRefOid"],
                "changedPathsHeadAfter": pull["headRefOid"],
                "changedPathsBaseBefore": pull["baseRefOid"],
                "changedPathsBaseAfter": pull["baseRefOid"],
            }
        )
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
    assert candidate["base_sha"] == AUDIT_SHA
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

    repository, branches, pulls, ancestry = fixtures()
    repository.pop("default_branch_commit")
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
        assert "missing pinned default branch commit" in str(exc)
    else:
        raise AssertionError("unpinned cached repository metadata was accepted")


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


def test_remote_files_are_counted_and_bound_to_one_head() -> None:
    row = {
        "number": 10,
        "headRefOid": "b" * 40,
        "baseRefOid": AUDIT_SHA,
        "changedFiles": -1,
        "files": [],
        "changedPathsSource": "UNRESOLVED_BLOCKED",
    }
    original_run_json = MOD.run_json
    calls: list[list[str]] = []

    def fake_run_json(command: list[str]):
        calls.append(command)
        if command[-1].endswith("?per_page=100"):
            return [[{"filename": "tests/a.py"}, {"filename": "tools/a.py"}]]
        return {
            "head": {"sha": "b" * 40},
            "base": {"sha": AUDIT_SHA},
            "changed_files": 2,
        }

    MOD.run_json = fake_run_json
    try:
        MOD.enrich_remote_changed_paths(MOD.REPOSITORY, [row])
    finally:
        MOD.run_json = original_run_json
    assert len(calls) == 3
    assert "/pulls/10/files?per_page=100" in calls[1][-1]
    assert row["changedFiles"] == 2
    assert row["changedPathsSource"] == "GITHUB_HEAD_AND_BASE_PINNED_PR_FILES_API"
    assert row["changedPathsHeadBefore"] == "b" * 40
    assert row["changedPathsHeadAfter"] == "b" * 40
    assert row["changedPathsBaseBefore"] == AUDIT_SHA
    assert row["changedPathsBaseAfter"] == AUDIT_SHA


def test_remote_file_cap_and_head_race_remain_blocked() -> None:
    original_run_json = MOD.run_json
    capped = {
        "number": 10,
        "headRefOid": "b" * 40,
        "baseRefOid": AUDIT_SHA,
        "changedFiles": -1,
        "files": [],
    }
    calls = 0

    def capped_run_json(command: list[str]):
        nonlocal calls
        calls += 1
        if command[-1].endswith("?per_page=100"):
            return [[{"filename": f"file-{idx}"} for idx in range(3000)]]
        return {
            "head": {"sha": "b" * 40},
            "base": {"sha": AUDIT_SHA},
            "changed_files": 3001,
        }

    MOD.run_json = capped_run_json
    try:
        MOD.enrich_remote_changed_paths(MOD.REPOSITORY, [capped])
    finally:
        MOD.run_json = original_run_json
    assert calls == 3
    assert capped["changedFiles"] == 3001
    assert len(capped["files"]) == 3000
    assert capped["changedPathsComplete"] is False
    assert capped["changedPathsApiCapReached"] is True

    racing = {
        "number": 10,
        "headRefOid": "b" * 40,
        "baseRefOid": AUDIT_SHA,
        "changedFiles": -1,
        "files": [],
    }
    detail_calls = 0

    def racing_run_json(command: list[str]):
        nonlocal detail_calls
        if command[-1].endswith("?per_page=100"):
            return [[{"filename": "one.py"}]]
        detail_calls += 1
        sha = "b" * 40 if detail_calls == 1 else "c" * 40
        return {
            "head": {"sha": sha},
            "base": {"sha": AUDIT_SHA},
            "changed_files": 1,
        }

    MOD.run_json = racing_run_json
    try:
        MOD.enrich_remote_changed_paths(MOD.REPOSITORY, [racing])
    finally:
        MOD.run_json = original_run_json
    assert racing["changedFiles"] == -1
    assert racing["files"] == []

    base_racing = {
        "number": 10,
        "headRefOid": "b" * 40,
        "baseRefOid": AUDIT_SHA,
        "changedFiles": -1,
        "files": [],
    }
    detail_calls = 0

    def base_racing_run_json(command: list[str]):
        nonlocal detail_calls
        if command[-1].endswith("?per_page=100"):
            return [[{"filename": "one.py"}]]
        detail_calls += 1
        base_sha = AUDIT_SHA if detail_calls == 1 else "d" * 40
        return {
            "head": {"sha": "b" * 40},
            "base": {"sha": base_sha},
            "changed_files": 1,
        }

    MOD.run_json = base_racing_run_json
    try:
        MOD.enrich_remote_changed_paths(MOD.REPOSITORY, [base_racing])
    finally:
        MOD.run_json = original_run_json
    assert base_racing["changedFiles"] == -1
    assert base_racing["files"] == []


def test_cached_changed_paths_require_head_and_base_pins() -> None:
    repository, branches, pulls, ancestry = fixtures()
    pulls[0].pop("changedPathsBaseAfter")
    census = MOD.build_census(
        repository_payload=repository,
        branches=branches,
        pull_requests=pulls,
        audit_sha=AUDIT_SHA,
        ancestry_by_sha=ancestry,
        do_not_repeat_ids=set(),
    )
    candidate = census["pull_requests"][0]
    assert candidate["changed_paths_complete"] is False
    assert "changed_paths_truncated" in candidate["promotion_blockers"]


def test_default_head_and_cached_ancestry_are_audit_bound() -> None:
    repository, branches, pulls, ancestry = fixtures()
    repository["default_branch_commit_post_collection"] = {"sha": "f" * 40}
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
        assert "moved during GitHub collection" in str(exc)
    else:
        raise AssertionError("post-collection default-head drift was accepted")

    repository, branches, pulls, ancestry = fixtures()
    branches[0]["commit"]["sha"] = "f" * 40
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
        assert "branch census" in str(exc)
    else:
        raise AssertionError("mixed-audit branch census was accepted")

    try:
        MOD.load_bound_ancestry_payload(ancestry, AUDIT_SHA)
    except ValueError as exc:
        assert "audit SHA" in str(exc)
    else:
        raise AssertionError("bare cached ancestry was accepted")
    bound = MOD.load_bound_ancestry_payload(
        {"audit_sha": AUDIT_SHA, "statuses": ancestry}, AUDIT_SHA
    )
    assert bound == ancestry


def test_advanced_and_path_named_branches_remain_candidates() -> None:
    repository, branches, pulls, ancestry = fixtures()
    branches[1]["commit"]["sha"] = "e" * 40
    ancestry["e" * 40] = "ORPHANED_FROM_AUDIT_HEAD"
    branches.append(
        {
            "name": "actual-results-rolling-window",
            "commit": {"sha": "f" * 40},
            "protected": False,
        }
    )
    ancestry["f" * 40] = "ORPHANED_FROM_AUDIT_HEAD"
    census = MOD.build_census(
        repository_payload=repository,
        branches=branches,
        pull_requests=pulls,
        audit_sha=AUDIT_SHA,
        ancestry_by_sha=ancestry,
        do_not_repeat_ids=set(),
    )
    advanced = next(
        row for row in census["branches"]
        if row["name"] == "codex/run287-expected-return"
    )
    assert advanced["linked_pr_numbers"] == []
    assert advanced["name_only_mismatched_pr_numbers"] == [10]
    assert advanced["experiment_candidate"] is True
    path_named = next(
        row for row in census["branches"]
        if row["name"] == "actual-results-rolling-window"
    )
    assert path_named["experiment_candidate"] is True


def test_duplicate_branch_only_heads_are_reported() -> None:
    repository, branches, pulls, ancestry = fixtures()
    for name in ("auto-learning-one", "promotion-test-two"):
        branches.append(
            {"name": name, "commit": {"sha": "e" * 40}, "protected": False}
        )
    ancestry["e" * 40] = "ORPHANED_FROM_AUDIT_HEAD"
    census = MOD.build_census(
        repository_payload=repository,
        branches=branches,
        pull_requests=pulls,
        audit_sha=AUDIT_SHA,
        ancestry_by_sha=ancestry,
        do_not_repeat_ids=set(),
    )
    group = next(
        item for item in census["duplicate_code_identity"]["groups"]
        if item["head_sha"] == "e" * 40
    )
    assert group["branch_names"] == ["auto-learning-one", "promotion-test-two"]
    assert group["pr_numbers"] == []
    for record_id in group["record_ids"]:
        row = next(
            item for item in census["experiment_candidates"]
            if item["record_id"] == record_id
        )
        assert "duplicate_code_head_sha_requires_canonical_deduplication" in (
            row["promotion_blockers"]
        )


def test_branch_only_and_duplicate_code_identities_are_blocked() -> None:
    repository, branches, pulls, ancestry = fixtures()
    branches.append(
        {
            "name": "codex/run287-orphan-experiment",
            "commit": {"sha": "e" * 40},
            "protected": False,
        }
    )
    ancestry["e" * 40] = "ORPHANED_FROM_AUDIT_HEAD"
    pulls[1]["title"] = "Backtest duplicate identity"
    pulls[1]["headRefOid"] = "b" * 40
    pulls[1]["changedPathsHeadBefore"] = "b" * 40
    pulls[1]["changedPathsHeadAfter"] = "b" * 40
    census = MOD.build_census(
        repository_payload=repository,
        branches=branches,
        pull_requests=pulls,
        audit_sha=AUDIT_SHA,
        ancestry_by_sha=ancestry,
        do_not_repeat_ids=set(),
    )
    branch = next(
        row for row in census["branches"]
        if row["name"] == "codex/run287-orphan-experiment"
    )
    assert branch["experiment_candidate"] is True
    assert "branch_changed_paths_unrecovered" in branch["promotion_blockers"]
    assert census["summary"]["branch_only_experiment_candidate_count"] == 1
    assert census["duplicate_code_identity"]["group_count"] == 1
    assert census["duplicate_code_identity"]["groups"][0]["pr_numbers"] == [10, 11]
    assert "duplicate_code_head_sha_requires_canonical_deduplication" in (
        census["pull_requests"][0]["promotion_blockers"]
    )


def main() -> int:
    test_census_is_complete_metadata_but_blocks_research_claims()
    test_truncated_paths_and_unverified_ancestry_fail_closed()
    test_repository_and_identity_are_pinned()
    test_candidate_csv_contains_only_experiment_like_prs()
    test_remote_files_are_counted_and_bound_to_one_head()
    test_remote_file_cap_and_head_race_remain_blocked()
    test_cached_changed_paths_require_head_and_base_pins()
    test_default_head_and_cached_ancestry_are_audit_bound()
    test_advanced_and_path_named_branches_remain_candidates()
    test_duplicate_branch_only_heads_are_reported()
    test_branch_only_and_duplicate_code_identities_are_blocked()
    print("run287_u0_v2_github_census_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
