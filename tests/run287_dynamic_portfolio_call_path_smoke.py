#!/usr/bin/env python3
"""Smoke-test the Run287 dynamic-portfolio call-path authority contract."""

from __future__ import annotations

import hashlib
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
    accepted = {
        **MOD.tracked_python_texts(ROOT),
        **MOD.tracked_shell_texts(ROOT),
        **MOD.workflow_texts(ROOT, MOD.tracked_local_action_paths(ROOT)),
        **workflows,
    }
    return contract, workflows, accepted


def test_current_repository_passes_and_has_one_accepted_writer() -> None:
    contract, workflows, accepted = source_inputs()
    result = MOD.audit_texts(contract, workflows, accepted)
    if result["status"] != MOD.PASS_STATUS:
        diagnostic_path = ".github/workflows/full_rebuild_manual.yml"
        evidence = result["workflow_authority_fingerprint_evidence"].get(
            diagnostic_path
        ) or {}
        print(
            "AUTHORITY_FINGERPRINT_DIAGNOSTIC="
            + json.dumps(
                {
                    "failures": result["failures"],
                    "workflow": diagnostic_path,
                    "fingerprint": result[
                        "workflow_authority_fingerprints"
                    ].get(diagnostic_path),
                    "evidence_categories": {
                        key: {
                            "count": len(values),
                            "sha256": MOD.canonical_sha256(values),
                            "items": values if len(values) <= 10 else [],
                        }
                        for key, values in sorted(evidence.items())
                    },
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
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
        '\nimport importlib\nload = importlib.import_module\nload("tools.build_new_target_writer").main()\n',
        '\nimport importlib\n(load := importlib.import_module)("tools.build_new_target_writer").main()\n',
        '\nimport importlib\nload, unused = (importlib.import_module, None)\nload("tools.build_new_target_writer").main()\n',
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
        "rsync source.csv outputs/reports/operating_main_target_book.csv",
        "sed -i 's/a/b/' outputs/reports/operating_main_target_book.csv",
        "ln -sf source.csv outputs/reports/operating_main_target_book.csv",
        "DEST=outputs/reports/operating_main_target_book.csv; rsync source.csv \"$DEST\"",
    ):
        shell_writer = deepcopy(workflows)
        shell_writer[observer] += f"\n  {shell_write}\n"
        result = MOD.audit_texts(contract, shell_writer, accepted)
        assert result["status"] == MOD.BLOCKED_STATUS
        assert any(
            "workflow_authority_fingerprint_mismatch:" + observer in item
            for item in result["failures"]
        )

    shell_helper_workflow = deepcopy(workflows)
    shell_helper_workflow[observer] += "\n  bash tools/authority_helper.sh\n"
    shell_helper_sources = deepcopy(accepted)
    shell_helper_sources["tools/authority_helper.sh"] = (
        "#!/usr/bin/env bash\n"
        "python tools/build_new_target_writer.py\n"
    )
    shell_helper_sources["tools/build_new_target_writer.py"] = (
        "def main():\n    return None\n"
    )
    result = MOD.audit_texts(
        contract, shell_helper_workflow, shell_helper_sources
    )
    assert result["status"] == MOD.BLOCKED_STATUS
    assert "tools/authority_helper.sh" in result[
        "workflow_shell_reachable_files"
    ][observer]
    assert any(
        "workflow_authority_fingerprint_mismatch:" + observer in item
        for item in result["failures"]
    )

    python_shell_workflow = deepcopy(workflows)
    read_only = ".github/workflows/new_python_shell.yml"
    python_shell_workflow[read_only] = (
        "jobs:\n  run:\n    steps:\n"
        "      - shell: python\n"
        "        run: |\n"
        "          import importlib\n"
        "          importlib.import_module(\"tools.build_new_target_writer\").main()\n"
    )
    result = MOD.audit_texts(
        contract, python_shell_workflow, shell_helper_sources
    )
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "workflow_authority_fingerprint_mismatch:" + read_only in item
        for item in result["failures"]
    )

    for wrapper in ("time", "exec -a harmless"):
        wrapped_writer = deepcopy(workflows)
        daily = contract["accepted_daily_workflow"]
        wrapped_writer[daily] += (
            f"\n  {wrapper} tools/build_run287_same_close_target_books.py\n"
        )
        result = MOD.audit_texts(contract, wrapped_writer, accepted)
        assert result["status"] == MOD.BLOCKED_STATUS
        assert any(
            "entrypoint_invocation_count_mismatch:"
            "tools/build_run287_same_close_target_books.py" in item
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
        '\nfrom pathlib import Path\npath = Path("outputs/reports/operating_main_target_book.csv")\npath.open("w").write("x")\n',
        '\ndestination = "outputs/reports/operating_main_target_book.csv"\nopen(destination, "w").write("x")\n',
        '\nfrom pathlib import Path\npath = Path("outputs/reports/operating_main_target_book.csv")\npath.write_text("x")\n',
        '\nimport shutil\nshutil.copyfile("source.csv", "outputs/reports/operating_main_target_book.csv")\n',
        '\nfrom shutil import copytree\ncopytree("source", "outputs/reports/operating_main_target_book")\n',
        '\nimport shutil\nshutil.rmtree("outputs/reports/operating_main_target_book")\n',
        '\nfrom pathlib import Path\nPath("outputs/reports/operating_main_target_book.csv").unlink()\n',
        '\nfrom pathlib import Path\np = Path("outputs/reports/operating_main_target_book.csv")\np = Path("outputs/harmless.txt")\np.unlink()\n',
    ):
        qualified_open_sources = deepcopy(accepted)
        qualified_open_sources["tools/run_daily_crisis_monitor.py"] += source
        result = MOD.audit_texts(contract, workflows, qualified_open_sources)
        assert result["status"] == MOD.BLOCKED_STATUS
        assert any(
            "workflow_authority_fingerprint_mismatch:" + observer in item
            for item in result["failures"]
        )

    for prefix in ("MODE=x ", "env MODE=x "):
        assigned_direct_writer = deepcopy(workflows)
        daily = contract["accepted_daily_workflow"]
        assigned_direct_writer[daily] += (
            f"\n  {prefix}tools/build_run287_same_close_target_books.py\n"
        )
        result = MOD.audit_texts(contract, assigned_direct_writer, accepted)
        assert result["status"] == MOD.BLOCKED_STATUS
        assert any(
            "entrypoint_invocation_count_mismatch:"
            "tools/build_run287_same_close_target_books.py" in item
            for item in result["failures"]
        )

    inline_python_write = deepcopy(workflows)
    inline_python_write[observer] += (
        "\n  python -c 'from pathlib import Path; "
        'Path("outputs/reports/operating_main_target_book.csv").write_text("x")\'\n'
    )
    result = MOD.audit_texts(contract, inline_python_write, accepted)
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "workflow_authority_fingerprint_mismatch:" + observer in item
        for item in result["failures"]
    )

    subprocess_writer_sources = deepcopy(neutral_helper_sources)
    subprocess_writer_sources["tools/run_daily_crisis_monitor.py"] += (
        "\nimport subprocess, sys\nfrom pathlib import Path\n"
        'subprocess.run([sys.executable, str(Path("tools") / '
        '"build_new_target_writer.py")])\n'
    )
    result = MOD.audit_texts(contract, workflows, subprocess_writer_sources)
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "workflow_authority_fingerprint_mismatch:" + observer in item
        for item in result["failures"]
    )

    keyword_subprocess_sources = deepcopy(accepted)
    keyword_subprocess_sources["tools/run_daily_crisis_monitor.py"] += (
        "\nimport subprocess\n"
        'subprocess.run(args=["python", "tools/build_new_target_writer.py"])\n'
    )
    result = MOD.audit_texts(contract, workflows, keyword_subprocess_sources)
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "workflow_authority_fingerprint_mismatch:" + observer in item
        for item in result["failures"]
    )

    reassigned_process_sources = deepcopy(accepted)
    reassigned_process_sources["tools/run_daily_crisis_monitor.py"] += (
        "\nimport subprocess\n"
        'command = ["python", "tools/build_new_target_writer.py"]\n'
        'command = ["python", "tools/harmless.py"]\n'
        "subprocess.run(command)\n"
    )
    result = MOD.audit_texts(contract, workflows, reassigned_process_sources)
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "workflow_authority_fingerprint_mismatch:" + observer in item
        for item in result["failures"]
    )

    transitive_protected_call = deepcopy(accepted)
    transitive_protected_call["tools/run_daily_crisis_monitor.py"] += (
        "\nfrom tools import build_run287_same_close_target_books as protected\n"
        "protected.main()\n"
    )
    result = MOD.audit_texts(contract, workflows, transitive_protected_call)
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "entrypoint_invocation_count_mismatch:"
        "tools/build_run287_same_close_target_books.py" in item
        for item in result["failures"]
    )

    unresolved_process_sources = deepcopy(accepted)
    unresolved_process_sources["tools/run_daily_crisis_monitor.py"] += (
        "\nimport subprocess\nsubprocess.run(dynamic_command)\n"
    )
    result = MOD.audit_texts(contract, workflows, unresolved_process_sources)
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "workflow_authority_fingerprint_mismatch:" + observer in item
        for item in result["failures"]
    )

    process_source = (
        "import subprocess\n"
        'command = ["python", "tools/build_new_target_writer.py"]\n'
        "subprocess.run(command)\n"
    )
    process_findings = MOD.python_process_launches(process_source)
    expected_binding_source = json.dumps(
        sorted(
            {
                "command",
                '["python", "tools/build_new_target_writer.py"]',
            }
        ),
        separators=(",", ":"),
    )
    expected_expression_hash = hashlib.sha256(
        expected_binding_source.encode("utf-8")
    ).hexdigest()[:16]
    assert len(process_findings) == 1
    assert f"argv={expected_expression_hash}:" in process_findings[0]

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


