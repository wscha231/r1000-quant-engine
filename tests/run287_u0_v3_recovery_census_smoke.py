"""Smoke tests for conservative U0-v3 legacy trial recovery."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import build_run287_u0_v3_recovery_census as MOD  # noqa: E402


CONTRACT_PATH = ROOT / "docs" / "run287_u0_v3_recovery_contract.json"


def contract() -> dict:
    return MOD.validate_contract(MOD.read_json(CONTRACT_PATH))


def candidate(
    record_id: str,
    head_sha: str,
    *,
    registry_ids: list[str] | None = None,
    ancestry: str = "ANCESTOR_OF_AUDIT_HEAD",
) -> dict:
    number = int(record_id.split(":")[-1])
    return {
        "record_id": record_id,
        "record_type": "PULL_REQUEST",
        "number": number,
        "title": f"legacy candidate {number}",
        "state": "MERGED",
        "url": f"https://github.com/wscha231/r1000-quant-engine/pull/{number}",
        "head_sha": head_sha,
        "ancestry": ancestry,
        "changed_paths_complete": True,
        "capability_family_candidates": ["EXPECTED_RETURN_AND_SCORING"],
        "matched_do_not_repeat_ids": registry_ids or [],
    }


def source_census() -> dict:
    candidates = [
        candidate("github-pr:10", "a" * 40, registry_ids=["known_family"]),
        candidate("github-pr:11", "a" * 40),
        candidate("github-pr:12", "b" * 40, ancestry="UNVERIFIED_BLOCKED"),
    ]
    return {
        "schema_version": MOD.SOURCE_SCHEMA,
        "repository": MOD.REPOSITORY,
        "audit_default_branch": "master",
        "audit_default_branch_sha": "f" * 40,
        "source_contract": {
            "branch_payload_sha256": "c" * 64,
            "pull_request_payload_sha256": "d" * 64,
            "metadata_only": True,
            "fullrun_executed": False,
            "production_or_live_mutated": False,
            "champion_changed": False,
        },
        "summary": {
            "branch_count": 0,
            "pull_request_count": len(candidates),
            "experiment_candidate_count": len(candidates),
            "unmapped_experiment_candidate_count": len(candidates),
            "historical_experiment_census_complete": False,
            "historical_challenger_allowed": False,
        },
        "promotion_blockers": [
            "experiment_candidates_require_canonical_mapping",
            "historical_return_series_and_trial_deduplication_not_recovered",
            "parameter_and_data_hash_duplicate_groups_not_yet_recovered",
        ],
        "branches": [],
        "pull_requests": [
            {"record_id": row["record_id"], "head_sha": row["head_sha"]}
            for row in candidates
        ],
        "experiment_candidates": candidates,
    }


def inventory() -> dict:
    return {
        "schema_version": MOD.INVENTORY_SCHEMA,
        "summary": {"registry_entry_count": 1},
        "entries": [
            {
                "registry_entry_id": "known_family",
                "evaluation_class": "PORTFOLIO_RETURN",
                "evidence_state": "SUMMARY_ONLY",
                "exact_trial_manifest_status": "MISSING",
                "after_cost_daily_return_series_status": "MISSING",
                "published_attempt_count_lower_bound": 3,
            }
        ],
    }


def test_exact_head_aliases_are_deduplicated_and_counted_conservatively() -> None:
    recovered = MOD.build_recovery_census(
        source_census(), inventory(), contract()
    )
    summary = recovered["summary"]
    assert summary["source_experiment_candidate_count"] == 3
    assert summary["classified_candidate_count"] == 3
    assert summary["canonical_code_trial_count"] == 2
    assert summary["duplicate_alias_count"] == 1
    assert summary["canonical_registry_published_attempt_lower_bound"] == 3
    assert summary["conservative_historical_trial_count_lower_bound"] == 5
    assert summary["historical_experiment_census_complete"] is True
    assert summary["historical_challenger_preregistration_ready"] is True
    assert summary["historical_challenger_allowed"] is False
    assert recovered["census_completion_blockers"] == []
    assert recovered["acceptance_migration_blockers"]

    rows = {row["record_id"]: row for row in recovered["recovered_candidates"]}
    assert rows["github-pr:10"]["canonical_trial_id"] == (
        rows["github-pr:11"]["canonical_trial_id"]
    )
    assert rows["github-pr:10"]["multiplicity_weight"] == 1
    assert rows["github-pr:11"]["multiplicity_weight"] == 0
    assert rows["github-pr:10"]["evidence_states"] == ["SUMMARY_ONLY"]
    assert rows["github-pr:11"]["evidence_states"] == ["SUMMARY_ONLY"]
    assert rows["github-pr:11"][
        "source_record_matched_do_not_repeat_ids"
    ] == []
    assert rows["github-pr:11"]["matched_do_not_repeat_ids"] == [
        "known_family"
    ]
    assert "git_ancestry_unverified" in rows["github-pr:12"][
        "legacy_result_promotion_blockers"
    ]
    for row in rows.values():
        assert row["performance_evaluated"] is False
        assert row["performance_metrics"] is None
        assert row["promotion_use_allowed"] is False
        assert row["performance_claim_allowed"] is False
        assert row["exact_head_reuse_blocked"] is True


def test_source_and_contract_tampering_fail_closed() -> None:
    unsafe = source_census()
    unsafe["source_contract"]["fullrun_executed"] = True
    try:
        MOD.build_recovery_census(unsafe, inventory(), contract())
    except ValueError as exc:
        assert "unsafe source census contract" in str(exc)
    else:
        raise AssertionError("unsafe source census was accepted")

    bad_link = source_census()
    bad_link["experiment_candidates"][0]["matched_do_not_repeat_ids"] = [
        "missing_registry_entry"
    ]
    try:
        MOD.build_recovery_census(bad_link, inventory(), contract())
    except ValueError as exc:
        assert "registry linkage" in str(exc)
    else:
        raise AssertionError("unknown registry linkage was accepted")

    changed = json.loads(json.dumps(contract()))
    changed["multiplicity_policy"][
        "count_each_distinct_candidate_code_head"
    ] = False
    try:
        MOD.validate_contract(changed)
    except ValueError as exc:
        assert "multiplicity policy changed" in str(exc)
    else:
        raise AssertionError("weakened multiplicity policy was accepted")


def test_branch_only_candidates_remain_changed_path_blocked() -> None:
    census = source_census()
    census["experiment_candidates"].append(
        {
            "record_id": "github-branch:legacy-replay",
            "record_type": "BRANCH",
            "name": "legacy-replay",
            "head_sha": "c" * 40,
            "ancestry": "ORPHANED_FROM_AUDIT_HEAD",
            "capability_family_candidates": ["EXECUTION_COST_AND_LEDGER"],
            "matched_do_not_repeat_ids": [],
            "promotion_blockers": ["branch_changed_paths_unrecovered"],
        }
    )
    census["branches"].append(
        {
            "record_id": "github-branch:legacy-replay",
            "head_sha": "c" * 40,
        }
    )
    census["summary"]["branch_count"] += 1
    census["summary"]["experiment_candidate_count"] += 1
    census["summary"]["unmapped_experiment_candidate_count"] += 1
    recovered = MOD.build_recovery_census(census, inventory(), contract())
    row = next(
        item
        for item in recovered["recovered_candidates"]
        if item["record_type"] == "BRANCH"
    )
    assert "changed_paths_incomplete" in row[
        "legacy_result_promotion_blockers"
    ]
    assert row["multiplicity_weight"] == 1


def test_cli_writes_only_research_metadata() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        census_path = root / "source.json"
        inventory_path = root / "inventory.json"
        output = root / "output"
        census_path.write_text(json.dumps(source_census()), encoding="utf-8")
        inventory_path.write_text(json.dumps(inventory()), encoding="utf-8")
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "build_run287_u0_v3_recovery_census.py"),
                "--source-census",
                str(census_path),
                "--inventory",
                str(inventory_path),
                "--contract",
                str(CONTRACT_PATH),
                "--output-dir",
                str(output),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        assert sorted(path.name for path in output.iterdir()) == [
            "github_recovery_census.json",
            "github_recovery_census_summary.json",
            "recovered_experiment_candidates.csv",
        ]
        payload = MOD.read_json(output / "github_recovery_census.json")
        assert payload["safety"]["metadata_only"] is True
        assert payload["safety"]["fullrun_allowed"] is False
        assert payload["safety"]["target_order_ledger_mutation_allowed"] is False
        assert payload["safety"]["production_or_live_trading_allowed"] is False
        assert payload["safety"]["automatic_promotion_allowed"] is False


def test_workflow_publishes_recovery_only_as_diagnostic() -> None:
    source = (
        ROOT / ".github" / "workflows" / "run287_u0_acceptance.yml"
    ).read_text(encoding="utf-8")
    classify = "- name: Classify conservative U0-v3 recovery census"
    diagnostic = "name: run287-u0-census-diagnostic"
    acceptance = "- name: Require complete U0 and create acceptance envelope"
    accepted = "name: run287-u0-accepted-evidence"
    assert "build_run287_u0_v3_recovery_census.py" in source
    assert "github_recovery_census.json" in source
    assert "github_recovery_census_summary.json" in source
    assert "recovered_experiment_candidates.csv" in source
    assert source.index(classify) < source.index(diagnostic)
    assert source.index(diagnostic) < source.index(acceptance) < source.index(accepted)
    assert "acceptance_gate_migration_allowed_by_this_contract: true" not in source


def main() -> int:
    test_exact_head_aliases_are_deduplicated_and_counted_conservatively()
    test_source_and_contract_tampering_fail_closed()
    test_branch_only_candidates_remain_changed_path_blocked()
    test_cli_writes_only_research_metadata()
    test_workflow_publishes_recovery_only_as_diagnostic()
    print("run287_u0_v3_recovery_census_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
