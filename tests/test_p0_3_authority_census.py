from __future__ import annotations

import copy
import gzip
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.build_p0_3_authority_census import (  # noqa: E402
    require_audit_commit,
    validate_research_only_policy,
)


CENSUS = ROOT / "docs" / "run287_p0_3_authority_census"
POLICY = ROOT / "docs" / "run287_p0_3_workflow_authority_policy.json"
AUDIT_SHA = "916a02ac0612d64d41f71690cf667a90dfd0531a"
TEXT_SUFFIXES = {".json", ".yaml", ".yml", ".md", ".py", ".txt", ".csv"}


def sha256(path: Path) -> str:
    content = path.read_bytes()
    if path.suffix.lower() in TEXT_SUFFIXES:
        content = content.replace(b"\r\n", b"\n")
    return hashlib.sha256(content).hexdigest()


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


def test_workflow_registry_has_singular_official_authority_and_blocks_legacy_names() -> None:
    registry = load_registry()
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    rows = registry["workflows"]
    assert registry["audit_master_sha"] == AUDIT_SHA
    assert len(rows) == 40
    assert {row["file"] for row in rows} == set(policy["workflows"])
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
    test_workflow_registry_has_singular_official_authority_and_blocks_legacy_names()
    test_workflow_policy_drift_fails_closed()
    test_frozen_audit_commit_is_resolved_independently_of_current_head()
    test_summary_exposes_ambiguous_and_duplicate_writer_surfaces()
    print("P0-3 authority census smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