def test_indirect_execution_and_destination_bypasses_fail_closed() -> None:
    contract, workflows, accepted = source_inputs()
    observer = ".github/workflows/daily_crisis_monitor.yml"

    assert MOD.shell_uses_indirect_assignment(
        'name="AFTER_CLOSE_LAYER4_ARGS"\nbuiltin read "$name"'
    )
    assert dict(
        MOD.python_main_call_counts(
            "from tools import build_run287_same_close_target_books as protected\n"
            "invoke = protected.main\n"
            "invoke()\n",
            "tools/helper.py",
        )
    )["tools/build_run287_same_close_target_books.py"] == 1
    assert dict(
        MOD.python_main_call_counts(
            "from .build_run287_same_close_target_books import main\n"
            "main()\n",
            "tools/helper.py",
        )
    )["tools/build_run287_same_close_target_books.py"] == 1

    inherited = (
        "defaults:\n  run:\n    shell: python\n"
        "jobs:\n  audit:\n    steps:\n      - run: |\n          print('x')\n"
    )
    assert MOD.workflow_python_shell_sources(inherited)[0]["source"].strip() == "print('x')"
    job_inherited = (
        "jobs:\n  audit:\n    defaults:\n      run:\n        shell: python\n"
        "    steps:\n      - run: |\n          print('y')\n"
    )
    assert MOD.workflow_python_shell_sources(job_inherited)[0]["source"].strip() == "print('y')"

    assert MOD.python_entrypoints("env -S 'python tools/harmless.py'") == {
        "tools/harmless.py"
    }
    assert MOD.python_entrypoints(
        'SCRIPT=tools/harmless.py\npython "$SCRIPT"'
    ) == {"tools/harmless.py"}
    assert MOD.python_entrypoints(
        'CMD="python tools/harmless.py"\nbash -c "$CMD"'
    ) == {"tools/harmless.py"}
    assigned_python_source = MOD.python_invocations(
        "CMD='from tools.build_run287_same_close_target_books import main; main()'\n"
        'python -c "$CMD"\n'
    )[0]["command_source"]
    assert dict(MOD.python_main_call_counts(str(assigned_python_source)))[
        "tools/build_run287_same_close_target_books.py"
    ] == 1
    assert MOD.python_invocations(
        "echo python tools/build_run287_same_close_target_books.py\n"
    ) == ()
    assert MOD.python_entrypoints("python -m tools.helper") == {
        "tools/helper.py",
        "tools/helper/__main__.py",
    }
    assert any(
        "dynamic-shell-c:UNRESOLVED_COMMAND" in finding
        for finding in MOD.shell_authority_write_sinks(
            'bash -c "$DYNAMIC_CMD"', ("target",)
        )
    )
    assert "tools/helper.py" in MOD.local_import_candidates(
        'import importlib\nimportlib.import_module(".helper", package="tools")\n',
        "tools/launcher.py",
    )

    first_unresolved = MOD.authority_write_sinks(
        'from pathlib import Path\ndef emit(dest="a"):\n    Path(dest).write_text("x")\n',
        ("target",),
    )
    second_unresolved = MOD.authority_write_sinks(
        'from pathlib import Path\ndef emit(dest="b"):\n    Path(dest).write_text("x")\n',
        ("target",),
    )
    assert first_unresolved != second_unresolved
    assert "binding=" in first_unresolved[0]
    assert any(
        ":rename:target" in finding
        for finding in MOD.authority_write_sinks(
            'import os\nos.rename(source, "outputs/main_target.csv")\n',
            ("target",),
        )
    )
    assert any(
        "unclassified-authority-operand:rm:outputs/main_target.csv:target"
        in finding
        for finding in MOD.shell_authority_write_sinks(
            'DEST=outputs/main_target.csv\nrm "$DEST"', ("target",)
        )
    )
    assert any(
        "tools/harmless.py" in finding
        for finding in MOD.python_process_launches(
            'import os\nos.execv("python", ["python", "tools/harmless.py"])\n'
        )
    )
    assert "tools/harmless.py" in MOD.local_process_candidates(
        'import subprocess\nsubprocess.getoutput("python tools/harmless.py")\n'
    )
    assert MOD.python_process_launches(
        'import subprocess\nsubprocess.getstatusoutput("python tools/harmless.py")\n'
    )
    assert "tools/harmless.py" in MOD.local_process_candidates(
        "import subprocess\nlaunch = subprocess.run\n"
        'launch(["python", "tools/harmless.py"])\n'
    )
    assert MOD.python_process_launches(
        "import subprocess\nlaunch = subprocess.run\n"
        'launch(["python", "tools/harmless.py"])\n'
    )
    variable_launch = (
        "import subprocess\nSCRIPT = 'tools/harmless.py'\n"
        'subprocess.run(["python", SCRIPT])\n'
    )
    assert "tools/harmless.py" in MOD.local_process_candidates(variable_launch)
    assert "tools/harmless.py" in MOD.python_process_launches(variable_launch)[0]
    assert "tools/harmless.txt" in MOD.local_process_candidates(
        'import subprocess\nsubprocess.run(["python", "tools/harmless.txt"])\n'
    )
    here_sources = MOD.embedded_python_sources(
        "python - <<< 'from tools.build_new_target_writer import main; main()'"
    )
    assert any(source["kind"] == "here-string" for source in here_sources)
    assert dict(MOD.python_main_call_counts(here_sources[0]["source"]))[
        "tools/build_new_target_writer.py"
    ] == 1
    dashed_heredoc = MOD.inline_python_blocks(
        "python - <<'PY-CODE'\n"
        "from tools.build_new_target_writer import main\n"
        "main()\nPY-CODE\n"
    )
    assert dict(MOD.python_main_call_counts(dashed_heredoc[0]["source"]))[
        "tools/build_new_target_writer.py"
    ] == 1
    assert dict(
        MOD.python_main_call_counts(
            "from tools import build_run287_same_close_target_books as protected\n"
            'getattr(protected, "main")()\n'
        )
    )["tools/build_run287_same_close_target_books.py"] == 1
    assert any(
        ":open:target" in finding
        for finding in MOD.authority_write_sinks(
            'writer = open\nwriter("outputs/main_target.csv", "w")\n',
            ("target",),
        )
    )
    assert any(
        ":os.open:target" in finding
        for finding in MOD.authority_write_sinks(
            'import os\nos.open("outputs/main_target.csv", os.O_WRONLY | os.O_TRUNC)\n',
            ("target",),
        )
    )
    assert "tools/harmless.py" in MOD.local_import_candidates(
        'import runpy\nrunpy.run_path("tools/harmless.py")\n',
        "tools/launcher.py",
    )
    assert "tools/harmless.py" in MOD.local_import_candidates(
        'from runpy import run_module as execute\n'
        'execute("tools.harmless", run_name="__main__")\n',
        "tools/launcher.py",
    )

    shell_sources = {
        "tools/authority_helper": "python tools/build_new_target_writer.py\n"
    }
    shell_root = MOD.local_shell_script_paths(
        "bash tools/authority_helper", set(shell_sources)
    )
    assert MOD.reachable_shell_paths(shell_root, shell_sources) == {
        "tools/authority_helper"
    }
    assert MOD.local_process_shell_paths(
        'import subprocess\nsubprocess.run(["bash", "tools/authority_helper"])\n',
        set(shell_sources),
    ) == {"tools/authority_helper"}
    assert MOD.local_shell_script_paths(
        "bash helper.bash", {"tools/helper.bash"}, "tools"
    ) == {"tools/helper.bash"}
    workdir_records = MOD.workflow_run_records(
        "defaults:\n  run:\n    working-directory: tools\n"
        "jobs:\n  audit:\n    steps:\n      - run: python harmless.py\n"
    )
    assert MOD.resolved_workflow_python_invocations(
        [("workflow.yml", *workdir_records[0])]
    )[0]["entrypoint"] == "tools/harmless.py"

    local_path = ".github/workflows/local_action_probe.yml"
    local_workflow = (
        "jobs:\n  audit:\n    steps:\n      - uses: ./tools/authority-action\n"
    )
    local_action_sources = {"tools/authority-action/action.yml": (
        "runs:\n  using: composite\n  steps:\n"
        "    - shell: bash\n"
        "      run: python tools/build_new_target_writer.py\n"
    )}
    assert MOD.reachable_local_yaml_paths(
        local_path, local_workflow, local_action_sources
    ) == {"tools/authority-action/action.yml"}
    action_run_text = MOD.workflow_run_text(
        local_action_sources["tools/authority-action/action.yml"]
    )
    assert "tools/build_new_target_writer.py" in MOD.python_entrypoints(
        action_run_text
    )
    node_action = (
        "runs:\n  using: node20\n  pre: setup.js\n"
        "  main: index.js\n  post: cleanup.js\n"
    )
    assert MOD.local_action_implementation_paths(
        "tools/node-action/action.yml",
        node_action,
        {
            "tools/node-action/setup.js",
            "tools/node-action/index.js",
            "tools/node-action/cleanup.js",
        },
    ) == {
        "tools/node-action/setup.js",
        "tools/node-action/index.js",
        "tools/node-action/cleanup.js",
    }

    unsupported = deepcopy(workflows)
    unsupported[observer] = unsupported[observer].replace(
        "        run: |",
        "        shell: node {0}\n        run: |",
        1,
    )
    unsupported_result = MOD.audit_texts(contract, unsupported, accepted)
    assert any(
        "unsupported_declared_shell:" + observer in failure
        for failure in unsupported_result["failures"]
    )


