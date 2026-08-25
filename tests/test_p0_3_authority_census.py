from __future__ import annotations

import copy
import gzip
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.build_p0_3_authority_census import (  # noqa: E402
    BRANCH_SUPPLEMENT_SCHEMA,
    GENERATOR_RUNTIME_VERSIONS,
    PR_SUPPLEMENT_SCHEMA,
    audited_workflow_paths,
    branch_live_identity_from_rows,
    canonical_text_bytes,
    check_summary,
    read_branch_supplement,
    require_audit_commit,
    resolve_generation_timestamp,
    source_branch_live_identity,
    source_pr_identity,
    supplement_pr_mutable_evidence,
    validated_frozen_checks,
    validate_runtime_requirements,
    validate_research_only_policy,
    validate_u0_fail_closed_source,
)


CENSUS = ROOT / "docs" / "run287_p0_3_authority_census"
POLICY = CENSUS / "source_workflow_authority_policy.json"
AUDIT_SHA = "916a02ac0612d64d41f71690cf667a90dfd0531a"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_summary() -> dict:
    return json.loads((CENSUS / "summary.json").read_text(encoding="utf-8"))


def load_registry() -> dict:
    return yaml.safe_load((CENSUS / "workflow_registry.yaml").read_text(encoding="utf-8"))


