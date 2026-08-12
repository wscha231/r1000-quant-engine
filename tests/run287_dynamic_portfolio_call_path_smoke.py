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

    for operator in ("&>", "&>>"):
        combined_redirect = deepcopy(workflows)
        combined_redirect[daily] = combined_redirect[daily].replace(
            "--suppress-new-orders \\",
            f"{operator} --suppress-new-orders \\",
            1,
        )
        result = MOD.audit_texts(contract, combined_redirect, accepted)
        assert result["status"] == MOD.BLOCKED_STATUS
        assert any(
            "required_executable_command_mismatch" in item
            for item in result["failures"]
        )

    duplicate_cost = deepcopy(workflows)
    duplicate_cost[daily] = duplicate_cost[daily].replace(
        "            --security-lifecycle-events data_static/run287_exact_packet/security_lifecycle_events.csv \\\n"
        "            --cost-bps 25 \\\n            --max-fill-lag-days 7 \\",
        "            --security-lifecycle-events data_static/run287_exact_packet/security_lifecycle_events.csv \\\n"
        "            --cost-bps 25 \\\n            --cost-bps 0 \\\n"
        "            --max-fill-lag-days 7 \\",
        1,
    )
    result = MOD.audit_texts(contract, duplicate_cost, accepted)
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "required_executable_command_mismatch" in item
        for item in result["failures"]
    )

    empty_handoff = deepcopy(workflows)
    empty_handoff[daily] = empty_handoff[daily].replace(
        '--target-handoff-manifest "$SAME_CLOSE_DIR/status.json" \\',
        '--target-handoff-manifest "" \\',
        1,
    )
    for option, variable in (
        ("--expected-target-handoff-sha256", "TARGET_HANDOFF_SHA"),
        ("--main-target-sha256", "MAIN_TARGET_SHA"),
        ("--concentrated-target-sha256", "CONCENTRATED_TARGET_SHA"),
    ):
        empty_handoff[daily] = empty_handoff[daily].replace(
            f"              {option} \"${variable}\" \\\n",
            "",
            1,
        )
    result = MOD.audit_texts(contract, empty_handoff, accepted)
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "required_executable_command_mismatch" in item
        for item in result["failures"]
    )

    expanded_empty_handoff = deepcopy(workflows)
    expanded_empty_handoff[daily] += '\n  EMPTY_HANDOFF=""\n'
    for value in (
        "$SAME_CLOSE_DIR/status.json",
        "$TARGET_HANDOFF_SHA",
        "$MAIN_TARGET_SHA",
        "$CONCENTRATED_TARGET_SHA",
    ):
        expanded_empty_handoff[daily] = expanded_empty_handoff[daily].replace(
            f'"{value}"', '"$EMPTY_HANDOFF"', 1
        )
    result = MOD.audit_texts(contract, expanded_empty_handoff, accepted)
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "required_executable_command_mismatch" in item
        for item in result["failures"]
    )

    reassigned_handoff = deepcopy(workflows)
    reassigned_handoff[daily] = reassigned_handoff[daily].replace(
        "            python tools/run_daily_simulated_fill_ledger.py \\",
        '            SAME_CLOSE_DIR="outputs/alternate"\n'
        '            TARGET_HANDOFF_SHA="alternate"\n'
        '            MAIN_TARGET_SHA="alternate"\n'
        '            CONCENTRATED_TARGET_SHA="alternate"\n'
        "            python tools/run_daily_simulated_fill_ledger.py \\",
        1,
    )
    result = MOD.audit_texts(contract, reassigned_handoff, accepted)
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "workflow_shell_variable_occurrence_mismatch:"
        ".github/workflows/daily_operating_selection_refresh.yml" in item
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

    dotted_command_writer = deepcopy(workflows)
    dotted_command_writer[daily] += (
        '\n  python -c "import tools.build_run287_same_close_target_books; '
        'tools.build_run287_same_close_target_books.main()"\n'
    )
    result = MOD.audit_texts(contract, dotted_command_writer, accepted)
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "entrypoint_invocation_count_mismatch:"
        "tools/build_run287_same_close_target_books.py" in item
        for item in result["failures"]
    )

    for direct_path in (
        "./tools/build_run287_same_close_target_books.py",
        "tools/build_run287_same_close_target_books.py",
        (ROOT / "tools" / "build_run287_same_close_target_books.py").as_posix(),
    ):
        direct_writer = deepcopy(workflows)
        direct_writer[daily] += f"\n  {direct_path}\n"
        result = MOD.audit_texts(contract, direct_writer, accepted)
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

    backslash_stdin_wrapper = deepcopy(workflows)
    backslash_stdin_wrapper[".github/workflows/new_backslash_stdin.yml"] = (
        "jobs:\n  run:\n    steps:\n      - run: |\n"
        "          python /dev/stdin <<\\PY\n"
        "          from tools.build_new_target_writer import main\n"
        "          main()\n"
        "          PY\n"
    )
    result = MOD.audit_texts(contract, backslash_stdin_wrapper, command_sources)
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "authority_sensitive_workflow_role_missing:"
        ".github/workflows/new_backslash_stdin.yml" in item
        or "reachable_authority_workflow_role_missing:"
        ".github/workflows/new_backslash_stdin.yml" in item
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

    dev_stdin_wrapper = deepcopy(workflows)
    dev_stdin_wrapper[".github/workflows/new_dev_stdin.yml"] = (
        "jobs:\n  run:\n    steps:\n      - run: |\n"
        "          python /dev/stdin <<'PY'\n"
        "          from tools.build_new_target_writer import main\n"
        "          main()\n"
        "          PY\n"
    )
    result = MOD.audit_texts(contract, dev_stdin_wrapper, command_sources)
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "authority_sensitive_workflow_role_missing:"
        ".github/workflows/new_dev_stdin.yml" in item
        or "reachable_authority_workflow_role_missing:"
        ".github/workflows/new_dev_stdin.yml" in item
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

    undeclared_neutral_helper = deepcopy(workflows)
    undeclared_neutral_helper[".github/workflows/new_neutral_helper.yml"] = (
        "jobs:\n  run:\n    steps:\n"
        "      - run: python tools/harmless.py\n"
    )
    result = MOD.audit_texts(
        contract,
        undeclared_neutral_helper,
        neutral_helper_sources,
    )
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "reachable_authority_workflow_role_missing:"
        ".github/workflows/new_neutral_helper.yml" in item
        for item in result["failures"]
    )

    declared_read_only_helper = deepcopy(workflows)
    read_only = ".github/workflows/pr_validation.yml"
    declared_read_only_helper[read_only] += "\n  python tools/harmless.py\n"
    result = MOD.audit_texts(
        contract,
        declared_read_only_helper,
        neutral_helper_sources,
    )
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "workflow_authority_fingerprint_mismatch:" + read_only in item
        for item in result["failures"]
    )

    dynamic_import_sources = deepcopy(accepted)
    dynamic_import_sources["tools/run_daily_crisis_monitor.py"] += (
        '\nimport importlib\n'
        'importlib.import_module("tools.build_run287_same_close_target_books").main()\n'
    )
    result = MOD.audit_texts(contract, workflows, dynamic_import_sources)
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "no_writer_reachable_authority_mismatch:" + observer in item
        for item in result["failures"]
    )

    for source in (
        '\nfrom importlib import import_module\nimport_module("tools.build_new_target_writer").main()\n',
        '\nimport importlib as il\nil.import_module("tools.build_new_target_writer").main()\n',
        '\nimport builtins as bi\nbi.__import__("tools.build_new_target_writer").main()\n',
    ):
        aliased_dynamic_sources = deepcopy(neutral_helper_sources)
        aliased_dynamic_sources["tools/run_daily_crisis_monitor.py"] += source
        result = MOD.audit_texts(contract, workflows, aliased_dynamic_sources)
        assert result["status"] == MOD.BLOCKED_STATUS
        assert any(
            "workflow_authority_fingerprint_mismatch:" + observer in item
            for item in result["failures"]
        )

    for shell_write in (
        "printf x > outputs/reports/operating_main_target_book.csv",
        "cp source.csv outputs/reports/operating_main_target_book.csv",
        "printf x | tee outputs/reports/operating_main_target_book.csv",
    ):
        shell_writer = deepcopy(workflows)
        shell_writer[observer] += f"\n  {shell_write}\n"
        result = MOD.audit_texts(contract, shell_writer, accepted)
        assert result["status"] == MOD.BLOCKED_STATUS
        assert any(
            "workflow_authority_fingerprint_mismatch:" + observer in item
            for item in result["failures"]
        )

    accepted_transitive_writer = deepcopy(accepted)
    accepted_transitive_writer["tools/audit_data_readiness.py"] += (
        '\nfrom pathlib import Path\n'
        'Path("outputs/reports/operating_main_target_book.csv").write_text("x")\n'
    )
    result = MOD.audit_texts(contract, workflows, accepted_transitive_writer)
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "workflow_authority_fingerprint_mismatch:"
        + contract["accepted_daily_workflow"] in item
        for item in result["failures"]
    )

    direct_write_sources = deepcopy(accepted)
    direct_write_sources["tools/run_daily_crisis_monitor.py"] += (
        '\nfrom pathlib import Path\n'
        'Path("outputs/reports/operating_main_target_book.csv").write_text("x")\n'
    )
    result = MOD.audit_texts(contract, workflows, direct_write_sources)
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "no_writer_authority_write_sink:" + observer in item
        for item in result["failures"]
    )

    open_write_sources = deepcopy(accepted)
    open_write_sources["tools/run_daily_crisis_monitor.py"] += (
        '\nwith open("outputs/reports/operating_main_target_book.csv", "w") as handle:\n'
        '    handle.write("x")\n'
    )
    result = MOD.audit_texts(contract, workflows, open_write_sources)
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "no_writer_authority_write_sink:" + observer in item
        for item in result["failures"]
    )

    for source in (
        '\nfrom pathlib import Path\nPath("outputs/reports/operating_main_target_book.csv").open("w").write("x")\n',
        '\nimport io\nio.open("outputs/reports/operating_main_target_book.csv", "w").write("x")\n',
        '\nimport builtins\nbuiltins.open("outputs/reports/operating_main_target_book.csv", "w").write("x")\n',
        '\nfrom io import open as io_open\nio_open("outputs/reports/operating_main_target_book.csv", "w").write("x")\n',
    ):
        qualified_open_sources = deepcopy(accepted)
        qualified_open_sources["tools/run_daily_crisis_monitor.py"] += source
        result = MOD.audit_texts(contract, workflows, qualified_open_sources)
        assert result["status"] == MOD.BLOCKED_STATUS
        assert any(
            "workflow_authority_fingerprint_mismatch:" + observer in item
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

    eager_layer4 = deepcopy(workflows)
    path = ".github/workflows/layer4_monthly_swap.yml"
    eager_layer4[path] = eager_layer4[path].replace(
        '          EXECUTE_FLAG=""',
        '          EXECUTE_FLAG="--execute --confirm"',
        1,
    )
    result = MOD.audit_texts(contract, eager_layer4, accepted)
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "workflow_shell_flag_derivation_mismatch:"
        ".github/workflows/layer4_monthly_swap.yml:EXECUTE_FLAG" in item
        for item in result["failures"]
    )

    for assignment in (
        'export EXECUTE_FLAG="--execute --confirm"',
        'export -x EXECUTE_FLAG="--execute --confirm"',
        'typeset EXECUTE_FLAG="--execute --confirm"',
    ):
        exported_layer4 = deepcopy(workflows)
        exported_layer4[path] = exported_layer4[path].replace(
            '          THROTTLE_FLAG=""',
            f"          {assignment}\n          THROTTLE_FLAG=\"\"",
            1,
        )
        result = MOD.audit_texts(contract, exported_layer4, accepted)
        assert result["status"] == MOD.BLOCKED_STATUS
        assert any(
            "workflow_shell_flag_derivation_mismatch:"
            ".github/workflows/layer4_monthly_swap.yml:EXECUTE_FLAG" in item
            for item in result["failures"]
        )

    eager_after_close = deepcopy(workflows)
    path = ".github/workflows/after_close_daily.yml"
    eager_after_close[path] = eager_after_close[path].replace(
        '          LEGACY_EXECUTE_FLAG=""',
        '          LEGACY_EXECUTE_FLAG="--allow-legacy-execute"',
        1,
    )
    result = MOD.audit_texts(contract, eager_after_close, accepted)
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "workflow_shell_flag_derivation_mismatch:"
        ".github/workflows/after_close_daily.yml:LEGACY_EXECUTE_FLAG" in item
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
        assert MOD.git_path_tracked_at_head(root, "tracked.txt") is True

        ignored = root / "outputs" / "audit.py"
        ignored.parent.mkdir()
        ignored.write_text("print('stale')\n", encoding="utf-8")
        (root / ".git" / "info" / "exclude").write_text(
            "outputs/\n", encoding="utf-8"
        )
        assert MOD.git_path_tracked_at_head(root, "outputs/audit.py") is False

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