def test_reviewed_execution_edges_are_inventory_bound() -> None:
    protected = "tools/build_run287_same_close_target_books.py"
    helper_source = (
        "from tools import build_run287_same_close_target_books as protected\n"
        "def invoke():\n    protected.main()\n"
        "invoke()\ninvoke()\n"
    )
    assert dict(MOD.python_main_call_counts(helper_source))[protected] == 2
    assert protected not in dict(
        MOD.python_main_call_counts(
            "from tools import build_run287_same_close_target_books as protected\n"
            "def never_called():\n    protected.main()\n"
        )
    )

    assert any(
        ":open:target" in finding
        for finding in MOD.authority_write_sinks(
            'MODE = "w"\nopen("outputs/main_target.csv", MODE)\n',
            ("target",),
        )
    )
    assert any(
        "UNRESOLVED_MODE" in finding
        for finding in MOD.authority_write_sinks(
            'open("outputs/main_target.csv", dynamic_mode)\n',
            ("target",),
        )
    )
    assert any(
        ":os.truncate:target" in finding
        for finding in MOD.authority_write_sinks(
            'from os import truncate as cut\ncut("outputs/main_target.csv", 0)\n',
            ("target",),
        )
    )

    action = (
        "runs:\n  using: composite\n  steps:\n"
        "    - shell: bash\n"
        "      run: python ${{ github.action_path }}/writer.py\n"
    )
    records = MOD.workflow_run_records(action, "tools/authority-action/action.yml")
    assert "tools/authority-action/writer.py" in MOD.python_entrypoints(records[0][1])
    action_env = action.replace(
        "${{ github.action_path }}", "$GITHUB_ACTION_PATH"
    )
    records = MOD.workflow_run_records(
        action_env, "tools/authority-action/action.yml"
    )
    assert "tools/authority-action/writer.py" in MOD.python_entrypoints(records[0][1])
    assert "tools/harmless.py" in MOD.python_entrypoints(
        "( python tools/harmless.py )"
    )

    async_source = (
        "import asyncio\n"
        "await asyncio.create_subprocess_exec("
        '"python", "worker.py", cwd="tools")\n'
    )
    assert "tools/worker.py" in MOD.local_process_candidates(async_source)
    assert any("create_subprocess_exec" in row for row in MOD.python_process_launches(async_source))
    first_cwd = MOD.python_process_launches(
        'import subprocess\nsubprocess.run(["python", "worker.py"], cwd="tools")\n'
    )
    second_cwd = MOD.python_process_launches(
        'import subprocess\nsubprocess.run(["python", "worker.py"], cwd="jobs")\n'
    )
    assert first_cwd != second_cwd

    exec_source = (
        "exec('from tools.build_run287_same_close_target_books "
        "import main; main()')\n"
    )
    assert dict(MOD.python_main_call_counts(exec_source))[protected] == 1
    assert dict(
        MOD.python_main_call_counts(
            "from builtins import exec as execute\n"
            "execute('from tools.build_run287_same_close_target_books "
            "import main; main()')\n"
        )
    )[protected] == 1
    assert protected in MOD.local_import_candidates(exec_source, "tools/helper.py")
    assert any(
        "dynamic-exec" in finding and "target" in finding
        for finding in MOD.authority_write_sinks(
            'exec(\'open("outputs/main_target.csv", "w")\')\n',
            ("target",),
        )
    )
    assert "tools/harmless.py" in MOD.local_process_candidates(
        'exec(\'import subprocess; '
        'subprocess.run(["python", "tools/harmless.py"])\')\n'
    )

    unresolved = MOD.python_invocations('python "${{ inputs.script }}"\n')
    assert unresolved and unresolved[0]["unresolved_entrypoint"] is True
    assert MOD.invocation_matches_requirement(
        ["tool.py", "--required"], {"required_flags": ["--required"]}
    )
    assert not MOD.invocation_matches_requirement(
        ["tool.py", "--", "--required"], {"required_flags": ["--required"]}
    )
    disabled = (
        "jobs:\n  disabled:\n    if: false\n    steps:\n"
        "      - run: python tools/writer.py\n"
        "  enabled:\n    steps:\n"
        "      - if: false\n        run: python tools/writer.py\n"
    )
    assert MOD.workflow_run_records(disabled, "workflow.yml") == ()

    package_only = (
        "from . import build_run287_same_close_target_books as writer\n"
        "writer.main()\n"
    )
    assert dict(MOD.python_main_call_counts(package_only, "tools/helper.py"))[
        protected
    ] == 1
    assert dict(
        MOD.python_main_call_counts(
            'import runpy\nrunpy.run_module('
            '"tools.build_run287_same_close_target_books", run_name="__main__")\n'
        )
    )[protected] == 1
    attached = MOD.python_invocations(
        "python -c'from tools.build_run287_same_close_target_books import main; main()'\n"
    )
    assert attached[0]["entrypoint"] == "-c"
    assert dict(MOD.python_main_call_counts(str(attached[0]["command_source"])))[
        protected
    ] == 1
    assert MOD.python_entrypoints(
        "PYTHONPATH=tools python tools/harmless.py\n"
    ) >= {"tools/sitecustomize.py", "tools/usercustomize.py"}
    assert "tools/sitecustomize.py" not in MOD.python_entrypoints(
        "PYTHONPATH=tools python -I tools/harmless.py\n"
    )


