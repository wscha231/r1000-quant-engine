#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
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
        "default_branch_commit_post_collection": {"sha": AUDIT_SHA},
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
        pull["commitCount"] = len(pull["commits"])
        pull.update(
            {
                "changedPathsComplete": True,
                "changedPathsApiCapReached": False,
                "changedPathsSource": "GITHUB_HEAD_AND_BASE_PINNED_PR_FILES_API",
                "changedPathsHeadBefore": pull["headRefOid"],
                "changedPathsHeadAfter": pull["headRefOid"],
                "changedPathsBaseBefore": pull["baseRefOid"],
                "changedPathsBaseAfter": pull["baseRefOid"],
                "changedFilesDetail": pull["changedFiles"],
                "changedFilesGraphql": pull["changedFiles"],
                "renamedFromPaths": [],
                "statusMetadataHeadOid": pull["headRefOid"],
                "statusMetadataHeadMatches": True,
                "statusMetadataSource": "GRAPHQL_STATUS_HEAD_PINNED",
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

    repository, branches, pulls, ancestry = fixtures()
    repository.pop("default_branch_commit_post_collection")
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
        assert "post-collection default pin" in str(exc)
    else:
        raise AssertionError("cached repository without a final pin was accepted")


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
            return [[
                {
                    "filename": "docs/a.py",
                    "previous_filename": "experiments/a.py",
                },
                {"filename": "tools/a.py"},
            ]]
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
    assert row["renamedFromPaths"] == [{"path": "experiments/a.py"}]


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


def test_zero_count_conflict_and_status_head_race_fail_closed() -> None:
    row = {
        "number": 10,
        "headRefOid": "b" * 40,
        "baseRefOid": AUDIT_SHA,
        "changedFiles": -1,
        "files": [],
    }
    original_run_json = MOD.run_json

    def zero_count_run_json(command: list[str]):
        if command[-1].endswith("?per_page=100"):
            return [[{"filename": "one.py"}]]
        if len(command) > 1 and command[1:3] == ["pr", "view"]:
            return {
                "headRefOid": "b" * 40,
                "baseRefOid": AUDIT_SHA,
                "changedFiles": 0,
            }
        return {
            "head": {"sha": "b" * 40},
            "base": {"sha": AUDIT_SHA},
            "changed_files": 0,
        }

    MOD.run_json = zero_count_run_json
    try:
        MOD.enrich_remote_changed_paths(MOD.REPOSITORY, [row])
    finally:
        MOD.run_json = original_run_json
    assert row["changedFiles"] == 0
    assert len(row["files"]) == 1
    assert row["changedPathsComplete"] is False

    rest_pull = {
        "number": 12,
        "title": "Safety change",
        "state": "open",
        "draft": False,
        "head": {"ref": "codex/safety", "sha": "b" * 40},
        "base": {"ref": "master", "sha": AUDIT_SHA},
        "user": {"login": "wscha231"},
        "labels": [],
        "html_url": "https://example.invalid/12",
        "body": "",
    }

    def status_race_run_json(command: list[str]):
        if command[1:3] == ["api", "--paginate"]:
            return [[rest_pull]]
        return [
            {
                "number": 12,
                "state": "MERGED",
                "headRefOid": "c" * 40,
                "mergedAt": "2026-08-01T00:00:00Z",
                "mergeCommit": {"oid": "d" * 40},
            }
        ]

    MOD.run_json = status_race_run_json
    try:
        try:
            MOD.collect_pull_requests(MOD.REPOSITORY)
        except RuntimeError as exc:
            assert "namespace moved" in str(exc)
        else:
            raise AssertionError("REST/GraphQL PR identity drift was accepted")
    finally:
        MOD.run_json = original_run_json

    empty_head_pull = dict(rest_pull)
    empty_head_pull["head"] = {"ref": "deleted-head", "sha": None}

    def empty_status_run_json(command: list[str]):
        if command[1:3] == ["api", "--paginate"]:
            return [[empty_head_pull]]
        return [
            {
                "number": 12,
                "state": "MERGED",
                "headRefOid": None,
                "mergedAt": "2026-08-01T00:00:00Z",
                "mergeCommit": {"oid": "d" * 40},
            }
        ]

    MOD.run_json = empty_status_run_json
    try:
        collected = MOD.collect_pull_requests(MOD.REPOSITORY)
    finally:
        MOD.run_json = original_run_json
    assert collected[0]["statusMetadataHeadMatches"] is False
    assert collected[0]["state"] == "open"
    assert collected[0]["mergedAt"] is None

    snapshot_calls = 0

    def namespace_race_run_json(command: list[str]):
        nonlocal snapshot_calls
        if command[1:3] == ["api", "--paginate"]:
            return [[rest_pull]]
        snapshot_calls += 1
        rows = [
            {
                "number": 12,
                "state": "OPEN",
                "headRefOid": "b" * 40,
                "mergedAt": None,
                "mergeCommit": None,
            }
        ]
        if snapshot_calls == 2:
            rows.append({"number": 13, "headRefOid": "e" * 40})
        return rows

    MOD.run_json = namespace_race_run_json
    try:
        try:
            MOD.collect_pull_requests(MOD.REPOSITORY)
        except RuntimeError as exc:
            assert "namespace moved" in str(exc)
        else:
            raise AssertionError("PR pagination namespace drift was accepted")
    finally:
        MOD.run_json = original_run_json


def test_cached_collections_require_complete_bound_envelopes() -> None:
    _, branches, pulls, _ = fixtures()
    envelope = {
        "schema_version": MOD.COLLECTION_CACHE_SCHEMA_VERSION,
        "repository": MOD.REPOSITORY,
        "audit_sha": AUDIT_SHA,
        "collection_kind": "branches",
        "pagination_complete": True,
        "record_count": len(branches),
        "records_sha256": MOD.canonical_sha256(branches),
        "records": branches,
    }
    assert MOD.load_bound_collection_payload(
        envelope, audit_sha=AUDIT_SHA, collection_kind="branches"
    ) == branches
    envelope["record_count"] += 1
    try:
        MOD.load_bound_collection_payload(
            envelope, audit_sha=AUDIT_SHA, collection_kind="branches"
        )
    except ValueError as exc:
        assert "record count" in str(exc)
    else:
        raise AssertionError("partial cached collection was accepted")
    try:
        MOD.load_bound_collection_payload(
            pulls, audit_sha=AUDIT_SHA, collection_kind="pull_requests"
        )
    except ValueError as exc:
        assert "evidence object" in str(exc)
    else:
        raise AssertionError("bare cached PR list was accepted")

    pr_envelope = {
        "schema_version": MOD.COLLECTION_CACHE_SCHEMA_VERSION,
        "repository": MOD.REPOSITORY,
        "audit_sha": AUDIT_SHA,
        "collection_kind": "pull_requests",
        "pagination_complete": True,
        "record_count": len(pulls),
        "records_sha256": MOD.canonical_sha256(pulls),
        "records": pulls,
    }
    pulls[0].pop("renamedFromPaths")
    pr_envelope["records_sha256"] = MOD.canonical_sha256(pulls)
    try:
        MOD.load_bound_collection_payload(
            pr_envelope, audit_sha=AUDIT_SHA, collection_kind="pull_requests"
        )
    except ValueError as exc:
        assert "rename provenance" in str(exc)
    else:
        raise AssertionError("cached PR collection without rename provenance passed")

    _, _, pulls, _ = fixtures()
    pulls[0]["renamedFromPaths"] = [{"not_path": "experiments/foo.py"}]
    pr_envelope = {
        "schema_version": MOD.COLLECTION_CACHE_SCHEMA_VERSION,
        "repository": MOD.REPOSITORY,
        "audit_sha": AUDIT_SHA,
        "collection_kind": "pull_requests",
        "pagination_complete": True,
        "record_count": len(pulls),
        "records_sha256": MOD.canonical_sha256(pulls),
        "records": pulls,
    }
    try:
        MOD.load_bound_collection_payload(
            pr_envelope, audit_sha=AUDIT_SHA, collection_kind="pull_requests"
        )
    except ValueError as exc:
        assert "malformed renamedFromPaths" in str(exc)
    else:
        raise AssertionError("malformed cached rename path was accepted")


def test_cached_json_rejects_duplicate_provenance_keys() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "conflicted.json"
        path.write_text(
            '{"audit_sha":"'
            + AUDIT_SHA
            + '","audit_sha":"'
            + ("b" * 40)
            + '"}',
            encoding="utf-8",
        )
        try:
            MOD.read_json(path)
        except ValueError as exc:
            assert "duplicate JSON key" in str(exc)
        else:
            raise AssertionError("duplicate cached provenance key was accepted")


def test_uncollected_commit_oids_remain_unresolved() -> None:
    repository, branches, pulls, ancestry = fixtures()
    pulls[0].pop("commits")
    pulls[0]["commitCount"] = 1
    census = MOD.build_census(
        repository_payload=repository,
        branches=branches,
        pull_requests=pulls,
        audit_sha=AUDIT_SHA,
        ancestry_by_sha=ancestry,
        do_not_repeat_ids=set(),
    )
    candidate = census["pull_requests"][0]
    assert candidate["commit_count"] == 1
    assert candidate["commit_oids"] is None
    assert candidate["commit_oids_sha256"] is None
    assert candidate["commit_oids_complete"] is False
    assert "commit_oids_unresolved" in candidate["promotion_blockers"]

    observed = census["pull_requests"][1]
    assert observed["commit_oids_complete"] is True
    assert observed["commit_oids"] == ["c" * 40]
    assert observed["commit_oids_sha256"] == MOD.canonical_sha256(["c" * 40])

    repository, branches, pulls, ancestry = fixtures()
    pulls[0]["commits"] = [{"oid": "e" * 40}]
    census = MOD.build_census(
        repository_payload=repository,
        branches=branches,
        pull_requests=pulls,
        audit_sha=AUDIT_SHA,
        ancestry_by_sha=ancestry,
        do_not_repeat_ids=set(),
    )
    wrong_head = census["pull_requests"][0]
    assert wrong_head["commit_oids_complete"] is False
    assert wrong_head["commit_oids"] is None
    assert "commit_oids_unresolved" in wrong_head["promotion_blockers"]

    repository, branches, pulls, ancestry = fixtures()
    pulls[0].pop("commitCount")
    census = MOD.build_census(
        repository_payload=repository,
        branches=branches,
        pull_requests=pulls,
        audit_sha=AUDIT_SHA,
        ancestry_by_sha=ancestry,
        do_not_repeat_ids=set(),
    )
    missing_count = census["pull_requests"][0]
    assert missing_count["commit_count"] is None
    assert missing_count["commit_oids"] is None
    assert missing_count["commit_oids_complete"] is False
    assert "commit_oids_unresolved" in missing_count["promotion_blockers"]


def test_do_not_repeat_registry_is_strictly_validated() -> None:
    valid_entry = {
        "id": "known_failed_lane",
        "signal": "signal",
        "mechanism": "mechanism",
        "book": "book",
        "window": "window",
        "status": "REJECTED",
        "blocked_reuse": True,
    }
    valid = {
        "schema_version": "run287-do-not-repeat-registry-v1",
        "match_fields": ["signal", "mechanism", "book", "window"],
        "entries": [valid_entry],
    }
    assert MOD.validated_do_not_repeat_ids(valid) == {"known_failed_lane"}
    invalid_payloads = [
        {},
        {**valid, "schema_version": "wrong"},
        {**valid, "entries": None},
        {**valid, "entries": [{**valid_entry, "signal": ""}]},
        {**valid, "entries": [valid_entry, dict(valid_entry)]},
        {
            **valid,
            "entries": [
                valid_entry,
                {**valid_entry, "id": "known__failed_lane"},
            ],
        },
        {**valid, "entries": [{**valid_entry, "blocked_reuse": False}]},
    ]
    for payload in invalid_payloads:
        try:
            MOD.validated_do_not_repeat_ids(payload)
        except ValueError:
            pass
        else:
            raise AssertionError(
                "malformed do-not-repeat registry was accepted: "
                + json.dumps(payload, sort_keys=True)
            )


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


def test_cached_status_and_changed_count_provenance_are_recomputed() -> None:
    repository, branches, pulls, ancestry = fixtures()
    pulls[0]["statusMetadataHeadOid"] = "c" * 40
    census = MOD.build_census(
        repository_payload=repository,
        branches=branches,
        pull_requests=pulls,
        audit_sha=AUDIT_SHA,
        ancestry_by_sha=ancestry,
        do_not_repeat_ids=set(),
    )
    candidate = census["pull_requests"][0]
    assert candidate["status_metadata_head_matches"] is False
    assert "pr_status_identity_unverified" in candidate["promotion_blockers"]

    repository, branches, pulls, ancestry = fixtures()
    pulls[0]["headRefOid"] = ""
    pulls[0]["statusMetadataHeadOid"] = ""
    census = MOD.build_census(
        repository_payload=repository,
        branches=branches,
        pull_requests=pulls,
        audit_sha=AUDIT_SHA,
        ancestry_by_sha=ancestry,
        do_not_repeat_ids=set(),
    )
    candidate = census["pull_requests"][0]
    assert candidate["status_metadata_head_matches"] is False
    assert "pr_status_identity_unverified" in candidate["promotion_blockers"]

    repository, branches, pulls, ancestry = fixtures()
    pulls[0]["changedFilesDetail"] = 0
    pulls[0]["changedFilesGraphql"] = 2
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

    repository, branches, pulls, ancestry = fixtures()
    pulls[0].pop("changedFilesDetail")
    pulls[0].pop("changedPathsSource")
    census = MOD.build_census(
        repository_payload=repository,
        branches=branches,
        pull_requests=pulls,
        audit_sha=AUDIT_SHA,
        ancestry_by_sha=ancestry,
        do_not_repeat_ids=set(),
    )
    candidate = census["pull_requests"][0]
    assert candidate["github_detail_changed_file_count"] is None
    assert candidate["changed_paths_source"] == "UNRESOLVED_BLOCKED"
    assert candidate["changed_paths_complete"] is False

    repository, branches, pulls, ancestry = fixtures()
    pulls[0].pop("reviews")
    pulls[0].pop("statusCheckRollup")
    census = MOD.build_census(
        repository_payload=repository,
        branches=branches,
        pull_requests=pulls,
        audit_sha=AUDIT_SHA,
        ancestry_by_sha=ancestry,
        do_not_repeat_ids=set(),
    )
    candidate = census["pull_requests"][0]
    assert candidate["review_count"] is None
    assert candidate["check_count"] is None
    assert "pr_review_metadata_unresolved" in candidate["promotion_blockers"]
    assert "pr_check_metadata_unresolved" in candidate["promotion_blockers"]
    assert "one_or_more_pr_review_metadata_sets_are_unresolved" in (
        census["promotion_blockers"]
    )
    assert "one_or_more_pr_check_metadata_sets_are_unresolved" in (
        census["promotion_blockers"]
    )


def test_linked_strong_experiment_head_names_are_candidates() -> None:
    repository, branches, pulls, ancestry = fixtures()
    alias = "promotion-test-rank-rs-revenue-replacement"
    branches[1] = {
        "name": alias,
        "commit": {"sha": "c" * 40},
        "protected": False,
    }
    pulls[1]["title"] = "Maintenance"
    pulls[1]["body"] = ""
    pulls[1]["headRefName"] = "maintenance-alias"
    census = MOD.build_census(
        repository_payload=repository,
        branches=branches,
        pull_requests=pulls,
        audit_sha=AUDIT_SHA,
        ancestry_by_sha=ancestry,
        do_not_repeat_ids={"rank_rs_revenue_replacement"},
    )
    linked_pr = census["pull_requests"][1]
    assert linked_pr["experiment_candidate"] is True
    assert linked_pr["experiment_evidence_branch_aliases"] == [alias]
    assert linked_pr["matched_do_not_repeat_ids"] == [
        "rank_rs_revenue_replacement"
    ]
    linked_branch = next(
        row for row in census["branches"] if row["name"] == alias
    )
    assert linked_branch["linked_pr_numbers"] == [11]
    assert linked_branch["experiment_candidate"] is False
    assert MOD.experiment_like_text("experiments/future-return")
    for value in (
        "research/foo", "aggressive/foo", "promotion/foo", "broker/foo",
        "scor/foo",
    ):
        assert MOD.experiment_like_text(value)
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "candidates.csv"
        MOD.write_candidate_csv(path, census)
        text = path.read_text(encoding="utf-8")
        assert "experiment_evidence_branch_aliases" in text.splitlines()[0]
        assert alias in text

    repository, branches, pulls, ancestry = fixtures()
    branches[1] = {
        "name": "relative-strength-alias",
        "commit": {"sha": "c" * 40},
        "protected": False,
    }
    pulls[1]["title"] = "Backtest"
    pulls[1]["body"] = ""
    pulls[1]["headRefName"] = "neutral-maintenance"
    pulls[1]["files"] = [{"path": "README.md"}]
    census = MOD.build_census(
        repository_payload=repository,
        branches=branches,
        pull_requests=pulls,
        audit_sha=AUDIT_SHA,
        ancestry_by_sha=ancestry,
        do_not_repeat_ids=set(),
    )
    existing_candidate = census["pull_requests"][1]
    assert existing_candidate["experiment_candidate"] is True
    assert "RELATIVE_STRENGTH_AND_LEADERSHIP" in (
        existing_candidate["capability_family_candidates"]
    )

    repository, branches, pulls, ancestry = fixtures()
    branches[1] = {
        "name": "relative-strength-alias",
        "commit": {"sha": "c" * 40},
        "protected": False,
    }
    pulls[1]["commits"] = None
    census = MOD.build_census(
        repository_payload=repository,
        branches=branches,
        pull_requests=pulls,
        audit_sha=AUDIT_SHA,
        ancestry_by_sha=ancestry,
        do_not_repeat_ids=set(),
    )
    alias_promoted = census["pull_requests"][1]
    assert alias_promoted["experiment_candidate"] is True
    assert alias_promoted["commit_oids_complete"] is False
    assert "commit_oids_unresolved" in alias_promoted["promotion_blockers"]


def test_normalized_title_path_rename_and_registry_evidence_are_candidates() -> None:
    repository, branches, pulls, ancestry = fixtures()
    pulls[1]["title"] = "Expected-return model"
    pulls[1]["body"] = ""
    pulls[1]["headRefName"] = "neutral-maintenance"
    pulls[1]["files"] = [{"path": "README.md"}]
    pulls[1]["changedFiles"] = 1
    pulls[1]["changedFilesDetail"] = 1
    pulls[1]["changedFilesGraphql"] = 1
    census = MOD.build_census(
        repository_payload=repository,
        branches=branches,
        pull_requests=pulls,
        audit_sha=AUDIT_SHA,
        ancestry_by_sha=ancestry,
        do_not_repeat_ids=set(),
    )
    assert census["pull_requests"][1]["experiment_candidate"] is True
    assert "EXPECTED_RETURN_AND_SCORING" in (
        census["pull_requests"][1]["capability_family_candidates"]
    )

    repository, branches, pulls, ancestry = fixtures()
    pulls[1]["title"] = "Execution-cost model"
    pulls[1]["body"] = ""
    pulls[1]["headRefName"] = "neutral-maintenance"
    pulls[1]["files"] = [{"path": "README.md"}]
    census = MOD.build_census(
        repository_payload=repository,
        branches=branches,
        pull_requests=pulls,
        audit_sha=AUDIT_SHA,
        ancestry_by_sha=ancestry,
        do_not_repeat_ids=set(),
    )
    execution_title = census["pull_requests"][1]
    assert execution_title["experiment_candidate"] is True
    assert "EXECUTION_COST_AND_LEDGER" in (
        execution_title["capability_family_candidates"]
    )

    repository, branches, pulls, ancestry = fixtures()
    pulls[1]["title"] = "Maintenance"
    pulls[1]["body"] = ""
    pulls[1]["headRefName"] = "neutral-maintenance"
    pulls[1]["files"] = [{"path": "docs/foo.py"}]
    pulls[1]["renamedFromPaths"] = [{"path": "experiments/foo.py"}]
    pulls[1]["changedFiles"] = 1
    pulls[1]["changedFilesDetail"] = 1
    pulls[1]["changedFilesGraphql"] = 1
    census = MOD.build_census(
        repository_payload=repository,
        branches=branches,
        pull_requests=pulls,
        audit_sha=AUDIT_SHA,
        ancestry_by_sha=ancestry,
        do_not_repeat_ids=set(),
    )
    renamed = census["pull_requests"][1]
    assert renamed["experiment_candidate"] is True
    assert renamed["changed_file_count"] == 1
    assert renamed["renamed_from_paths"] == ["experiments/foo.py"]

    repository, branches, pulls, ancestry = fixtures()
    pulls[1]["title"] = "Maintenance"
    pulls[1]["body"] = ""
    pulls[1]["headRefName"] = "neutral-maintenance"
    pulls[1]["files"] = [{"path": "execution-cost/foo.py"}]
    census = MOD.build_census(
        repository_payload=repository,
        branches=branches,
        pull_requests=pulls,
        audit_sha=AUDIT_SHA,
        ancestry_by_sha=ancestry,
        do_not_repeat_ids=set(),
    )
    assert census["pull_requests"][1]["experiment_candidate"] is True

    repository, branches, pulls, ancestry = fixtures()
    pulls[1]["title"] = "rank-rs-revenue-replacement"
    pulls[1]["body"] = ""
    pulls[1]["headRefName"] = "neutral-maintenance"
    pulls[1]["files"] = [{"path": "README.md"}]
    census = MOD.build_census(
        repository_payload=repository,
        branches=branches,
        pull_requests=pulls,
        audit_sha=AUDIT_SHA,
        ancestry_by_sha=ancestry,
        do_not_repeat_ids={"rank_rs_revenue_replacement"},
    )
    assert census["pull_requests"][1]["experiment_candidate"] is True
    assert census["pull_requests"][1]["matched_do_not_repeat_ids"] == [
        "rank_rs_revenue_replacement"
    ]
    assert MOD.EXPERIMENT_TEXT_RE.search("Experiments")


def test_conflicting_local_and_cached_ancestry_fails_closed() -> None:
    sha = "b" * 40
    try:
        MOD.merge_ancestry_evidence(
            {sha: "ANCESTOR_OF_AUDIT_HEAD"},
            {sha: "ORPHANED_FROM_AUDIT_HEAD"},
        )
    except ValueError as exc:
        assert "ancestry conflict" in str(exc)
    else:
        raise AssertionError("conflicting ancestry evidence was accepted")


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
    pulls[1]["statusMetadataHeadOid"] = "b" * 40
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

    repository, branches, pulls, ancestry = fixtures()
    branches.append(
        {
            "name": "codex/run287-unverified-experiment",
            "commit": {"sha": "e" * 40},
            "protected": False,
        }
    )
    census = MOD.build_census(
        repository_payload=repository,
        branches=branches,
        pull_requests=pulls,
        audit_sha=AUDIT_SHA,
        ancestry_by_sha=ancestry,
        do_not_repeat_ids=set(),
    )
    unverified = next(
        row for row in census["branches"]
        if row["name"] == "codex/run287-unverified-experiment"
    )
    assert "head_ancestry_unverified" in unverified["promotion_blockers"]

    repository, branches, pulls, ancestry = fixtures()
    registry_branch_sha = "1" * 40
    branches.append(
        {
            "name": "rank-rs-revenue-replacement",
            "commit": {"sha": registry_branch_sha},
            "protected": False,
        }
    )
    ancestry[registry_branch_sha] = "ORPHANED_FROM_AUDIT_HEAD"
    census = MOD.build_census(
        repository_payload=repository,
        branches=branches,
        pull_requests=pulls,
        audit_sha=AUDIT_SHA,
        ancestry_by_sha=ancestry,
        do_not_repeat_ids={"rank_rs_revenue_replacement"},
    )
    registry_branch = next(
        row for row in census["branches"]
        if row["name"] == "rank-rs-revenue-replacement"
    )
    assert registry_branch["experiment_candidate"] is True
    assert registry_branch["matched_do_not_repeat_ids"] == [
        "rank_rs_revenue_replacement"
    ]


def main() -> int:
    test_census_is_complete_metadata_but_blocks_research_claims()
    test_truncated_paths_and_unverified_ancestry_fail_closed()
    test_repository_and_identity_are_pinned()
    test_candidate_csv_contains_only_experiment_like_prs()
    test_remote_files_are_counted_and_bound_to_one_head()
    test_remote_file_cap_and_head_race_remain_blocked()
    test_cached_changed_paths_require_head_and_base_pins()
    test_zero_count_conflict_and_status_head_race_fail_closed()
    test_cached_collections_require_complete_bound_envelopes()
    test_cached_json_rejects_duplicate_provenance_keys()
    test_uncollected_commit_oids_remain_unresolved()
    test_do_not_repeat_registry_is_strictly_validated()
    test_default_head_and_cached_ancestry_are_audit_bound()
    test_cached_status_and_changed_count_provenance_are_recomputed()
    test_linked_strong_experiment_head_names_are_candidates()
    test_normalized_title_path_rename_and_registry_evidence_are_candidates()
    test_conflicting_local_and_cached_ancestry_fails_closed()
    test_advanced_and_path_named_branches_remain_candidates()
    test_duplicate_branch_only_heads_are_reported()
    test_branch_only_and_duplicate_code_identities_are_blocked()
    print("run287_u0_v2_github_census_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