def test_census_is_hash_bound_and_read_only() -> None:
    summary = load_summary()
    assert summary["schema_version"] == "run287-p0-3-authority-census-v1"
    assert summary["audit_master_sha"] == AUDIT_SHA
    assert summary["counts"] == {
        "branches": 297,
        "pull_requests": 372,
        "workflows": 40,
    }
    assert all(summary["completeness"][key] for key in (
        "every_visible_branch_classified",
        "every_visible_pr_dispositioned",
        "every_workflow_profiled",
        "unknown_lineage_fail_closed",
        "publication_branch_and_pr_expected_delta",
    ))
    assert summary["completeness"]["open_pr_review_threads_bulk_collected"] is False
    assert summary["completeness"]["all_pr_changed_paths_complete"] is False
    assert summary["evidence_limitations"] == {
        "all_pr_changed_paths_complete": False,
        "incomplete_changed_path_prs": [5, 6, 11, 16, 49, 62, 147, 212],
    }
    assert summary["safety"] == {
        "branch_merge_delete_or_history_rewrite": False,
        "champion_or_production_changed": False,
        "fullrun_executed": False,
        "live_trading_enabled": False,
        "metadata_only": True,
        "target_order_or_ledger_mutated": False,
        "workflow_dispatched": False,
    }
    for name, expected in summary["output_hashes"].items():
        assert sha256(CENSUS / name) == expected
    assert sha256(POLICY) == summary["source_hashes"]["workflow_policy_sha256"]
    source_artifact = summary["source_artifact"]
    source_path = ROOT / source_artifact["repository_path"]
    source_bytes = gzip.decompress(source_path.read_bytes())
    assert sha256(source_path) == source_artifact["compressed_sha256"]
    assert len(source_bytes) == source_artifact["uncompressed_bytes"]
    assert hashlib.sha256(source_bytes).hexdigest() == source_artifact["uncompressed_sha256"]
    assert source_artifact["uncompressed_sha256"] == summary["source_hashes"][
        "source_u0_census_sha256"
    ]
    source = json.loads(source_bytes.decode("utf-8"))
    assert len(source["branches"]) == summary["counts"]["branches"]
    assert len(source["pull_requests"]) == summary["counts"]["pull_requests"]
    assert summary["source_promotion_blockers"] == source["promotion_blockers"]
    assert summary["source_experiment_completeness"] == {
        "historical_challenger_allowed": source["summary"][
            "historical_challenger_allowed"
        ],
        "historical_experiment_census_complete": source["summary"][
            "historical_experiment_census_complete"
        ],
        "unmapped_experiment_candidate_count": source["summary"][
            "unmapped_experiment_candidate_count"
        ],
    }
    assert summary["completeness"]["historical_experiment_census_complete"] is False
    pr_source_artifact = summary["source_pr_supplement_artifact"]
    pr_source_path = ROOT / pr_source_artifact["repository_path"]
    pr_source_bytes = gzip.decompress(pr_source_path.read_bytes())
    assert sha256(pr_source_path) == pr_source_artifact["compressed_sha256"]
    assert len(pr_source_bytes) == pr_source_artifact["uncompressed_bytes"]
    assert hashlib.sha256(pr_source_bytes).hexdigest() == pr_source_artifact[
        "uncompressed_sha256"
    ]
    assert pr_source_artifact["uncompressed_sha256"] == summary["source_hashes"][
        "source_pr_supplement_sha256"
    ]
    pr_source = json.loads(pr_source_bytes.decode("utf-8"))
    assert pr_source["schema_version"] == PR_SUPPLEMENT_SCHEMA
    assert pr_source["audit_master_sha"] == AUDIT_SHA
    assert pr_source["generated_at_utc"] == summary["generated_at_utc"]
    assert len(pr_source["rows"]) == summary["counts"]["pull_requests"]
    source_pr_by_number = {row["number"]: row for row in source["pull_requests"]}
    for row in pr_source["rows"]:
        assert check_summary(row["checks"]) == row["check_summary"]
        source_pr = source_pr_by_number[row["number"]]
        assert (
            row["head_sha"],
            row["base_sha"],
            row["state"],
            row["updated_at"],
        ) == (
            source_pr["head_sha"],
            source_pr["base_sha"],
            source_pr["state"],
            source_pr["updated_at"],
        )
    branch_source_artifact = summary["source_branch_supplement_artifact"]
    branch_source_path = ROOT / branch_source_artifact["repository_path"]
    assert sha256(branch_source_path) == branch_source_artifact["sha256"]
    assert branch_source_artifact["sha256"] == summary["source_hashes"][
        "source_branch_supplement_sha256"
    ]
    assert branch_source_path.stat().st_size == branch_source_artifact["bytes"]
    branch_source = read_branch_supplement(branch_source_path)
    assert branch_source["schema_version"] == BRANCH_SUPPLEMENT_SCHEMA
    assert branch_source["audit_master_sha"] == AUDIT_SHA
    assert branch_source["generated_at_utc"] == summary["generated_at_utc"]
    assert len(branch_source["rows"]) == summary["counts"]["branches"]
    policy_artifact = summary["source_workflow_policy_artifact"]
    policy_path = ROOT / policy_artifact["repository_path"]
    assert policy_path == POLICY
    assert sha256(policy_path) == policy_artifact["sha256"]
    assert policy_artifact["sha256"] == summary["source_hashes"][
        "workflow_policy_sha256"
    ]
    runtime_artifact = summary["generator_runtime_requirements_artifact"]
    runtime_path = ROOT / runtime_artifact["repository_path"]
    assert sha256(runtime_path) == runtime_artifact["sha256"]
    assert runtime_artifact["sha256"] == summary["source_hashes"][
        "generator_runtime_requirements_sha256"
    ]
    pinned_versions = {
        name: version
        for name, version in (
            line.split("==", maxsplit=1)
            for line in runtime_path.read_text(encoding="utf-8").splitlines()
        )
    }
    assert pinned_versions == GENERATOR_RUNTIME_VERSIONS
    assert summary["generator_runtime_versions"] == GENERATOR_RUNTIME_VERSIONS
    for text_name in (
        "README.md",
        "requirements.txt",
        "summary.json",
        "workflow_registry.yaml",
        "source_workflow_authority_policy.json",
    ):
        assert b"\r\n" not in (CENSUS / text_name).read_bytes()


def test_every_branch_has_required_issue_371_fields_and_fail_closed_disposition() -> None:
    frame = pd.read_parquet(CENSUS / "branch_census.parquet")
    required = {
        "branch",
        "tip_sha",
        "merge_base_sha",
        "ahead_count",
        "behind_count",
        "last_commit_at",
        "author_or_agent",
        "associated_pr",
        "associated_issue",
        "changed_paths",
        "workflow_changes",
        "data_or_model_changes",
        "test_changes",
        "artifact_references",
        "classification",
        "recommended_action",
    }
    assert required.issubset(frame.columns)
    assert len(frame) == 297
    assert frame["branch"].is_unique
    assert set(frame["classification"]) <= set("ABCDEF")
    master = frame.loc[frame["branch"] == "master"].iloc[0]
    assert master["tip_sha"] == AUDIT_SHA
    assert master["classification"] == "A"
    assert master["ahead_count"] == 0
    assert (
        frame.loc[frame["classification"] == "F", "recommended_action"]
        .str.contains("NEVER AUTO-MERGE")
        .all()
    )