def test_latest_review_execution_context_edges_are_bound() -> None:
    protected = "tools/build_run287_same_close_target_books.py"
    uncalled = (
        "never() {\n"
        "  python tools/build_run287_same_close_target_books.py\n"
        "}\n"
    )
    assert protected not in MOD.python_entrypoints(uncalled)
    called_twice = uncalled + "never\nnever\n"
    assert len(MOD.executable_invocations(called_twice, protected)) == 2

    disabled_action_workflow = (
        "jobs:\n  audit:\n    steps:\n"
        "      - if: false\n        uses: ./tools/disabled-action\n"
        "      - uses: ./tools/enabled-action\n"
    )
    known_actions = {
        "tools/disabled-action/action.yml",
        "tools/enabled-action/action.yml",
    }
    assert MOD.local_uses_paths(disabled_action_workflow, known_actions) == {
        "tools/enabled-action/action.yml"
    }

    workflow_env = (
        "env:\n  PYTHONPATH: tools/hooks\n"
        "jobs:\n  audit:\n    steps:\n"
        "      - run: python tools/harmless.py\n"
    )
    env_records = MOD.workflow_run_records(workflow_env, "workflow.yml")
    assert MOD.python_entrypoints(env_records[0][1]) >= {
        "tools/hooks/sitecustomize.py",
        "tools/hooks/usercustomize.py",
    }
    job_step_env = (
        "env:\n  PYTHONPATH: ignored\n"
        "jobs:\n  audit:\n    env:\n      PYTHONPATH: job\n"
        "    steps:\n      - env:\n          PYTHONPATH: step\n"
        "        run: python tools/harmless.py\n"
    )
    assert MOD.python_entrypoints(
        MOD.workflow_run_records(job_step_env, "workflow.yml")[0][1]
    ) >= {"step/sitecustomize.py", "step/usercustomize.py"}

    contract, workflows, accepted = source_inputs()
    direct = deepcopy(workflows)
    daily = contract["accepted_daily_workflow"]
    direct[daily] = direct[daily].replace(
        "python tools/build_run287_same_close_target_books.py",
        "tools/build_run287_same_close_target_books.py",
        1,
    )
    result = MOD.audit_texts(contract, direct, accepted)
    assert any(
        "unverified_direct_python_executable:" + daily in failure
        for failure in result["failures"]
    )

    assert any(
        ":move:target" in finding
        for finding in MOD.authority_write_sinks(
            'import shutil\nshutil.move('
            '"outputs/operating_main_target_book.csv", "tmp/archive.csv")\n',
            ("target",),
        )
    )

    docker_action = (
        "runs:\n  using: docker\n  image: Dockerfile\n"
    )
    docker_paths = {
        "tools/docker-action/action.yml",
        "tools/docker-action/Dockerfile",
        "tools/docker-action/entrypoint.sh",
        "tools/docker-action/assets/config.json",
        "tools/unrelated.txt",
    }
    assert MOD.local_action_implementation_paths(
        "tools/docker-action/action.yml", docker_action, docker_paths
    ) == {
        "tools/docker-action/action.yml",
        "tools/docker-action/Dockerfile",
        "tools/docker-action/entrypoint.sh",
        "tools/docker-action/assets/config.json",
    }


