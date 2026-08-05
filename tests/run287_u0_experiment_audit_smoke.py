#!/usr/bin/env python3
"""Smoke checks for the Run287 U0 historical experiment audit."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "audit_run287_u0_experiment_inventory.py"
SPEC = importlib.util.spec_from_file_location(
    "audit_run287_u0_experiment_inventory", MODULE_PATH
)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)

CONTRACT_PATH = ROOT / "docs" / "run287_u0_experiment_audit_contract.json"
REGISTRY_PATH = ROOT / "docs" / "run287_do_not_repeat_registry.json"
INVENTORY_PATH = ROOT / "docs" / "run287_u0_experiment_inventory.json"


def read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def audit(inventory: dict[str, Any]) -> dict[str, Any]:
    return MOD.audit_inventory(
        contract=read(CONTRACT_PATH),
        registry=read(REGISTRY_PATH),
        inventory=inventory,
        repository_root=ROOT,
        registry_path=REGISTRY_PATH,
        inventory_path=INVENTORY_PATH,
    )


def entry(
    inventory: dict[str, Any], registry_entry_id: str
) -> dict[str, Any]:
    return next(
        item
        for item in inventory["entries"]
        if item["registry_entry_id"] == registry_entry_id
    )


def test_current_inventory_is_valid_but_blocks_promotion() -> None:
    contract = read(CONTRACT_PATH)
    assert "READY" not in contract["trial_manifest_states"]
    assert "READY" not in contract["daily_return_series_states"]
    assert all(
        value.startswith("BLOCK_")
        for value in contract["multiplicity_dispositions"]
    )
    result = audit(read(INVENTORY_PATH))
    assert result["valid"] is True
    assert result["status"] == "VALID_INVENTORY_PROMOTION_BLOCKED"
    assert result["promotion_ready"] is False
    assert result["performance_claim_allowed"] is False
    assert result["fullrun_authorized"] is False
    assert result["champion_change_authorized"] is False
    assert result["registry_entry_count"] == 21
    assert result["classified_entry_count"] == 21
    assert result["promotion_blocked_entry_count"] == 21
    assert result["orphaned_pr_evidence_count"] == 21
    assert result["coverage_scope"] == (
        "CANONICAL_DO_NOT_REPEAT_REGISTRY_ONLY"
    )
    assert result["historical_experiment_census_complete"] is False
    assert result["known_out_of_registry_backlog_count"] == 3
    assert {
        item["evidence"]["pr_number"]
        for item in read(INVENTORY_PATH)["coverage"][
            "known_out_of_registry_backlog"
        ]
    } == {229, 230, 237}
    assert result["overlap_group_count"] == 4
    assert result["errors"] == []


def test_registry_coverage_is_exact_and_fail_closed() -> None:
    inventory = read(INVENTORY_PATH)
    inventory["entries"].pop()
    result = audit(inventory)
    assert result["valid"] is False
    assert any(
        error.startswith("inventory_registry_entries_missing:")
        for error in result["errors"]
    )
    assert "inventory_summary_mismatch" in result["errors"]


def test_registry_hash_drift_is_rejected() -> None:
    inventory = read(INVENTORY_PATH)
    inventory["source_registry"]["sha256"] = "0" * 64
    result = audit(inventory)
    assert result["valid"] is False
    assert "source_registry_sha256_mismatch" in result["errors"]


def test_overlap_must_be_acknowledged_to_prevent_double_counting() -> None:
    inventory = read(INVENTORY_PATH)
    entry(inventory, "direct_growth_tilt")["overlap_group_ids"] = []
    result = audit(inventory)
    assert result["valid"] is False
    assert (
        "direct_growth_tilt:overlap_group_membership_mismatch"
        in result["errors"]
    )

    inventory = read(INVENTORY_PATH)
    inventory["overlap_groups"] = []
    for item in inventory["entries"]:
        item["overlap_group_ids"] = []
    result = audit(inventory)
    assert result["valid"] is False
    assert "known_overlap_groups_mismatch" in result["errors"]


def test_canonical_registry_cannot_be_claimed_as_full_history() -> None:
    inventory = read(INVENTORY_PATH)
    inventory["coverage"]["historical_experiment_census_complete"] = True
    result = audit(inventory)
    assert result["valid"] is False
    assert (
        "historical_experiment_census_must_remain_incomplete"
        in result["errors"]
    )


def test_known_out_of_registry_backlog_cannot_be_hidden() -> None:
    inventory = read(INVENTORY_PATH)
    inventory["coverage"]["known_out_of_registry_backlog"] = []
    result = audit(inventory)
    assert result["valid"] is False
    assert "known_out_of_registry_backlog_invalid" in result["errors"]
    assert "inventory_summary_mismatch" in result["errors"]

    inventory = read(INVENTORY_PATH)
    inventory["coverage"]["known_out_of_registry_backlog"].pop()
    inventory["summary"]["known_out_of_registry_backlog_count"] = 2
    result = audit(inventory)
    assert result["valid"] is False
    assert (
        "known_out_of_registry_pr_numbers_mismatch"
        in result["errors"]
    )
    contract = read(CONTRACT_PATH)
    contract["known_out_of_registry_pr_numbers"] = [229, 230]
    result = MOD.audit_inventory(
        contract=contract,
        registry=read(REGISTRY_PATH),
        inventory=read(INVENTORY_PATH),
        repository_root=ROOT,
        registry_path=REGISTRY_PATH,
        inventory_path=INVENTORY_PATH,
    )
    assert result["valid"] is False
    assert (
        "contract_known_backlog_pr_numbers_invalid"
        in result["errors"]
    )


def test_summary_cannot_be_relabelled_as_ready_return_evidence() -> None:
    inventory = read(INVENTORY_PATH)
    target = entry(inventory, "main_growth_downside_beta_neutral")
    target["exact_trial_manifest_status"] = "READY"
    target["after_cost_daily_return_series_status"] = "READY"
    target["multiplicity_disposition"] = "INCLUDE_EXACT_RETURN_TRIALS"
    result = audit(inventory)
    assert result["valid"] is False
    assert (
        "main_growth_downside_beta_neutral:"
        "trial_manifest_status_invalid"
        in result["errors"]
    )
    assert (
        "main_growth_downside_beta_neutral:"
        "daily_return_series_status_invalid"
        in result["errors"]
    )
    assert (
        "main_growth_downside_beta_neutral:"
        "multiplicity_disposition_invalid"
        in result["errors"]
    )
    assert (
        "main_growth_downside_beta_neutral:"
        "v1_disposition_must_block"
        in result["errors"]
    )
    assert (
        "main_growth_downside_beta_neutral"
        in result["blocked_registry_entry_ids"]
    )

    contract = read(CONTRACT_PATH)
    contract["trial_manifest_states"].append("READY")
    contract["daily_return_series_states"].append("READY")
    result = MOD.audit_inventory(
        contract=contract,
        registry=read(REGISTRY_PATH),
        inventory=read(INVENTORY_PATH),
        repository_root=ROOT,
        registry_path=REGISTRY_PATH,
        inventory_path=INVENTORY_PATH,
    )
    assert result["valid"] is False
    assert (
        "contract_enumeration_invalid:trial_manifest_states"
        in result["errors"]
    )
    assert (
        "contract_enumeration_invalid:daily_return_series_states"
        in result["errors"]
    )


def test_v1_rejects_recovery_manifests_and_selection_labels() -> None:
    inventory = read(INVENTORY_PATH)
    portfolio = entry(inventory, "main_growth_downside_beta_neutral")
    portfolio["trial_manifest"] = {"invented": True}
    mixed = entry(inventory, "ownership_13f_form4")
    mixed["multiplicity_disposition"] = (
        "SELECTION_MULTIPLICITY_PENALTY_IMPLEMENTED"
    )
    result = audit(inventory)
    assert result["valid"] is False
    assert (
        "main_growth_downside_beta_neutral:entry_fields_invalid"
        in result["errors"]
    )
    assert (
        "ownership_13f_form4:multiplicity_disposition_invalid"
        in result["errors"]
    )
    assert "main_growth_downside_beta_neutral" in result["blocked_registry_entry_ids"]
    assert "ownership_13f_form4" in result["blocked_registry_entry_ids"]
    assert result["promotion_blocked_entry_count"] == 21


def test_contract_rules_are_exact_and_fail_closed() -> None:
    inventory = read(INVENTORY_PATH)
    contract = read(CONTRACT_PATH)
    contract["rules"]["summary_metrics_are_not_daily_return_series"] = False
    result = MOD.audit_inventory(
        contract=contract,
        registry=read(REGISTRY_PATH),
        inventory=inventory,
        repository_root=ROOT,
        registry_path=REGISTRY_PATH,
        inventory_path=INVENTORY_PATH,
    )
    assert result["valid"] is False
    assert "contract_rules_invalid" in result["errors"]


def test_hash_bindings_are_newline_canonical() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        lf = root / "lf.txt"
        crlf = root / "crlf.txt"
        lf.write_bytes(b"alpha\nbeta\n")
        crlf.write_bytes(b"alpha\r\nbeta\r\n")
        assert MOD.sha256_file(lf) == MOD.sha256_file(crlf)
        assert MOD.canonical_file_size(lf) == MOD.canonical_file_size(crlf)
    inventory = read(INVENTORY_PATH)
    assert inventory["source_registry"]["sha256"] == MOD.sha256_file(
        REGISTRY_PATH
    )
    assert inventory["source_registry"]["bytes"] == (
        MOD.canonical_file_size(REGISTRY_PATH)
    )


def test_pr_ref_and_blob_bindings_are_verified() -> None:
    inventory = read(INVENTORY_PATH)
    target = entry(inventory, "static_actual_profitability")
    pr_evidence = next(
        evidence
        for evidence in target["evidence"]
        if evidence["kind"] == "github_pr" and evidence["artifacts"]
    )
    original_head = pr_evidence["head_commit"]
    pr_evidence["head_commit"] = "f" * 40
    result = audit(inventory)
    assert result["valid"] is False
    assert any(
        error.endswith(":github_pr_ref_head_mismatch")
        for error in result["errors"]
    )
    pr_evidence["head_commit"] = original_head
    pr_evidence["artifacts"][0]["git_blob_oid"] = "f" * 40
    result = audit(inventory)
    assert result["valid"] is False
    assert any(
        error.endswith(":git_blob_oid_mismatch")
        for error in result["errors"]
    )


def test_every_orphaned_pr_names_a_verified_blob() -> None:
    inventory = read(INVENTORY_PATH)
    target = entry(inventory, "broad_gross_floor")
    pr_evidence = next(
        evidence
        for evidence in target["evidence"]
        if evidence["kind"] == "github_pr"
    )
    assert pr_evidence["ancestry"] == "ORPHANED_FROM_CURRENT_MASTER"
    assert pr_evidence["artifacts"]
    pr_evidence["artifacts"] = []
    result = audit(inventory)
    assert result["valid"] is False
    assert any(
        error.endswith(":orphaned_github_pr_artifact_required")
        for error in result["errors"]
    )


def test_pr_ancestry_label_is_verified_against_audit_base() -> None:
    inventory = read(INVENTORY_PATH)
    target = entry(inventory, "static_actual_profitability")
    pr_evidence = next(
        evidence
        for evidence in target["evidence"]
        if evidence["kind"] == "github_pr"
    )
    assert pr_evidence["ancestry"] == "ORPHANED_FROM_CURRENT_MASTER"
    pr_evidence["ancestry"] = "CURRENT_MASTER"
    result = audit(inventory)
    assert result["valid"] is False
    assert any(
        error.endswith(":github_pr_ancestry_mismatch")
        for error in result["errors"]
    )


def test_required_pr_refspecs_are_exact_and_unique() -> None:
    inventory = read(INVENTORY_PATH)
    refspecs = MOD.required_pr_refspecs(inventory)
    assert len(refspecs) == 22
    assert len(refspecs) == len(set(refspecs))
    assert (
        "+refs/pull/229/head:refs/run287-u0/pr/229"
        in refspecs
    )
    assert (
        "+refs/pull/336/head:refs/run287-u0/pr/336"
        in refspecs
    )
    assert MOD.required_base_refspec(inventory) == (
        "+f29ac1f93a61076a08bedca83a4df5539926aab1:"
        "refs/run287-u0/base"
    )


def test_overlap_deduplication_cannot_be_claimed_in_v1() -> None:
    inventory = read(INVENTORY_PATH)
    group = inventory["overlap_groups"][0]
    group["deduplication_status"] = "READY"
    group["canonical_trial_ids"] = ["invented-trial"]
    result = audit(inventory)
    assert result["valid"] is False
    assert "overlap_group[0]:definition_invalid" in result["errors"]


def test_tracked_evidence_is_hash_bound() -> None:
    inventory = read(INVENTORY_PATH)
    target = entry(inventory, "monthly_dd_vix_floor")
    tracked = next(
        evidence
        for evidence in target["evidence"]
        if evidence["kind"] == "tracked_file"
    )
    tracked["sha256"] = "f" * 64
    result = audit(inventory)
    assert result["valid"] is False
    assert any(
        error.endswith(":tracked_file_sha256_mismatch")
        for error in result["errors"]
    )


def test_missing_artifact_is_checked_against_committed_tree() -> None:
    inventory = read(INVENTORY_PATH)
    missing_path = "_tmp_tests/p5_hold_exit_actual_v2_20260720/summary.json"
    original = MOD.committed_blob_bytes

    def fake_committed_blob_bytes(root: Path, path: str) -> bytes | None:
        if path == missing_path:
            return b"recovered\n"
        return original(root, path)

    MOD.committed_blob_bytes = fake_committed_blob_bytes
    try:
        result = audit(inventory)
    finally:
        MOD.committed_blob_bytes = original
    assert result["valid"] is False
    assert any(
        error.endswith(":missing_local_artifact_committed_blob_exists")
        for error in result["errors"]
    )


def test_registry_payload_and_path_match_the_committed_blob() -> None:
    inventory = read(INVENTORY_PATH)
    registry = read(REGISTRY_PATH)
    registry["entries"][0]["status"] = "INVENTED"
    result = MOD.audit_inventory(
        contract=read(CONTRACT_PATH),
        registry=registry,
        inventory=inventory,
        repository_root=ROOT,
        registry_path=REGISTRY_PATH,
        inventory_path=INVENTORY_PATH,
    )
    assert result["valid"] is False
    assert "parsed_registry_content_mismatch" in result["errors"]

    result = MOD.audit_inventory(
        contract=read(CONTRACT_PATH),
        registry=read(REGISTRY_PATH),
        inventory=inventory,
        repository_root=ROOT,
        registry_path=ROOT / "docs" / "alternate_registry.json",
        inventory_path=INVENTORY_PATH,
    )
    assert result["valid"] is False
    assert "parsed_registry_path_invalid" in result["errors"]


def test_cli_reports_blocked_state_without_treating_it_as_test_failure() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        output = Path(temporary) / "audit.json"
        completed = subprocess.run(
            [
                sys.executable,
                str(MODULE_PATH),
                "--output",
                str(output),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        payload = read(output)
        assert payload["valid"] is True
        assert payload["promotion_ready"] is False
        assert payload["status"] == "VALID_INVENTORY_PROMOTION_BLOCKED"


def main() -> int:
    test_current_inventory_is_valid_but_blocks_promotion()
    test_registry_coverage_is_exact_and_fail_closed()
    test_registry_hash_drift_is_rejected()
    test_overlap_must_be_acknowledged_to_prevent_double_counting()
    test_canonical_registry_cannot_be_claimed_as_full_history()
    test_known_out_of_registry_backlog_cannot_be_hidden()
    test_summary_cannot_be_relabelled_as_ready_return_evidence()
    test_v1_rejects_recovery_manifests_and_selection_labels()
    test_contract_rules_are_exact_and_fail_closed()
    test_hash_bindings_are_newline_canonical()
    test_pr_ref_and_blob_bindings_are_verified()
    test_every_orphaned_pr_names_a_verified_blob()
    test_pr_ancestry_label_is_verified_against_audit_base()
    test_required_pr_refspecs_are_exact_and_unique()
    test_overlap_deduplication_cannot_be_claimed_in_v1()
    test_tracked_evidence_is_hash_bound()
    test_missing_artifact_is_checked_against_committed_tree()
    test_registry_payload_and_path_match_the_committed_blob()
    test_cli_reports_blocked_state_without_treating_it_as_test_failure()
    print("run287_u0_experiment_audit_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