def test_every_pr_has_exact_identity_checks_review_state_and_disposition() -> None:
    frame = pd.read_parquet(CENSUS / "pr_census.parquet")
    required = {
        "number",
        "title",
        "state",
        "head_branch",
        "head_sha",
        "base_branch",
        "base_sha",
        "associated_issue",
        "checks",
        "check_summary",
        "review_state",
        "disposition",
    }
    assert required.issubset(frame.columns)
    assert len(frame) == 372
    assert frame["number"].is_unique
    assert set(frame["state"]) == {"OPEN", "CLOSED", "MERGED"}
    assert frame["head_sha"].str.fullmatch(r"[0-9a-f]{40}").all()
    assert frame["base_sha"].str.fullmatch(r"[0-9a-f]{40}").all()
    assert frame["disposition"].str.len().gt(0).all()
    assert frame.loc[frame["state"] == "OPEN", "disposition"].str.contains(
        "REVIEW_REQUIRED|BLOCKED"
    ).all()


def test_frozen_pr_check_summary_is_derived_and_corruption_fails_closed() -> None:
    source = json.loads(
        gzip.decompress((CENSUS / "source_pr_supplement.json.gz").read_bytes())
    )
    row = copy.deepcopy(source["rows"][0])
    checks, summary = validated_frozen_checks(row, int(row["number"]))
    assert summary == check_summary(checks)
    row["check_summary"]["count"] += 1
    try:
        validated_frozen_checks(row, int(row["number"]))
    except SystemExit:
        return
    raise AssertionError("corrupt frozen PR check summary was not rejected")


def test_live_pr_mutable_evidence_detects_check_and_review_changes() -> None:
    row = {
        "number": 1,
        "statusCheckRollup": [
            {
                "__typename": "CheckRun",
                "name": "validate",
                "workflowName": "PR Validation (Fast)",
                "status": "COMPLETED",
                "conclusion": "SUCCESS",
                "detailsUrl": "https://example.invalid/check",
            }
        ],
        "reviewDecision": "",
        "latestReviews": [],
        "closingIssuesReferences": [],
    }
    before = supplement_pr_mutable_evidence([row])
    changed_check = copy.deepcopy(row)
    changed_check["statusCheckRollup"][0]["conclusion"] = "FAILURE"
    assert supplement_pr_mutable_evidence([changed_check]) != before
    changed_review = copy.deepcopy(row)
    changed_review["latestReviews"] = [
        {
            "author": {"login": "reviewer"},
            "state": "APPROVED",
            "submittedAt": "2026-08-25T00:00:00Z",
        }
    ]
    assert supplement_pr_mutable_evidence([changed_review]) != before


def test_generator_requirements_require_exact_pins() -> None:
    assert validate_runtime_requirements(CENSUS / "requirements.txt") == (
        GENERATOR_RUNTIME_VERSIONS
    )
    with tempfile.TemporaryDirectory() as directory:
        unsafe = Path(directory) / "requirements.txt"
        unsafe.write_bytes(b"pandas==2.3.3\r\npyarrow==23.0.1\r\nPyYAML==6.0.3\r\n")
        assert canonical_text_bytes(unsafe) == (
            b"pandas==2.3.3\npyarrow==23.0.1\nPyYAML==6.0.3\n"
        )
        unsafe.write_text("pandas>=2.3\npyarrow==23.0.1\nPyYAML==6.0.3\n")
        try:
            validate_runtime_requirements(unsafe)
        except SystemExit:
            return
    raise AssertionError("non-exact generator requirements were not rejected")