def test_shell_and_loader_authority_edges_fail_closed() -> None:
    protected = "tools/build_run287_same_close_target_books.py"
    one_line = (
        "never() { python tools/build_run287_same_close_target_books.py; }; true\n"
    )
    assert protected not in MOD.python_entrypoints(one_line)
    function_form = (
        "function never { python tools/build_run287_same_close_target_books.py; }; true\n"
    )
    assert protected not in MOD.python_entrypoints(function_form)
    assert len(
        MOD.executable_invocations(
            one_line.replace("; }; true", "; }; never"), protected
        )
    ) == 1
    assert protected not in MOD.python_entrypoints(
        "false && python tools/build_run287_same_close_target_books.py || true\n"
    )

    action = (
        "runs:\n  using: composite\n  steps:\n"
        "    - shell: bash\n      run: python worker.py\n"
    )
    inherited = MOD.workflow_run_records(
        action,
        "tools/action/action.yml",
        ("tools/hooks",),
    )
    assert MOD.python_entrypoints(inherited[0][1]) >= {
        "tools/hooks/sitecustomize.py",
        "tools/hooks/usercustomize.py",
    }

    expanded = (
        "CMD='python tools/build_run287_same_close_target_books.py'\n$CMD\n"
    )
    assert protected in MOD.python_entrypoints(expanded)
    pipeline = MOD.python_invocations("base64 -d payload.txt | python -\n")
    assert pipeline and pipeline[0]["unresolved_stdin_pipeline"] is True

    loader = (
        "import importlib.util\n"
        "spec = importlib.util.spec_from_file_location("
        "'helper', 'tools/helper.py')\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(module)\n"
    )
    assert "tools/helper.py" in MOD.local_import_candidates(
        loader, "tools/launcher.py"
    )

    node_action = "runs:\n  using: node20\n  main: index.js\n"
    node_paths = {
        "tools/node-action/action.yml",
        "tools/node-action/index.js",
        "tools/node-action/helper.js",
        "tools/other.js",
    }
    assert MOD.local_action_implementation_paths(
        "tools/node-action/action.yml", node_action, node_paths
    ) == {
        "tools/node-action/action.yml",
        "tools/node-action/index.js",
        "tools/node-action/helper.js",
    }

    definition_time = (
        "from tools import build_run287_same_close_target_books as protected\n"
        "def helper(value=protected.main()):\n    pass\n"
    )
    assert dict(MOD.python_main_call_counts(definition_time))[protected] == 1
    assert MOD.normalize_script_entrypoint("tools/../jobs/helper.py") == (
        "jobs/helper.py"
    )
    budgeted = "\n".join("true" for _ in range(10001))
    assert MOD.shell_logical_commands(budgeted)[-1][1] == (
        MOD.SHELL_EXPANSION_BUDGET_SENTINEL
    )


