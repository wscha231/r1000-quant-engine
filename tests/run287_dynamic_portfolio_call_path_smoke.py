#!/usr/bin/env python3
"""Smoke-test the Run287 dynamic-portfolio call-path authority contract."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from copy import deepcopy
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import audit_run287_dynamic_portfolio_call_paths as MOD  # noqa: E402


CONTRACT_PATH = ROOT / "docs" / "run287_dynamic_portfolio_call_path_contract.json"


@lru_cache(maxsize=1)
def source_inputs() -> tuple[dict, dict[str, str], dict[str, str]]:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    tracked = MOD.tracked_workflow_paths(ROOT)
    workflows = MOD.workflow_texts(ROOT, tracked)
    accepted = {**MOD.tracked_python_texts(ROOT), **workflows}
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


def test_inline_writer_and_transitive_legacy_exit_fail_closed() -> None:
    contract, workflows, accepted = source_inputs()
    daily = contract["accepted_daily_workflow"]
    inline = deepcopy(workflows)
    needle = "from tools.build_run287_same_close_target_books import ("
    inline[daily] = inline[daily].replace(
        needle,
        "from tools.build_new_target_writer import main as new_main\n"
        "          new_main()\n"
        f"          {needle}",
        1,
    )
    inline_sources = deepcopy(accepted)
    inline_sources["tools/build_new_target_writer.py"] = "def main():\n    return None\n"
    result = MOD.audit_texts(contract, inline, inline_sources)
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "accepted_workflow_inline_import_mismatch" in item
        for item in result["failures"]
    )

    transitive = deepcopy(accepted)
    transitive["tools/run287_crisis_policy.py"] += (
        "\nfrom r1000_risk_sensing import evaluate_layer1_individual\n"
    )
    result = MOD.audit_texts(contract, workflows, transitive)
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "forbidden_legacy_exit_reachability:tools/run287_crisis_policy.py" in item
        for item in result["failures"]
    )


def test_required_transaction_boundary_cannot_be_removed() -> None:
    contract, workflows, accepted = source_inputs()
    changed = deepcopy(workflows)
    daily = contract["accepted_daily_workflow"]
    changed[daily] = changed[daily].replace("--suppress-new-orders", "--removed-boundary")
    changed[daily] += "\n# --suppress-new-orders\n"
    result = MOD.audit_texts(contract, changed, accepted)
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "required_executable_command_mismatch" in item
        for item in result["failures"]
    )

    inline_comment = deepcopy(workflows)
    inline_comment[daily] = inline_comment[daily].replace(
        "--suppress-new-orders \\",
        "# --suppress-new-orders \\",
        1,
    )
    result = MOD.audit_texts(contract, inline_comment, accepted)
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "required_executable_command_mismatch" in item
        for item in result["failures"]
    )

    shell_suffix = deepcopy(workflows)
    shell_suffix[daily] = shell_suffix[daily].replace(
        "--suppress-new-orders \\",
        "; : --suppress-new-orders \\",
        1,
    )
    result = MOD.audit_texts(contract, shell_suffix, accepted)
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "required_executable_command_mismatch" in item
        for item in result["failures"]
    )

    redirected = deepcopy(workflows)
    redirected[daily] = redirected[daily].replace(
        "--suppress-new-orders \\",
        "> --suppress-new-orders \\",
        1,
    )
    result = MOD.audit_texts(contract, redirected, accepted)
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "required_executable_command_mismatch" in item
        for item in result["failures"]
    )


def test_no_writer_role_and_duplicate_accepted_writer_fail_closed() -> None:
    contract, workflows, accepted = source_inputs()
    no_writer = deepcopy(workflows)
    observer = ".github/workflows/daily_crisis_monitor.yml"
    no_writer[observer] += "\n  python tools/build_new_target_writer.py\n"
    result = MOD.audit_texts(contract, no_writer, accepted)
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "workflow_authority_sensitive_mismatch" in item
        for item in result["failures"]
    )

    duplicate = deepcopy(workflows)
    daily = contract["accepted_daily_workflow"]
    duplicate[daily] += "\n  python tools/build_run287_same_close_target_books.py\n"
    result = MOD.audit_texts(contract, duplicate, accepted)
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "entrypoint_invocation_count_mismatch" in item
        for item in result["failures"]
    )

    module_mode = deepcopy(workflows)
    module_mode[daily] += (
        "\n  python -m tools.build_run287_same_close_target_books\n"
    )
    result = MOD.audit_texts(contract, module_mode, accepted)
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "entrypoint_invocation_count_mismatch" in item
        for item in result["failures"]
    )

    extra_ledger = deepcopy(workflows)
    extra_ledger[daily] += (
        "\n  python tools/run_daily_simulated_fill_ledger.py "
        "--as-of-date 2026-08-11 --decision-time-utc 2026-08-12T00:00:00Z\n"
    )
    result = MOD.audit_texts(contract, extra_ledger, accepted)
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "entrypoint_invocation_count_mismatch:"
        "tools/run_daily_simulated_fill_ledger.py" in item
        for item in result["failures"]
    )

    command_writer = deepcopy(workflows)
    command_writer[daily] += (
        "\n  python -c \"from tools.build_run287_same_close_target_books "
        "import main; main()\"\n"
    )
    result = MOD.audit_texts(contract, command_writer, accepted)
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "entrypoint_invocation_count_mismatch:"
        "tools/build_run287_same_close_target_books.py" in item
        for item in result["failures"]
    )

    moved_boundary = deepcopy(workflows)
    moved_boundary[daily] = moved_boundary[daily].replace(
        "            --suppress-new-orders \\\n",
        "",
        1,
    )
    second_profile = (
        "              --max-fill-lag-days 7 \\\n"
        "              2>&1 | tee outputs/full_rebuild_logs/"
        "daily_simulated_fill_ledger.log"
    )
    moved_boundary[daily] = moved_boundary[daily].replace(
        second_profile,
        "              --max-fill-lag-days 7 \\\n"
        "              --suppress-new-orders \\\n"
        "              2>&1 | tee outputs/full_rebuild_logs/"
        "daily_simulated_fill_ledger.log",
        1,
    )
    result = MOD.audit_texts(contract, moved_boundary, accepted)
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "exclusive_invocation_profile_mismatch" in item
        for item in result["failures"]
    )


def test_global_workflow_and_transitive_authority_allowlists_fail_closed() -> None:
    contract, workflows, accepted = source_inputs()
    undeclared = deepcopy(workflows)
    undeclared[".github/workflows/new_production.yml"] = (
        "jobs:\n  run:\n    steps:\n      - run: python tools/build_new_target_writer.py\n"
    )
    result = MOD.audit_texts(contract, undeclared, accepted)
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "authority_sensitive_workflow_role_missing" in item
        for item in result["failures"]
    )

    command_string = deepcopy(workflows)
    command_string[".github/workflows/new_command_string.yml"] = (
        "jobs:\n  run:\n    steps:\n      - run: >-\n"
        "          python -c \"from tools.build_new_target_writer import main; "
        "main()\"\n"
    )
    command_sources = deepcopy(accepted)
    command_sources["tools/build_new_target_writer.py"] = (
        "def main():\n    return None\n"
    )
    result = MOD.audit_texts(contract, command_string, command_sources)
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "authority_sensitive_workflow_role_missing:"
        ".github/workflows/new_command_string.yml" in item
        for item in result["failures"]
    )

    stdin_wrapper = deepcopy(workflows)
    stdin_wrapper[".github/workflows/new_stdin.yml"] = (
        "jobs:\n  run:\n    steps:\n      - run: |\n"
        "          python3.12 -u - <<'PY'\n"
        "          from tools.build_new_target_writer import main\n"
        "          main()\n"
        "          PY\n"
    )
    result = MOD.audit_texts(contract, stdin_wrapper, command_sources)
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "authority_sensitive_workflow_role_missing:"
        ".github/workflows/new_stdin.yml" in item
        for item in result["failures"]
    )

    shell_wrapper = deepcopy(workflows)
    shell_wrapper[".github/workflows/new_shell_wrapper.yml"] = (
        "jobs:\n  run:\n    steps:\n      - run: >-\n"
        "          bash -c 'python tools/build_new_target_writer.py'\n"
    )
    result = MOD.audit_texts(contract, shell_wrapper, command_sources)
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "authority_sensitive_workflow_role_missing:"
        ".github/workflows/new_shell_wrapper.yml" in item
        for item in result["failures"]
    )

    accepted_root = deepcopy(accepted)
    accepted_root["tools/build_run287_catchup_target_evidence.py"] += (
        "\nfrom r1000_risk_sensing import evaluate_layer1_individual\n"
    )
    result = MOD.audit_texts(contract, workflows, accepted_root)
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "forbidden_legacy_exit_reachability:"
        "tools/build_run287_catchup_target_evidence.py" in item
        for item in result["failures"]
    )

    transitive_writer = deepcopy(accepted)
    transitive_writer["tools/build_new_target_writer.py"] = "def main():\n    return None\n"
    transitive_writer["tools/build_run287_exact_packet_input_registry.py"] += (
        "\nfrom tools.build_new_target_writer import main as new_writer_main\n"
    )
    result = MOD.audit_texts(contract, workflows, transitive_writer)
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "accepted_reachable_authority_sensitive_mismatch" in item
        for item in result["failures"]
    )

    neutral_helper_workflow = deepcopy(workflows)
    neutral_helper_workflow[contract["accepted_daily_workflow"]] += (
        "\n  python tools/harmless.py\n"
    )
    neutral_helper_sources = deepcopy(accepted)
    neutral_helper_sources["tools/harmless.py"] = (
        "from tools.build_new_target_writer import main\nmain()\n"
    )
    neutral_helper_sources["tools/build_new_target_writer.py"] = (
        "def main():\n    return None\n"
    )
    result = MOD.audit_texts(
        contract,
        neutral_helper_workflow,
        neutral_helper_sources,
    )
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "accepted_workflow_local_entrypoint_mismatch" in item
        for item in result["failures"]
    )
    assert any(
        "accepted_reachable_authority_sensitive_mismatch" in item
        for item in result["failures"]
    )

    no_writer_helper = deepcopy(workflows)
    observer = ".github/workflows/daily_crisis_monitor.yml"
    no_writer_helper[observer] += "\n  python tools/harmless.py\n"
    result = MOD.audit_texts(
        contract,
        no_writer_helper,
        neutral_helper_sources,
    )
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "no_writer_reachable_authority_mismatch:" + observer in item
        for item in result["failures"]
    )

    missing_import = deepcopy(accepted)
    missing_import.pop("tools/run287_crisis_policy.py")
    known = set(accepted)
    result = MOD.audit_texts(
        contract,
        workflows,
        missing_import,
        known_python_paths=known,
    )
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "reachable_python_file_missing:tools/run287_crisis_policy.py" in item
        for item in result["failures"]
    )


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


def test_execution_defaults_are_bound_to_named_inputs() -> None:
    contract, workflows, accepted = source_inputs()
    after_close = deepcopy(workflows)
    path = ".github/workflows/after_close_daily.yml"
    after_close[path] = after_close[path].replace(
        "      allow_legacy_execute:\n"
        "        description: 'acknowledge old Alpaca paper executor bypasses account-ledger safety audit'\n"
        "        type: boolean\n"
        "        default: false",
        "      allow_legacy_execute:\n"
        "        description: 'acknowledge old Alpaca paper executor bypasses account-ledger safety audit'\n"
        "        type: boolean\n"
        "        default: true",
        1,
    )
    result = MOD.audit_texts(contract, after_close, accepted)
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "workflow_input_default_mismatch:"
        ".github/workflows/after_close_daily.yml:allow_legacy_execute" in item
        for item in result["failures"]
    )

    layer4 = deepcopy(workflows)
    path = ".github/workflows/layer4_monthly_swap.yml"
    layer4[path] = layer4[path].replace(
        "      execute:\n"
        "        description: 'execute LIVE paper swaps (default: dry-run only)'\n"
        "        type: boolean\n"
        "        default: false",
        "      execute:\n"
        "        description: 'execute LIVE paper swaps (default: dry-run only)'\n"
        "        type: boolean\n"
        "        default: true",
        1,
    )
    result = MOD.audit_texts(contract, layer4, accepted)
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "workflow_input_default_mismatch:"
        ".github/workflows/layer4_monthly_swap.yml:execute" in item
        for item in result["failures"]
    )


def test_dirty_input_is_not_attributed_to_head_and_defaults_follow_repo_root() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        tracked = root / "tracked.txt"
        tracked.write_text("clean\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "Run287 Test"], cwd=root, check=True)
        subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)
        clean = MOD.git_source_identity(root, ["tracked.txt"])
        assert clean["source_identity_status"] == "CLEAN_HEAD_BOUND"
        assert clean["source_commit_sha"] == clean["observed_head_sha"]

        tracked.write_text("dirty\n", encoding="utf-8")
        dirty = MOD.git_source_identity(root, ["tracked.txt"])
        assert dirty["source_identity_status"] == "DIRTY_INPUTS_NOT_HEAD_BOUND"
        assert dirty["source_commit_sha"] == ""
        assert dirty["dirty_input_records"]

        assert MOD.resolve_repo_path(root, MOD.DEFAULT_CONTRACT) == (
            root / "docs/run287_dynamic_portfolio_call_path_contract.json"
        ).resolve()
        assert MOD.resolve_repo_path(root, MOD.DEFAULT_OUTPUT) == (
            root / "outputs/run287_dynamic_portfolio_call_path_audit.json"
        ).resolve()


def main() -> int:
    test_current_repository_passes_and_has_one_accepted_writer()
    test_second_writer_and_legacy_exit_reachability_fail_closed()
    test_inline_writer_and_transitive_legacy_exit_fail_closed()
    test_required_transaction_boundary_cannot_be_removed()
    test_no_writer_role_and_duplicate_accepted_writer_fail_closed()
    test_global_workflow_and_transitive_authority_allowlists_fail_closed()
    test_untracked_workflow_is_not_repository_authority()
    test_execution_defaults_are_bound_to_named_inputs()
    test_dirty_input_is_not_attributed_to_head_and_defaults_follow_repo_root()
    print("run287 dynamic portfolio call-path smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