def test_u0_fail_closed_source_cannot_be_made_promotion_ready() -> None:
    source = json.loads(
        gzip.decompress((CENSUS / "source_u0_github_census.json.gz").read_bytes())
    )
    validate_u0_fail_closed_source(source)

    def assert_rejected(unsafe: dict) -> None:
        try:
            validate_u0_fail_closed_source(unsafe)
        except SystemExit:
            return
        raise AssertionError("promotion-ready U0 source was not rejected")

    unsafe = copy.deepcopy(source)
    unsafe["promotion_blockers"] = []
    assert_rejected(unsafe)
    unsafe = copy.deepcopy(source)
    unsafe["pull_requests"][0]["changed_paths_complete"] = not unsafe[
        "pull_requests"
    ][0]["changed_paths_complete"]
    assert_rejected(unsafe)
    for key, unsafe_value in (
        ("historical_experiment_census_complete", True),
        ("historical_challenger_allowed", True),
        ("unmapped_experiment_candidate_count", 0),
    ):
        unsafe = copy.deepcopy(source)
        unsafe["summary"][key] = unsafe_value
        assert_rejected(unsafe)


def test_pr_identity_and_frozen_timestamps_require_complete_exact_values() -> None:
    source = json.loads(
        gzip.decompress((CENSUS / "source_u0_github_census.json.gz").read_bytes())
    )
    source_pr_identity(source)
    for field, unsafe_value in (
        ("head_sha", ""),
        ("base_sha", "bad"),
        ("state", "UNKNOWN"),
        ("updated_at", ""),
    ):
        unsafe = copy.deepcopy(source)
        unsafe["pull_requests"][0][field] = unsafe_value
        try:
            source_pr_identity(unsafe)
        except ValueError:
            continue
        raise AssertionError(f"invalid PR identity field was accepted: {field}")

    timestamp = "2026-08-25T05:19:23.469377+00:00"
    assert resolve_generation_timestamp(
        {"generated_at_utc": timestamp},
        {"generated_at_utc": timestamp},
        verify_live_namespace=False,
    ) == timestamp
    try:
        resolve_generation_timestamp(
            {}, {}, verify_live_namespace=False
        )
    except SystemExit:
        return
    raise AssertionError("timestamp-less frozen supplements were not rejected")


def test_live_branch_guard_binds_head_and_protection_state() -> None:
    source = json.loads(
        gzip.decompress((CENSUS / "source_u0_github_census.json.gz").read_bytes())
    )
    expected = source_branch_live_identity(source)
    rows = [
        {
            "name": row["name"],
            "commit": {"sha": row["head_sha"]},
            "protected": row["protected"],
        }
        for row in source["branches"]
    ]
    paginated = [rows[:100], rows[100:200], rows[200:]]
    assert branch_live_identity_from_rows(paginated) == expected
    rows[0]["protected"] = not rows[0]["protected"]
    assert branch_live_identity_from_rows(paginated) != expected


def test_frozen_regeneration_is_independent_of_staging_directory() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        output_dir = Path(temporary) / "alternate" / "staging"
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "build_p0_3_authority_census.py"),
                "--audit-sha",
                AUDIT_SHA,
                "--source-census",
                str(CENSUS / "source_u0_github_census.json.gz"),
                "--output-dir",
                str(output_dir),
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        for name in (
            "README.md",
            "branch_census.parquet",
            "pr_census.parquet",
            "requirements.txt",
            "source_branch_supplement.parquet",
            "source_pr_supplement.json.gz",
            "source_u0_github_census.json.gz",
            "source_workflow_authority_policy.json",
            "summary.json",
            "workflow_registry.yaml",
        ):
            assert (output_dir / name).read_bytes() == (
                CENSUS / name
            ).read_bytes(), name