def test_static_control_and_indirect_launch_edges_are_bound() -> None:
    protected = "tools/build_run287_same_close_target_books.py"
    false_if = (
        "if false; then\n"
        "  python tools/build_run287_same_close_target_books.py\n"
        "fi\n"
    )
    false_while = (
        "while false; do\n"
        "  python tools/build_run287_same_close_target_books.py\n"
        "done\n"
    )
    assert protected not in MOD.python_entrypoints(false_if)
    assert protected not in MOD.python_entrypoints(false_while)
    assert protected in MOD.python_entrypoints(
        "until false; do\n"
        "  python tools/build_run287_same_close_target_books.py\n"
        "  break\n"
        "done\n"
    )
    assert protected not in MOD.python_entrypoints(
        "until true; do\n"
        "  python tools/build_run287_same_close_target_books.py\n"
        "done\n"
    )
    assert protected not in MOD.python_entrypoints(
        "if false; then python tools/build_run287_same_close_target_books.py; fi\n"
    )
    assert protected in MOD.python_entrypoints(
        "if false; then :; else "
        "python tools/build_run287_same_close_target_books.py; fi\n"
    )
    assert len(
        MOD.executable_invocations(
            "for x in 1 2; do python "
            "tools/build_run287_same_close_target_books.py; done\n",
            protected,
        )
    ) == 2
    brace_loop = (
        "for x in {1..2}; do\n"
        "  python tools/build_run287_same_close_target_books.py\n"
        "done\n"
    )
    assert any(
        command == MOD.SHELL_UNRESOLVED_CONTROL_SENTINEL
        for _line, command in MOD.shell_logical_commands(brace_loop)
    )
    assert protected not in MOD.python_entrypoints(
        "if true; then :; else "
        "python tools/build_run287_same_close_target_books.py; fi\n"
    )
    assert len(
        MOD.executable_invocations(
            "for x in 1 2; do\n"
            "  python tools/build_run287_same_close_target_books.py\n"
            "done\n",
            protected,
        )
    ) == 2
    assert protected not in MOD.python_entrypoints(
        "if true; then\n"
        "  :\n"
        "else\n"
        "  python tools/build_run287_same_close_target_books.py\n"
        "fi\n"
    )
    assert MOD.statically_disabled_workflow_condition(
        "${{ false && github.event_name == 'push' }}"
    )
    assert MOD.statically_disabled_workflow_condition(
        "${{ ((false)) && github.event_name == 'push' }}"
    )
    heredoc = (
        "cat <<'EOF'\n"
        "python tools/build_run287_same_close_target_books.py --required\n"
        "EOF\n"
    )
    assert protected not in MOD.python_entrypoints(heredoc)
    assert protected in MOD.python_entrypoints(
        "read value <<< 'data'\n"
        "python tools/build_run287_same_close_target_books.py\n"
    )
    assert protected in MOD.python_entrypoints(
        "printf '' | xargs python tools/build_run287_same_close_target_books.py\n"
    )
    assert any(
        command == MOD.SHELL_UNRESOLVED_CONTROL_SENTINEL
        for _line, command in MOD.shell_logical_commands(
            "printf '' | xargs -r python "
            "tools/build_run287_same_close_target_books.py\n"
        )
    )

    assert any(
        ":rename:target" in finding
        for finding in MOD.authority_write_sinks(
            'import os\nos.rename('
            '"outputs/operating_main_target_book.csv", "tmp/archive.csv")\n',
            ("target",),
        )
    )
    assert any(
        ":target" in finding
        for finding in MOD.authority_write_sinks(
            'from os import renames as move_tree\nmove_tree('
            '"outputs/operating_main_target_book.csv", "tmp/archive.csv")\n',
            ("target",),
        )
    )
    assert any(
        ":mv:outputs/operating_main_target_book.csv:target" in finding
        for finding in MOD.shell_authority_write_sinks(
            "mv outputs/operating_main_target_book.csv tmp/archive.csv\n",
            ("target",),
        )
    )
    finite_process = (
        "import subprocess\n"
        "ALLOWED_TOOLS = {'tools/helper.py', 'tools/other.py'}\n"
        "def run_stage(command):\n    subprocess.run(list(command))\n"
        "run_stage(['python', selected_tool])\n"
    )
    assert set(MOD.local_process_candidates(finite_process)) >= {
        "tools/helper.py",
        "tools/other.py",
    }
    threaded = (
        "import threading\n"
        "from tools import build_run287_same_close_target_books as writer\n"
        "threading.Thread(target=writer.main).start()\n"
    )
    assert dict(MOD.python_main_call_counts(threaded))[protected] == 1
    inert_thread = (
        "import threading\n"
        "from tools import build_run287_same_close_target_books as writer\n"
        "threading.Thread(target=writer.main)\n"
    )
    assert protected not in dict(MOD.python_main_call_counts(inert_thread))
    assigned_thread = (
        "import threading\n"
        "from tools import build_run287_same_close_target_books as writer\n"
        "worker = threading.Thread(target=writer.main)\n"
        "worker.start()\n"
    )
    assert dict(MOD.python_main_call_counts(assigned_thread))[protected] == 1
    pty_launch = (
        "from pty import spawn as launch\n"
        "launch(['python', 'tools/helper.py'])\n"
    )
    assert "tools/helper.py" in MOD.local_process_candidates(pty_launch)
    subprocess_startup = (
        "import os, subprocess\n"
        "subprocess.run(['python', 'tools/harmless.py'], "
        "env={**os.environ, 'PYTHONPATH': 'tools/hooks'})\n"
    )
    assert set(MOD.local_process_candidates(subprocess_startup)) >= {
        "tools/harmless.py",
        "tools/hooks/sitecustomize.py",
        "tools/hooks/usercustomize.py",
    }
    cwd_subprocess_startup = (
        "import os, subprocess\n"
        "subprocess.run(['python', 'harmless.py'], cwd='sandbox', "
        "env={**os.environ, 'PYTHONPATH': 'hooks'})\n"
    )
    assert set(MOD.local_process_candidates(cwd_subprocess_startup)) >= {
        "sandbox/harmless.py",
        "sandbox/hooks/sitecustomize.py",
        "sandbox/hooks/usercustomize.py",
    }
    constructor_environment = (
        "import os, subprocess\n"
        "subprocess.run(['python', 'tools/harmless.py'], "
        "env=dict(os.environ, PYTHONPATH='tools/hooks'))\n"
    )
    assert set(MOD.local_process_candidates(constructor_environment)) >= {
        "tools/hooks/sitecustomize.py",
        "tools/hooks/usercustomize.py",
    }

    dynamic_module = (
        "import importlib\n"
        "name = 'tools.build_run287_same_close_target_books'\n"
        "importlib.import_module(name).main()\n"
    )
    assert protected in MOD.local_import_candidates(dynamic_module)
    assert dict(MOD.python_main_call_counts(dynamic_module))[protected] == 1
    ambiguous_dynamic_module = (
        "import importlib\n"
        "name = ('tools.build_run287_same_close_target_books' "
        "if enabled else 'tools.harmless')\n"
        "importlib.import_module(name).main()\n"
    )
    assert MOD.PYTHON_UNRESOLVED_DYNAMIC_IMPORT_SENTINEL in (
        MOD.local_import_candidates(ambiguous_dynamic_module)
    )
    partial_dynamic_module = (
        "import importlib\n"
        "importlib.import_module(f'tools.{suffix}').main()\n"
    )
    assert MOD.PYTHON_UNRESOLVED_DYNAMIC_IMPORT_SENTINEL in (
        MOD.local_import_candidates(partial_dynamic_module)
    )

    quoted_substitution = (
        'echo "$(python tools/build_run287_same_close_target_books.py)"\n'
    )
    assert len(MOD.executable_invocations(quoted_substitution, protected)) == 1
    shadowed_python = (
        "python() { :; }\n"
        "python tools/build_run287_same_close_target_books.py\n"
    )
    assert any(
        command == MOD.SHELL_UNRESOLVED_CONTROL_SENTINEL
        for _line, command in MOD.shell_logical_commands(shadowed_python)
    )

    exit_callback = (
        "import atexit\n"
        "from tools import build_run287_same_close_target_books as writer\n"
        "atexit.register(writer.main)\n"
    )
    assert dict(MOD.python_main_call_counts(exit_callback))[protected] == 1

    aliased_local_launcher = (
        "import tools.build_run287_same_close_target_books as writer\n"
        "def launch():\n"
        "    writer.main()\n"
        "callback = launch\n"
        "callback()\n"
    )
    assert dict(MOD.python_main_call_counts(aliased_local_launcher))[protected] == 1

    assert "tools/hook.sh" in MOD.shell_script_candidates(
        'DIR=tools\nsource "$DIR/hook.sh"\n'
    )
    assert any(
        command == MOD.SHELL_UNRESOLVED_CONTROL_SENTINEL
        for _line, command in MOD.shell_logical_commands(
            "DIR=tools\nsource '$DIR/hook.sh'\n"
        )
    )
    assert any(
        command == MOD.SHELL_UNRESOLVED_CONTROL_SENTINEL
        for _line, command in MOD.shell_logical_commands(
            "CMD='python tools/build_run287_same_close_target_books.py'\n"
            "eval \"$CMD\"\n"
        )
    )

    nested_payload = "import tools.harmless"
    for _index in range(5):
        nested_payload = f"exec({nested_payload!r})"
    original_budget = MOD.PYTHON_DYNAMIC_EXEC_SOURCE_BUDGET
    try:
        MOD.PYTHON_DYNAMIC_EXEC_SOURCE_BUDGET = 3
        assert MOD.PYTHON_DYNAMIC_EXEC_BUDGET_SENTINEL in (
            MOD.transitive_literal_python_sources(nested_payload)
        )
    finally:
        MOD.PYTHON_DYNAMIC_EXEC_SOURCE_BUDGET = original_budget

    bash_env_workflow = (
        "env:\n  BASH_ENV: tools/startup.sh\n"
        "jobs:\n  audit:\n    steps:\n      - run: echo ready\n"
    )
    bash_records = MOD.workflow_run_records(bash_env_workflow)
    assert bash_records and "source tools/startup.sh" in bash_records[0][1]
    assert "tools/startup.sh" in MOD.shell_script_candidates(bash_records[0][1])

    matrix_workflow = (
        "jobs:\n  audit:\n    strategy:\n      matrix:\n        py: ['3.11', '3.12']\n"
        "    steps:\n      - run: python tools/helper.py\n"
    )
    assert any(
        MOD.SHELL_UNRESOLVED_CONTROL_SENTINEL in source
        for _shell, source, _workdir in MOD.workflow_run_records(matrix_workflow)
    )

    local_action = "runs:\n  using: composite\n  steps:\n    - run: echo ready\n"
    duplicate_uses = (
        "jobs:\n  audit:\n    steps:\n"
        "      - uses: ./tools/writer-action\n"
        "      - uses: ./tools/writer-action\n"
    )
    counts, cycle = MOD.reachable_local_yaml_execution_counts(
        ".github/workflows/audit.yml",
        duplicate_uses,
        {"tools/writer-action/action.yml": local_action},
    )
    assert cycle is False
    assert counts == {"tools/writer-action/action.yml": 2}

    external_node_sources = {
        "tools/node-action/action.yml": "runs:\n  using: node20\n  main: index.js\n",
        "tools/node-action/index.js": 'import "../../shared/helper.js";\n',
        "shared/helper.js": "module.exports = {};\n",
    }
    assert "shared/helper.js" in MOD.local_action_implementation_paths(
        "tools/node-action/action.yml",
        external_node_sources["tools/node-action/action.yml"],
        set(external_node_sources),
        external_node_sources,
    )
    assert MOD.node_action_authority_findings(
        "tools/node-action/index.js",
        "const {execFileSync} = require('node:child_process');\n"
        "execFileSync('python', "
        "['tools/build_run287_same_close_target_books.py']);\n",
        MOD.PROTECTED_AUTHORITY_SENSITIVE_TERMS,
    ) == ("process-launch",)

    ubuntu_records = MOD.workflow_run_records(
        "jobs:\n  audit:\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - run: echo ready\n"
    )
    assert ubuntu_records[0][0] == ""
    windows_records = MOD.workflow_run_records(
        "jobs:\n  audit:\n    runs-on: windows-latest\n"
        "    steps:\n      - run: echo ready\n"
    )
    assert windows_records[0][0] == "pwsh"
    dynamic_runner_records = MOD.workflow_run_records(
        "jobs:\n  audit:\n    runs-on: ${{ matrix.runner }}\n"
        "    steps:\n      - run: echo ready\n"
    )
    assert dynamic_runner_records[0][0] == MOD.IMPLICIT_UNKNOWN_RUNNER_SHELL

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "tests").mkdir()
        (root / "docs").mkdir()
        (root / "outputs").mkdir()
        (root / "tests" / "reader.py").write_text(
            "from pathlib import Path\n"
            "Path('docs/status.md').read_text()\n",
            encoding="utf-8",
        )
        (root / "docs" / "status.md").write_text(
            "outputs/summary.json\n", encoding="utf-8"
        )
        (root / "outputs" / "summary.json").write_text(
            "{}\n", encoding="utf-8"
        )
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        discovered_shells = MOD.tracked_shell_paths(root)
        assert "docs/status.md" not in discovered_shells
        assert "outputs/summary.json" not in discovered_shells

    contract, workflows, accepted = source_inputs()
    multiplied = deepcopy(workflows)
    daily = contract["accepted_daily_workflow"]
    duplicate_helper = "tools/" + "duplicate_" + "helper.py"
    multiplied[daily] = multiplied[daily].replace(
        "          set -euo pipefail",
        f"          python {duplicate_helper}\n"
        f"          python {duplicate_helper}\n"
        "          set -euo pipefail",
        1,
    )
    multiplied_sources = deepcopy(accepted)
    multiplied_sources[duplicate_helper] = (
        "from tools.build_run287_same_close_target_books import main\n"
        "main()\n"
    )
    multiplied_result = MOD.audit_texts(
        contract, multiplied, multiplied_sources
    )
    assert any(
        "entrypoint_invocation_count_mismatch:"
        "tools/build_run287_same_close_target_books.py:expected=1:observed=3"
        in failure
        for failure in multiplied_result["failures"]
    ), multiplied_result["failures"]