def test_run_audit_binds_no_writer_traversal_sources_to_head() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / ".github" / "workflows").mkdir(parents=True)
        (root / "tools").mkdir()
        (root / "docs").mkdir()
        accepted_workflow = ".github/workflows/accepted.yml"
        observer_workflow = ".github/workflows/observer.yml"
        workflow_texts = {
            accepted_workflow: (
                "jobs:\n  run:\n    steps:\n"
                "      - run: python tools/build_run287_same_close_target_books.py\n"
            ),
            observer_workflow: (
                "jobs:\n  run:\n    steps:\n"
                "      - run: python tools/neutral.py\n"
            ),
        }
        for path, text in workflow_texts.items():
            target = root / path
            target.write_text(text, encoding="utf-8")
        (root / "tools" / "build_run287_same_close_target_books.py").write_text(
            "def main():\n    return None\n", encoding="utf-8"
        )
        (root / "tools" / "run_daily_simulated_fill_ledger.py").write_text(
            "def main():\n    return None\n", encoding="utf-8"
        )
        neutral = root / "tools" / "neutral.py"
        neutral.write_text("VALUE = 1\n", encoding="utf-8")
        contract = {
            "schema_version": MOD.SCHEMA_VERSION,
            "status": "RESEARCH_ONLY_STATIC_AUTHORITY_CONTRACT",
            "tracked_workflow_sha256": {
                path: MOD.text_sha256(text) for path, text in workflow_texts.items()
            },
            "writer_authority": {
                "accepted_current_target_writer": "tools/build_run287_same_close_target_books.py",
                "durable_paper_ledger_consumer": "tools/run_daily_simulated_fill_ledger.py",
            },
            "workflow_roles": {
                accepted_workflow: "accepted_daily_target",
                observer_workflow: "state_observer_no_target_writer",
            },
            "entrypoint_bindings": [
                {
                    "entrypoint": "tools/build_run287_same_close_target_books.py",
                    "role": "accepted_current_target_writer",
                    "exact_invocation_count": 1,
                    "allowed_workflows": [accepted_workflow],
                }
            ],
            "workflow_authority_sensitive_entrypoints": {
                accepted_workflow: ["tools/build_run287_same_close_target_books.py"]
            },
            "no_writer_reachable_authority_sensitive_modules": {
                observer_workflow: []
            },
            "no_writer_authority_write_sinks": {observer_workflow: []},
            "accepted_daily_workflow": accepted_workflow,
            "accepted_path_files": [
                accepted_workflow,
                "tools/build_run287_same_close_target_books.py",
            ],
            "accepted_workflow_authority_sensitive_entrypoints": [
                "tools/build_run287_same_close_target_books.py"
            ],
            "accepted_workflow_local_entrypoints": [
                "tools/build_run287_same_close_target_books.py"
            ],
            "accepted_reachable_authority_sensitive_modules": [
                "tools/build_run287_same_close_target_books.py"
            ],
            "accepted_workflow_inline_local_imports": [],
            "authority_sensitive_name_terms": ["target", "writer", "ledger"],
            "forbidden_accepted_path_tokens": ["forbidden_legacy_exit"],
            "required_workflow_input_defaults": [],
            "required_shell_boolean_flag_derivations": [],
            "required_workflow_tokens": {},
            "required_executable_commands": [],
            "safety": {
                "changes_investment_behavior": False,
                "target_mutation_authorized": False,
                "paper_execution_authorized": False,
                "fullrun_authorized": False,
                "production_activation_allowed": False,
                "live_trading_enabled": False,
                "automatic_promotion_allowed": False,
                "untracked_workflows_are_authority": False,
            },
        }
        contract_path = root / "docs" / "contract.json"
        contract_path.write_text(json.dumps(contract), encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "Run287 Test"], cwd=root, check=True)
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)

        clean = MOD.run_audit(root, contract, contract_path=contract_path)
        assert clean["source_identity_status"] == "CLEAN_HEAD_BOUND", clean["failures"]
        assert "tools/neutral.py" in clean["audit_input_paths"]
        assert clean["audit_runtime_head_bound"] is False
        assert "audit_runtime_outside_selected_repository" in clean["failures"]

        neutral.write_text("VALUE = 2\n", encoding="utf-8")
        dirty = MOD.run_audit(root, contract, contract_path=contract_path)
        assert dirty["source_identity_status"] == "DIRTY_INPUTS_NOT_HEAD_BOUND"
        assert dirty["source_commit_sha"] == ""
        assert any("tools/neutral.py" in row for row in dirty["dirty_input_records"])


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
    test_run_audit_binds_no_writer_traversal_sources_to_head()
    print("run287 dynamic portfolio call-path smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
