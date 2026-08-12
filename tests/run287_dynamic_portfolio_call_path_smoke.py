#!/usr/bin/env python3
"""Smoke-test the Run287 dynamic-portfolio call-path authority contract."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import audit_run287_dynamic_portfolio_call_paths as MOD  # noqa: E402


CONTRACT_PATH = ROOT / "docs" / "run287_dynamic_portfolio_call_path_contract.json"


def source_inputs() -> tuple[dict, dict[str, str], dict[str, str]]:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    tracked = MOD.tracked_workflow_paths(ROOT)
    workflows = MOD.workflow_texts(ROOT, tracked)
    accepted = {
        path: (ROOT / path).read_text(encoding="utf-8")
        for path in contract["accepted_path_files"]
    }
    return contract, workflows, accepted


def test_current_repository_passes_and_has_one_accepted_writer() -> None:
    contract, workflows, accepted = source_inputs()
    result = MOD.audit_texts(contract, workflows, accepted)
    assert result["status"] == MOD.PASS_STATUS, result["failures"]
    accepted_rows = [
        row for row in result["invocations"]
        if row["role"] == "accepted_current_target_writer"
    ]
    assert len(accepted_rows) == 1
    assert accepted_rows[0]["workflow"] == contract["accepted_daily_workflow"]
    assert result["safety"]["target_mutation_authorized"] is False
    assert result["safety"]["paper_execution_authorized"] is False


def test_second_writer_and_legacy_exit_reachability_fail_closed() -> None:
    contract, workflows, accepted = source_inputs()
    duplicate = deepcopy(workflows)
    weekly = ".github/workflows/weekly_data_refresh.yml"
    duplicate[weekly] += "\n  python tools/build_run287_same_close_target_books.py\n"
    result = MOD.audit_texts(contract, duplicate, accepted)
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any("entrypoint_workflow_mismatch" in item for item in result["failures"])

    reachable = deepcopy(accepted)
    accepted_writer = "tools/build_run287_same_close_target_books.py"
    reachable[accepted_writer] += (
        "\nfrom r1000_risk_sensing import evaluate_layer1_individual\n"
    )
    result = MOD.audit_texts(contract, workflows, reachable)
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any("forbidden_legacy_exit_reachability" in item for item in result["failures"])

    new_daily_writer = deepcopy(workflows)
    daily = contract["accepted_daily_workflow"]
    new_daily_writer[daily] += "\n  python tools/build_new_target_writer.py\n"
    result = MOD.audit_texts(contract, new_daily_writer, accepted)
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "accepted_workflow_sensitive_entrypoint_mismatch" in item
        for item in result["failures"]
    )


def test_required_transaction_boundary_cannot_be_removed() -> None:
    contract, workflows, accepted = source_inputs()
    changed = deepcopy(workflows)
    daily = contract["accepted_daily_workflow"]
    changed[daily] = changed[daily].replace("--suppress-new-orders", "--removed-boundary")
    result = MOD.audit_texts(contract, changed, accepted)
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any("required_workflow_token_missing" in item for item in result["failures"])


def test_untracked_workflow_is_not_repository_authority() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        workflows = root / ".github" / "workflows"
        workflows.mkdir(parents=True)
        tracked = workflows / "tracked.yml"
        untracked = workflows / "untracked.yml"
        tracked.write_text("name: tracked\n", encoding="utf-8")
        untracked.write_text("name: untracked\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "add", ".github/workflows/tracked.yml"], cwd=root, check=True)
        paths = MOD.tracked_workflow_paths(root)
        assert paths == [".github/workflows/tracked.yml"]


def main() -> int:
    test_current_repository_passes_and_has_one_accepted_writer()
    test_second_writer_and_legacy_exit_reachability_fail_closed()
    test_required_transaction_boundary_cannot_be_removed()
    test_untracked_workflow_is_not_repository_authority()
    print("run287 dynamic portfolio call-path smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