def test_protected_binding_schema_cannot_be_weakened() -> None:
    contract, _workflows, _accepted = source_inputs()
    weakened = deepcopy(contract)
    binding = next(
        row
        for row in weakened["entrypoint_bindings"]
        if row["entrypoint"] == "tools/build_run287_same_close_target_books.py"
    )
    binding.pop("exact_invocation_count")
    try:
        MOD.validate_contract(weakened)
    except ValueError as exc:
        assert "protected entrypoint binding changed" in str(exc)
    else:
        raise AssertionError("weakened protected binding was accepted")

    weakened = deepcopy(contract)
    weakened["authority_sensitive_name_terms"] = ["irrelevant"]
    try:
        MOD.validate_contract(weakened)
    except ValueError as exc:
        assert "protected authority-sensitive vocabulary changed" in str(exc)
    else:
        raise AssertionError("weakened authority vocabulary was accepted")

    weakened = deepcopy(contract)
    weakened["required_executable_commands"] = [
        row
        for row in weakened["required_executable_commands"]
        if row.get("entrypoint")
        != "tools/build_run287_same_close_target_books.py"
    ]
    try:
        MOD.validate_contract(weakened)
    except ValueError as exc:
        assert "protected executable command profiles changed" in str(exc)
    else:
        raise AssertionError("weakened protected command profile was accepted")

    weakened = deepcopy(contract)
    observer = ".github/workflows/daily_crisis_monitor.yml"
    weakened["workflow_roles"][observer] = "renamed_observer"
    try:
        MOD.validate_contract(weakened)
    except ValueError as exc:
        assert "protected no-writer role changed" in str(exc)
    else:
        raise AssertionError("renamed protected no-writer role was accepted")