def test_workflow_registry_has_singular_official_authority_and_blocks_legacy_names() -> None:
    registry = load_registry()
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    rows = registry["workflows"]
    assert registry["audit_master_sha"] == AUDIT_SHA
    assert len(rows) == 40
    assert {row["file"] for row in rows} == set(policy["workflows"])
    assert {path.as_posix() for path in audited_workflow_paths(ROOT, AUDIT_SHA)} == {
        (ROOT / row["path"]).as_posix() for row in rows
    }
    for row in rows:
        blob = subprocess.check_output(
            ["git", "cat-file", "blob", f"{registry['audit_master_sha']}:{row['path']}"],
            cwd=ROOT,
        )
        assert hashlib.sha256(blob).hexdigest() == row["workflow_sha256"]
    validation_workflow = (ROOT / ".github/workflows/pr_validation.yml").read_text(
        encoding="utf-8"
    )
    assert f"git fetch --no-tags --depth=1 origin {AUDIT_SHA}" in validation_workflow
    assert f"{AUDIT_SHA}^{{commit}}" in validation_workflow
    assert {row["decision"] for row in rows} <= {"KEEP", "CONSOLIDATE", "RETIRE", "UNKNOWN"}
    target_writers = [
        row["file"]
        for row in rows
        if row["target_authority"] == "OFFICIAL_CURRENT_US_TARGET_WRITER"
    ]
    ledger_writers = [
        row["file"]
        for row in rows
        if row["paper_ledger_authority"] == "OFFICIAL_SIMULATED_FILL_CONSUMER_AND_WRITER"
    ]
    assert target_writers == ["daily_operating_selection_refresh.yml"]
    assert ledger_writers == ["daily_operating_selection_refresh.yml"]
    assert all(row["production_live_authority"] != "AUTHORIZED" for row in rows)
    assert all(row["model_promotion_authority"] == "NONE_AUTOMATIC_DISABLED" for row in rows)

    by_file = {row["file"]: row for row in rows}
    alphaops = by_file["alphaops_replay_sidecars_manual.yml"]
    assert "INVALID_WORKFLOW_EXCEEDED_MAX_EXPRESSION_LENGTH_21000" in alphaops[
        "platform_validation_blockers"
    ]
    assert alphaops["long_expression_blocks"][0]["length"] > 21_000
    after_close = by_file["after_close_daily.yml"]
    assert after_close["static_authority_references"]["broker_execution_command"] is True
    assert after_close["paper_ledger_authority"] == "NONCANONICAL_ALPACA_PAPER_EXECUTOR_BLOCKED"
    assert after_close["production_live_authority"] == "NONCANONICAL_ALPACA_PAPER_EXECUTION_PATH_BLOCKED"
    assert after_close["authority_blockers"] == [
        "LEGACY_ALPACA_PAPER_EXECUTOR_BYPASSES_CANONICAL_ACCOUNT_LEDGER"
    ]
    live_extension = by_file["live_extension_daily.yml"]
    assert live_extension["platform_validation_blockers"] == []
    assert live_extension["authority_blockers"] == [
        "LIVE_NAMED_CONTENTS_WRITER_NONCANONICAL_BLOCKED"
    ]
    layer4 = by_file["layer4_monthly_swap.yml"]
    assert layer4["static_authority_references"]["broker_execution_command"] is True
    assert layer4["authority_blockers"] == [
        "LEGACY_ALPACA_PAPER_SWAP_BYPASSES_CANONICAL_ACCOUNT_LEDGER"
    ]
    preflight = by_file["data_readiness_preflight.yml"]
    assert preflight["static_authority_references"]["rclone_write"] is True
    assert preflight["durable_write_scope"] == (
        "DIAGNOSTIC_ARTIFACT_AND_CONDITIONAL_CANONICAL_COMPANYFACTS_DATASET_WRITE"
    )
    assert preflight["human_approval_requirement"] == (
        "WORKFLOW_DISPATCH_WITH_SEC_COMPANYFACTS_TRUE_REQUIRED_FOR_CANONICAL_DATASET_MUTATION; "
        "NO_TARGET_OR_LEDGER_MUTATION_AUTHORITY"
    )
    dispatch_inputs = {
        row["name"]: row for row in preflight["trigger"]["workflow_dispatch_inputs"]
    }
    assert dispatch_inputs["sec_companyfacts"]["default"] == "false"


