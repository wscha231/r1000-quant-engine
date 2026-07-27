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
        "ready_trial_manifest_invalid"
        in result["errors"]
    )
    assert (
        "main_growth_downside_beta_neutral:"
        "ready_daily_return_manifest_invalid"
        in result["errors"]
    )


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
    test_tracked_evidence_is_hash_bound()
    test_cli_reports_blocked_state_without_treating_it_as_test_failure()
    print("run287_u0_experiment_audit_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