def test_untracked_workflow_is_not_repository_authority() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        workflows = root / ".github" / "workflows"
        workflows.mkdir(parents=True)
        tracked = workflows / "tracked.yml"
        untracked = workflows / "untracked.yml"
        tracked.write_text(
            "name: tracked\njobs:\n  x:\n    steps:\n"
            "      - run: bash tools/helper.bash\n"
            "      - run: python tools/helper.txt\n",
            encoding="utf-8",
        )
        untracked.write_text("name: untracked\n", encoding="utf-8")
        (root / "tools").mkdir()
        (root / "tools" / "helper.bash").write_text(
            "python tools/harmless.py\n", encoding="utf-8"
        )
        (root / "tools" / "helper.txt").write_text(
            "from tools.build_run287_same_close_target_books import main\n"
            "main()\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(
            [
                "git", "add", ".github/workflows/tracked.yml",
                "tools/helper.bash", "tools/helper.txt",
            ],
            cwd=root,
            check=True,
        )
        paths = MOD.tracked_workflow_paths(root)
        assert paths == [".github/workflows/tracked.yml"]
        assert MOD.tracked_shell_paths(root) == ["tools/helper.bash"]
        assert "tools/helper.txt" in MOD.tracked_python_paths(root)


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

    indirect_layer4 = deepcopy(workflows)
    path = ".github/workflows/layer4_monthly_swap.yml"
    guarded = (
        '          EXECUTE_FLAG=""\n'
        '          if [ "${{ github.event.inputs.execute }}" = "true" ]; then\n'
        '            EXECUTE_FLAG="--execute --confirm"\n'
        "          fi"
    )
    indirect_layer4[path] = indirect_layer4[path].replace(
        guarded,
        "          cat <<'SAFE'\n"
        + guarded
        + "\n          SAFE\n"
        '          flag_name="EXECUTE_FLAG"\n'
        '          printf -v "$flag_name" "%s" "--execute --confirm"',
        1,
    )
    result = MOD.audit_texts(contract, indirect_layer4, accepted)
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "workflow_shell_flag_derivation_mismatch:"
        ".github/workflows/layer4_monthly_swap.yml:EXECUTE_FLAG" in item
        for item in result["failures"]
    )

    read_layer4 = deepcopy(workflows)
    read_layer4[path] = read_layer4[path].replace(
        '          THROTTLE_FLAG=""',
        '          read EXECUTE_FLAG\n          THROTTLE_FLAG=""',
        1,
    )
    result = MOD.audit_texts(contract, read_layer4, accepted)
    assert result["status"] == MOD.BLOCKED_STATUS
    assert any(
        "workflow_shell_flag_derivation_mismatch:"
        ".github/workflows/layer4_monthly_swap.yml:EXECUTE_FLAG" in item
        for item in result["failures"]
    )

    inert_layer4 = deepcopy(workflows)
    inert_layer4[path] = inert_layer4[path].replace(
        guarded,
        "          if false; then\n"
        + "\n".join(f"  {line}" for line in guarded.splitlines())
        + "\n          fi",
        1,
    )
    result = MOD.audit_texts(contract, inert_layer4, accepted)
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

        # A historical CRLF blob remains clean when its exact worktree bytes
        # match HEAD, even if a current clean filter would produce an LF blob.
        crlf_tracked = root / "historical_crlf.txt"
        crlf_tracked.write_bytes(b"historical\r\n")
        subprocess.run(
            ["git", "-c", "core.autocrlf=false", "add", "historical_crlf.txt"],
            cwd=root,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-qm", "historical crlf fixture"],
            cwd=root,
            check=True,
        )
        crlf_clean = MOD.git_source_identity(root, ["historical_crlf.txt"])
        assert crlf_clean["source_identity_status"] == "CLEAN_HEAD_BOUND"
        assert (
            crlf_clean["raw_worktree_blob_ids"]["historical_crlf.txt"]
            == crlf_clean["canonical_head_blob_ids"]["historical_crlf.txt"]
        )

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

        tracked.write_text("clean\n", encoding="utf-8")
        subprocess.run(
            ["git", "update-index", "--assume-unchanged", "tracked.txt"],
            cwd=root,
            check=True,
        )
        tracked.write_text("hidden dirty\n", encoding="utf-8")
        hidden_dirty = MOD.git_source_identity(root, ["tracked.txt"])
        assert hidden_dirty["source_identity_status"] == "DIRTY_INPUTS_NOT_HEAD_BOUND"
        assert hidden_dirty["source_commit_sha"] == ""
        assert "HEAD_BYTE_MISMATCH:tracked.txt" in hidden_dirty["dirty_input_records"]
        subprocess.run(
            ["git", "update-index", "--no-assume-unchanged", "tracked.txt"],
            cwd=root,
            check=True,
        )

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
        accepted_workflow = (
            ".github/workflows/daily_operating_selection_refresh.yml"
        )
        observer_workflow = ".github/workflows/observer.yml"
        workflow_texts = {
            accepted_workflow: (
                "jobs:\n  run:\n    steps:\n"
                "      - run: python tools/build_run287_same_close_target_books.py "
                "--producer-status ready --freshness-status ready "
                "--valuation-date 2026-08-12 --output-dir outputs\n"
                "      - run: python tools/run_daily_simulated_fill_ledger.py "
                "--suppress-new-orders --cost-bps 25\n"
                "      - run: python tools/run_daily_simulated_fill_ledger.py "
                "--target-handoff-manifest $SAME_CLOSE_DIR/status.json "
                "--expected-target-handoff-sha256 $TARGET_HANDOFF_SHA "
                "--main-target-sha256 $MAIN_TARGET_SHA "
                "--concentrated-target-sha256 $CONCENTRATED_TARGET_SHA "
                "--cost-bps 25\n"
            ),
            observer_workflow: (
                "jobs:\n  run:\n    steps:\n"
                "      - uses: ./tools/neutral-action\n"
                "      - uses: ./tools/node-action\n"
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
        action = root / "tools" / "neutral-action" / "action.yml"
        action.parent.mkdir()
        action.write_text(
            "runs:\n  using: composite\n  steps:\n"
            "    - shell: bash\n"
            "      run: python tools/neutral.py\n",
            encoding="utf-8",
        )
        node_action = root / "tools" / "node-action" / "action.yml"
        node_action.parent.mkdir()
        node_action.write_text(
            "runs:\n  using: node20\n  main: index.js\n",
            encoding="utf-8",
        )
        node_implementation = node_action.parent / "index.js"
        node_implementation.write_text(
            'import "../../shared/helper.js";\n', encoding="utf-8"
        )
        external_node_helper = root / "shared" / "helper.js"
        external_node_helper.parent.mkdir()
        external_node_helper.write_text(
            "export const value = 1;\n", encoding="utf-8"
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
                },
                {
                    "entrypoint": "tools/run_daily_simulated_fill_ledger.py",
                    "role": "durable_review_only_paper_ledger_consumer",
                    "exact_invocation_count": 2,
                    "allowed_workflows": [accepted_workflow],
                },
            ],
            "workflow_authority_sensitive_entrypoints": {accepted_workflow: [
                "tools/build_run287_same_close_target_books.py",
                "tools/run_daily_simulated_fill_ledger.py",
            ]},
            "no_writer_reachable_authority_sensitive_modules": {
                observer_workflow: []
            },
            "no_writer_authority_write_sinks": {observer_workflow: []},
            "accepted_daily_workflow": accepted_workflow,
            "accepted_path_files": [
                accepted_workflow,
                "tools/build_run287_same_close_target_books.py",
                "tools/run_daily_simulated_fill_ledger.py",
            ],
            "accepted_workflow_authority_sensitive_entrypoints": [
                "tools/build_run287_same_close_target_books.py",
                "tools/run_daily_simulated_fill_ledger.py",
            ],
            "accepted_workflow_local_entrypoints": [
                "tools/build_run287_same_close_target_books.py",
                "tools/run_daily_simulated_fill_ledger.py",
            ],
            "accepted_reachable_authority_sensitive_modules": [
                "tools/build_run287_same_close_target_books.py",
                "tools/run_daily_simulated_fill_ledger.py",
            ],
            "accepted_workflow_inline_local_imports": [],
            "authority_sensitive_name_terms": list(
                MOD.PROTECTED_AUTHORITY_SENSITIVE_TERMS
            ),
            "authority_write_destination_terms": list(
                MOD.PROTECTED_AUTHORITY_WRITE_TERMS
            ),
            "forbidden_accepted_path_tokens": ["forbidden_legacy_exit"],
            "required_workflow_input_defaults": [],
            "required_shell_boolean_flag_derivations": [],
            "required_workflow_tokens": {},
            "required_executable_commands": [
                deepcopy(row)
                for row in source_inputs()[0]["required_executable_commands"]
                if row.get("workflow") == accepted_workflow
                and row.get("entrypoint") in {
                    "tools/build_run287_same_close_target_books.py",
                    "tools/run_daily_simulated_fill_ledger.py",
                }
            ],
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
        assert "tools/neutral-action/action.yml" in clean["audit_input_paths"]
        assert clean["workflow_yaml_reachable_files"][observer_workflow] == [
            "tools/neutral-action/action.yml",
            "tools/node-action/action.yml",
        ]
        assert clean["workflow_action_implementation_files"][observer_workflow] == [
            "shared/helper.js",
            "tools/node-action/action.yml",
            "tools/node-action/index.js",
        ]
        assert "tools/node-action/index.js" in clean["audit_input_paths"]
        assert "shared/helper.js" in clean["audit_input_paths"]
        assert clean["audit_runtime_head_bound"] is False
        assert "audit_runtime_outside_selected_repository" in clean["failures"]

        ignored_contract = root / "outputs" / "contract.json"
        ignored_contract.parent.mkdir()
        ignored_contract.write_text(json.dumps(contract), encoding="utf-8")
        (root / ".git" / "info" / "exclude").write_text(
            "outputs/\n", encoding="utf-8"
        )
        untracked_contract = MOD.run_audit(
            root, contract, contract_path=ignored_contract
        )
        assert untracked_contract["contract_head_bound"] is False
        assert "contract_not_tracked_at_head" in untracked_contract["failures"]

        external_node_helper.write_text(
            "export const value = 2;\n", encoding="utf-8"
        )
        dirty_node_helper = MOD.run_audit(
            root, contract, contract_path=contract_path
        )
        assert dirty_node_helper["source_identity_status"] == (
            "DIRTY_INPUTS_NOT_HEAD_BOUND"
        )
        assert any(
            "shared/helper.js" in row
            for row in dirty_node_helper["dirty_input_records"]
        )
        external_node_helper.write_text(
            "export const value = 1;\n", encoding="utf-8"
        )

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
    test_indirect_execution_and_destination_bypasses_fail_closed()
    test_reviewed_execution_edges_are_inventory_bound()
    test_latest_review_execution_context_edges_are_bound()
    test_shell_and_loader_authority_edges_fail_closed()
    test_static_control_and_indirect_launch_edges_are_bound()
    test_protected_binding_schema_cannot_be_weakened()
    test_untracked_workflow_is_not_repository_authority()
    test_execution_defaults_are_bound_to_named_inputs()
    test_dirty_input_is_not_attributed_to_head_and_defaults_follow_repo_root()
    test_run_audit_binds_no_writer_traversal_sources_to_head()
    print("run287 dynamic portfolio call-path smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