def test_workflow_policy_drift_fails_closed() -> None:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    validate_research_only_policy(policy, AUDIT_SHA)

    def assert_rejected(unsafe_policy: dict) -> None:
        try:
            validate_research_only_policy(unsafe_policy, AUDIT_SHA)
        except SystemExit:
            return
        raise AssertionError("unsafe workflow policy was not rejected")

    for key, unsafe_value in (
        ("live_broker_execution_enabled", True),
        ("automatic_model_promotion_enabled", True),
        ("production_authority_default", "AUTHORIZED"),
        ("model_promotion_authority_default", "AUTOMATIC"),
        ("unlisted_workflow_policy", "ALLOW"),
    ):
        unsafe = copy.deepcopy(policy)
        unsafe["global_guards"][key] = unsafe_value
        assert_rejected(unsafe)
    unsafe = copy.deepcopy(policy)
    unsafe["official_authority"]["live_broker_writer_workflow"] = "live.yml"
    assert_rejected(unsafe)
    for key, unsafe_value in (
        ("paper_ledger_mode", "BROKER_EXECUTION"),
        ("accepted_state_store", "LOCAL_MUTABLE_STATE"),
    ):
        unsafe = copy.deepcopy(policy)
        unsafe["official_authority"][key] = unsafe_value
        assert_rejected(unsafe)
    unsafe = copy.deepcopy(policy)
    unsafe["workflows"]["daily_operating_selection_refresh.yml"][
        "durable_write_scope"
    ] = "LOCAL_MUTABLE_STATE"
    assert_rejected(unsafe)
    unsafe = copy.deepcopy(policy)
    unsafe["workflows"]["after_close_daily.yml"][
        "production_live_authority"
    ] = "AUTHORIZED"
    assert_rejected(unsafe)


def test_frozen_audit_commit_is_resolved_independently_of_current_head() -> None:
    require_audit_commit(ROOT, AUDIT_SHA)
    try:
        require_audit_commit(ROOT, "0" * 40)
    except SystemExit:
        return
    raise AssertionError("missing audit commit was not rejected")


def test_summary_exposes_ambiguous_and_duplicate_writer_surfaces() -> None:
    findings = load_summary()["authority_findings"]
    assert findings["official_target_writers"] == [
        "daily_operating_selection_refresh.yml"
    ]
    assert findings["official_paper_ledger_consumers"] == [
        "daily_operating_selection_refresh.yml"
    ]
    assert findings["live_broker_writers"] == []
    assert findings["automatic_model_promotion_writers"] == []
    assert findings["platform_blocked_workflows"] == [
        "alphaops_replay_sidecars_manual.yml"
    ]
    assert findings["authority_blocked_workflows"] == [
        "after_close_daily.yml",
        "layer4_monthly_swap.yml",
        "live_extension_daily.yml",
    ]
    assert findings["noncanonical_broker_execution_paths"] == [
        "after_close_daily.yml",
        "layer4_monthly_swap.yml",
    ]
    assert len(findings["contents_write_workflows"]) == 9
    assert findings["noncanonical_or_research_target_references"]
    assert findings["nonofficial_paper_ledger_references"]
    assert findings["broker_or_live_named_workflows"]
    assert findings["promotion_or_champion_reference_workflows"]


def main() -> int:
    test_census_is_hash_bound_and_read_only()
    test_every_branch_has_required_issue_371_fields_and_fail_closed_disposition()
    test_every_pr_has_exact_identity_checks_review_state_and_disposition()
    test_frozen_pr_check_summary_is_derived_and_corruption_fails_closed()
    test_live_pr_mutable_evidence_detects_check_and_review_changes()
    test_generator_requirements_require_exact_pins()
    test_u0_fail_closed_source_cannot_be_made_promotion_ready()
    test_pr_identity_and_frozen_timestamps_require_complete_exact_values()
    test_live_branch_guard_binds_head_and_protection_state()
    test_frozen_regeneration_is_independent_of_staging_directory()
    test_workflow_registry_has_singular_official_authority_and_blocks_legacy_names()
    test_workflow_policy_drift_fails_closed()
    test_frozen_audit_commit_is_resolved_independently_of_current_head()
    test_summary_exposes_ambiguous_and_duplicate_writer_surfaces()
    print("P0-3 authority census smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
