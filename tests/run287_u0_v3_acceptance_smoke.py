"""Smoke tests for U0-v3 research-fit acceptance."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
for value in (ROOT, ROOT / "tests"):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

from tools import build_run287_u0_v3_acceptance as MOD  # noqa: E402
from tools import build_run287_u0_v3_recovery_census as V3  # noqa: E402
import run287_u0_v3_recovery_census_smoke as FIX  # noqa: E402


ACCEPTANCE_CONTRACT = (
    ROOT / "docs" / "run287_u0_v3_acceptance_contract.json"
)
RECOVERY_CONTRACT = ROOT / "docs" / "run287_u0_v3_recovery_contract.json"


def inputs() -> tuple[dict, dict, dict, dict, dict]:
    source = FIX.source_census()
    inventory = FIX.inventory()
    recovery_contract = V3.read_json(RECOVERY_CONTRACT)
    recovery = V3.build_recovery_census(
        source, inventory, recovery_contract
    )
    acceptance_contract = V3.read_json(ACCEPTANCE_CONTRACT)
    return (
        source,
        recovery,
        inventory,
        recovery_contract,
        acceptance_contract,
    )


def test_acceptance_binds_recomputed_recovery_and_trial_floor() -> None:
    source, recovery, inventory, recovery_contract, acceptance_contract = inputs()
    evidence = MOD.build_acceptance(
        source,
        recovery,
        inventory,
        recovery_contract,
        acceptance_contract,
        "f" * 40,
    )
    assert evidence["schema_version"] == MOD.EVIDENCE_SCHEMA
    assert evidence["workflow_identity"] == MOD.WORKFLOW_IDENTITY
    assert evidence["audit_default_branch"] == "master"
    assert evidence["audit_default_branch_sha"] == "f" * 40
    assert evidence["source_observed_at_utc"] == source["generated_at_utc"]
    assert evidence["repository_namespace_sha256"] == V3.canonical_sha256(
        V3.repository_namespace_payload(source)
    )
    assert evidence["source_census_sha256"] == V3.canonical_sha256(source)
    assert evidence["recovery_census_sha256"] == V3.canonical_sha256(
        recovery
    )
    assert evidence["conservative_historical_trial_count_lower_bound"] == 5
    assert evidence["historical_challenger_research_fit_allowed"] is True
    assert evidence["historical_broker_backtest_allowed"] is False
    assert evidence["legacy_result_promotion_allowed"] is False
    assert evidence["promotion_blockers"] == []
    assert evidence["target_order_ledger_mutation_allowed"] is False
    assert evidence["automatic_promotion_allowed"] is False
    assert evidence["fullrun_allowed"] is False


def test_tampered_recovery_and_broadened_scope_fail_closed() -> None:
    source, recovery, inventory, recovery_contract, acceptance_contract = inputs()
    tampered = json.loads(json.dumps(recovery))
    tampered["recovered_candidates"][0]["multiplicity_weight"] = 0
    try:
        MOD.build_acceptance(
            source,
            tampered,
            inventory,
            recovery_contract,
            acceptance_contract,
            "f" * 40,
        )
    except ValueError as exc:
        assert "does not match recomputation" in str(exc)
    else:
        raise AssertionError("tampered recovery census was accepted")

    broadened = json.loads(json.dumps(acceptance_contract))
    broadened["authorization_scope"]["historical_broker_backtest_allowed"] = True
    try:
        MOD.build_acceptance(
            source,
            recovery,
            inventory,
            recovery_contract,
            broadened,
            "f" * 40,
        )
    except ValueError as exc:
        assert "authorization scope changed" in str(exc)
    else:
        raise AssertionError("broadened U0 authorization was accepted")


def test_incomplete_candidate_discovery_cannot_be_accepted() -> None:
    source, _, inventory, recovery_contract, acceptance_contract = inputs()
    source["pull_requests"][0]["changed_paths_complete"] = False
    source["experiment_candidates"][0]["changed_paths_complete"] = False
    source["promotion_blockers"].append(
        "one_or_more_pr_changed_path_lists_are_truncated"
    )
    FIX.rehash_normalized_inventory(source)
    recovery = V3.build_recovery_census(source, inventory, recovery_contract)
    try:
        MOD.build_acceptance(
            source,
            recovery,
            inventory,
            recovery_contract,
            acceptance_contract,
            "f" * 40,
        )
    except ValueError as exc:
        assert "source_candidate_discovery_incomplete" in str(exc)
        assert "historical_experiment_census_incomplete" in str(exc)
    else:
        raise AssertionError("incomplete source candidate discovery was accepted")


def test_cli_and_workflow_publish_canonical_v3_evidence_only() -> None:
    source, recovery, inventory, recovery_contract, _ = inputs()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source_path = root / "github_census.json"
        recovery_path = root / "github_recovery_census.json"
        inventory_path = root / "inventory.json"
        recovery_contract_path = root / "recovery_contract.json"
        output = root / "u0_accepted_evidence.json"
        for path, value in (
            (source_path, source),
            (recovery_path, recovery),
            (inventory_path, inventory),
            (recovery_contract_path, recovery_contract),
        ):
            path.write_text(json.dumps(value), encoding="utf-8")
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "build_run287_u0_v3_acceptance.py"),
                "--source-census",
                str(source_path),
                "--recovery-census",
                str(recovery_path),
                "--inventory",
                str(inventory_path),
                "--recovery-contract",
                str(recovery_contract_path),
                "--acceptance-contract",
                str(ACCEPTANCE_CONTRACT),
                "--expected-audit-sha",
                "f" * 40,
                "--output",
                str(output),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        payload = V3.read_json(output)
        assert payload["historical_challenger_research_fit_allowed"] is True
        assert payload["historical_broker_backtest_allowed"] is False

    workflow = (
        ROOT / ".github" / "workflows" / "run287_u0_acceptance.yml"
    ).read_text(encoding="utf-8")
    assert "build_run287_u0_v3_acceptance.py" in workflow
    assert "github_recovery_census.json" in workflow
    assert "run287-u0-accepted-evidence" in workflow
    assert "run287-u0-accepted-evidence-v1" not in workflow
    assert "run287-u0-v2-acceptance" not in workflow


def main() -> int:
    test_acceptance_binds_recomputed_recovery_and_trial_floor()
    test_tampered_recovery_and_broadened_scope_fail_closed()
    test_incomplete_candidate_discovery_cannot_be_accepted()
    test_cli_and_workflow_publish_canonical_v3_evidence_only()
    print("run287_u0_v3_acceptance_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
