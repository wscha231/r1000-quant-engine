#!/usr/bin/env python3
"""Smoke-test the repository-wide GitHub agent operating contract."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def read_required(relative_path: str) -> str:
    path = ROOT / relative_path
    assert path.is_file(), f"missing required agent contract: {relative_path}"
    text = path.read_text(encoding="utf-8")
    assert text.strip(), f"empty required agent contract: {relative_path}"
    return text


def require_terms(name: str, text: str, terms: tuple[str, ...]) -> None:
    normalized = text.casefold()
    missing = [term for term in terms if term.casefold() not in normalized]
    assert not missing, f"{name} is missing required terms: {missing}"


def normalize_whitespace(text: str) -> str:
    return " ".join(text.casefold().split())


def require_clauses(name: str, text: str, clauses: tuple[str, ...]) -> None:
    normalized = normalize_whitespace(text)
    missing = [
        clause
        for clause in clauses
        if normalize_whitespace(clause) not in normalized
    ]
    assert not missing, f"{name} is missing required safety clauses: {missing}"


def require_immediate_board_failure_details() -> None:
    """Keep an early suite traceback visible before the entire tier finishes."""
    from contextlib import redirect_stdout
    from io import StringIO
    from types import SimpleNamespace
    from unittest import TestCase
    from unittest.mock import patch
    import importlib.util

    spec = importlib.util.spec_from_file_location("validation_failure_fixture", ROOT / "tools/run_pr_validation.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the existing validation runner")
    validation = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validation)

    class FlushedOutput(StringIO):
        def __init__(self):
            super().__init__()
            self.flush_offsets = []

        def flush(self):
            self.flush_offsets.append(len(self.getvalue()))
            super().flush()

    check = TestCase()
    early = "EARLY_SYNTHETIC_PLANNING_FAILURE"
    stderr = early + "\n" + "later suite passed\n" * 25
    failed = SimpleNamespace(returncode=7, stdout="", stderr=stderr)
    output = FlushedOutput()
    with patch.object(validation.subprocess, "run", return_value=failed), redirect_stdout(output):
        passed, _, tail = validation.run_one("tests/agent_board_smoke.py", [], quiet=True)
    check.assertFalse(passed)
    check.assertNotIn(early, tail)  # Preserve the existing short final summary.
    check.assertIn("returncode=7", output.getvalue())
    check.assertIn(stderr, output.getvalue())
    check.assertIn(len(output.getvalue()), output.flush_offsets)

    # Other failures and successful board runs retain their prior output policy.
    for path, proc, expected in (
        ("tests/run287_agent_github_operating_standard_smoke.py", failed, False),
        ("tests/agent_board_smoke.py", SimpleNamespace(returncode=0, stdout="ok\n", stderr=stderr), True),
    ):
        output = FlushedOutput()
        with patch.object(validation.subprocess, "run", return_value=proc), redirect_stdout(output):
            passed, _, _ = validation.run_one(path, [], quiet=True)
        check.assertEqual(passed, expected)
        check.assertEqual(output.getvalue(), "")

    output = FlushedOutput()
    empty = SimpleNamespace(returncode=2, stdout="", stderr="")
    with patch.object(validation.subprocess, "run", return_value=empty), redirect_stdout(output):
        passed, _, tail = validation.run_one("tests/agent_board_smoke.py", [], quiet=True)
    check.assertFalse(passed)
    check.assertEqual(tail, "<no output>")
    check.assertIn("returncode=2", output.getvalue())
    check.assertIn("<no stderr>", output.getvalue())


def require_fail_fast_keeps_failure_and_complete_success() -> None:
    from contextlib import redirect_stdout
    from io import StringIO
    from tempfile import TemporaryDirectory
    from unittest import TestCase
    from unittest.mock import patch
    import importlib.util
    import os
    import sys

    spec = importlib.util.spec_from_file_location("validation_fast_fixture", ROOT / "tools/run_pr_validation.py")
    validation = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validation)
    check = TestCase()
    tests = [("first.py", []), ("second.py", [])]
    for ci, flags, results, calls, exit_code, summary in (
        ("true", [], [False, True], 1, 1, "(0/2 passed)"),
        ("false", [], [False, True], 2, 1, "(1/2 passed)"),
        ("false", ["--fail-fast"], [False, True], 1, 1, "(0/2 passed)"),
        ("true", [], [True, True], 2, 0, "(2/2 passed)"),
    ):
        output = StringIO()
        returns = [(ok, .01, "synthetic failure" if not ok else "") for ok in results]
        with patch.dict(os.environ, {"GITHUB_ACTIONS": ci}), \
             patch.object(sys, "argv", ["validation", *flags]), \
             patch.object(validation, "DEFAULT_TESTS", tests), \
             patch.object(validation, "run_one", side_effect=returns) as run, redirect_stdout(output):
            code = validation.main()
        check.assertEqual((code, run.call_count), (exit_code, calls))
        check.assertIn(summary, output.getvalue())
        check.assertEqual("NOT_RUN: 1 tests" in output.getvalue(), calls == 1)
        check.assertEqual("all PR validation tests pass" in output.getvalue(), exit_code == 0)
    # Real child exit3: the later test must not run or acquire a pass count.
    with TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "first.py").write_text("raise SystemExit(3)\n", encoding="utf-8")
        (root / "second.py").write_text("from pathlib import Path\nPath(__file__).with_suffix('.ran').write_text('unexpected')\n", encoding="utf-8")
        output = StringIO()
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}), \
             patch.object(sys, "argv", ["validation"]), patch.object(validation, "ROOT", root), \
             patch.object(validation, "DEFAULT_TESTS", tests), redirect_stdout(output):
            code = validation.main()
        check.assertEqual(code, 1)
        check.assertFalse((root / "second.ran").exists())
        check.assertIn("(0/2 passed)", output.getvalue())
        check.assertIn("NOT_RUN: 1 tests", output.getvalue())


def require_isolated_shards_cover_inventory_and_fail_closed() -> None:
    """No dropped/duplicated programs, vacuous shards or filtered CI success."""
    from collections import Counter
    from contextlib import redirect_stderr, redirect_stdout
    from io import StringIO
    from unittest import TestCase
    from unittest.mock import patch
    import importlib.util
    import sys
    import yaml

    spec = importlib.util.spec_from_file_location("validation_shard_fixture", ROOT / "tools/run_pr_validation.py")
    validation = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validation)
    check = TestCase()
    inventory = validation.DEFAULT_TESTS
    for count in (1, 2, 4, len(inventory)):
        shards = [validation.partition_tests(inventory, i, count) for i in range(count)]
        flattened = [entry for shard in shards for entry in shard]
        check.assertEqual(Counter(p for p, _ in flattened), Counter(p for p, _ in inventory))
        check.assertEqual(dict(flattened), dict(inventory))  # Retain per-program args.
        check.assertTrue(all(shards))
        for shard in shards:
            check.assertEqual([inventory.index(entry) for entry in shard],
                              sorted(inventory.index(entry) for entry in shard))

    for index, count in ((0, 0), (0, -1), (-1, 4), (4, 4), (0, len(inventory) + 1)):
        with check.assertRaises(ValueError):
            validation.partition_tests(inventory, index, count)
    for invalid in ([], [("same.py", []), ("same.py", ["--other"])]):
        with check.assertRaises(ValueError):
            validation.partition_tests(invalid, 0, 1)

    toy = [(f"case_{i}.py", [str(i)]) for i in range(9)]
    for index in range(4):
        with patch.object(validation, "DEFAULT_TESTS", toy), \
             patch.object(sys, "argv", ["validation", "--shard-index", str(index), "--shard-count", "4"]), \
             patch.object(validation, "run_one", return_value=(True, .01, "")) as run, \
             redirect_stdout(StringIO()) as output:
            check.assertEqual(validation.main(), 0)
        check.assertEqual([(c.args[0], c.args[1]) for c in run.call_args_list], toy[index::4])
        check.assertIn("inventory_sha256=", output.getvalue())
        with patch.object(validation, "DEFAULT_TESTS", toy), \
             patch.object(sys, "argv", ["validation", "--shard-index", str(index), "--shard-count", "4", "--fail-fast"]), \
             patch.object(validation, "run_one", return_value=(False, .01, "failed")) as run, \
             redirect_stdout(StringIO()) as output:
            check.assertEqual(validation.main(), 1)
        check.assertEqual(run.call_count, 1)
        check.assertNotIn("all PR validation tests pass", output.getvalue())
    for flags in (
        ["--shard-index", "0"], ["--shard-count", "4"],
        ["--shard-index", "4", "--shard-count", "4"],
        ["--shard-index", "0", "--shard-count", "0"],
        ["--shard-index", "0", "--shard-count", "4", "--only", "not_a_test"],
        ["--shard-index", "0", "--shard-count", "4", "--include", "extra.py"],
    ):
        with patch.object(sys, "argv", ["validation", *flags]), \
             patch.object(validation, "run_one") as run, \
             redirect_stdout(StringIO()), redirect_stderr(StringIO()), \
             check.assertRaises(SystemExit) as error:
            validation.main()
        check.assertEqual(error.exception.code, 2)
        run.assert_not_called()

    workflow = yaml.safe_load(read_required(".github/workflows/pr_validation.yml"))
    jobs = workflow["jobs"]
    shard = jobs["validation_shards"]
    gate = jobs["validate"]
    check.assertEqual(shard["strategy"], {"fail-fast": False, "matrix": {"shard": [0, 1, 2, 3]}})
    check.assertEqual(shard["timeout-minutes"], 90)
    check.assertNotIn("if", shard)
    check.assertNotIn("continue-on-error", shard)
    check.assertEqual(workflow["permissions"], {"contents": "read"})
    steps = shard["steps"]
    check.assertTrue(any(s.get("uses") == "actions/checkout@v4" for s in steps))
    run = next(s for s in steps if s["name"] == "Run Tier-1 PR validation")
    check.assertEqual(run["run"], "python tools/run_pr_validation.py --shard-index ${{ matrix.shard }} --shard-count 4")
    check.assertNotIn("if", run)
    check.assertNotIn("continue-on-error", run)
    check.assertEqual(gate["if"], "${{ always() }}")
    check.assertEqual(gate["needs"], ["validation_shards"])
    check.assertNotIn("continue-on-error", gate)
    step = gate["steps"][0]
    check.assertEqual(step["env"], {"SHARD_RESULT": "${{ needs.validation_shards.result }}"})
    check.assertEqual(step["run"], 'test "$SHARD_RESULT" = success')
    check.assertNotIn("if", step)
    check.assertNotIn("continue-on-error", step)


def main() -> int:
    require_immediate_board_failure_details()
    require_fail_fast_keeps_failure_and_complete_success()
    require_isolated_shards_cover_inventory_and_fail_closed()
    agents = read_required("AGENTS.md")
    standard = read_required("docs/RUN287_GITHUB_AGENT_OPERATING_STANDARD.md")
    template = read_required(".github/PULL_REQUEST_TEMPLATE.md")
    runner = read_required("tools/run_pr_validation.py")

    require_terms(
        "AGENTS.md",
        agents,
        (
            "GitHub plugin",
            "expected head SHA",
            "transactional daily workflow",
            "RESEARCH_ONLY",
            "fullrun",
            "Google Drive",
            "AGENT_SHARED_LESSONS_LEDGER.md",
            "Do not create a new worktree",
        ),
    )
    require_clauses(
        "AGENTS.md",
        agents,
        (
            "Do not create a new worktree unless the user explicitly approves it.",
            "Never blindly rerun a failed transactional daily workflow.",
            "Do not enable auto-merge for safety, durable-state, promotion, or "
            "trading-policy changes.",
            "Keep the system `RESEARCH_ONLY`: automatic paper research and "
            "manual live decisions only.",
            "Do not run a fullrun without explicit user approval after all "
            "preflight gates pass for one named candidate.",
            "Do not enable production or live trading.",
            "Do not auto-promote or auto-replace the champion. Automated "
            "learning may produce challenger proposals only.",
            "Do not backfill forward-only snapshots into historical PIT evidence.",
        ),
    )
    require_terms(
        "operating standard",
        standard,
        (
            "Canonical Source Map",
            "GitHub Capability Map",
            "expected head SHA",
            "blind failed-job rerun",
            "accepted publication manifest",
            "Experiment ledger",
            "Slack or Teams",
            "Improvement Roadmap",
        ),
    )
    require_clauses(
        "operating standard",
        standard,
        (
            "Do not use a blind failed-job rerun for a workflow that can "
            "produce targets, orders, fills, account/ledger mutations, "
            "accepted manifests, cache heads, or durable publications.",
            "No agent may silently install an optional collaboration plugin "
            "or begin sending external messages.",
            "Auto-merge is prohibited for changes affecting durable state, "
            "accepted publication, safety gates, promotion, portfolio policy, "
            "or trading behavior.",
        ),
    )
    require_terms(
        "pull request template",
        template,
        (
            "AGENTS.md",
            "RUN287_GITHUB_AGENT_OPERATING_STANDARD.md",
            "exact head SHA",
            "transactional workflow",
            "auto-merge",
        ),
    )
    require_clauses(
        "pull request template",
        template,
        (
            "I did not blindly rerun a transactional workflow or enable "
            "auto-merge for a safety, durable-state, promotion, or "
            "trading-policy change.",
        ),
    )
    require_terms(
        "Tier-1 validation runner",
        runner,
        ("tests/run287_agent_github_operating_standard_smoke.py",),
    )

    print("run287 agent GitHub operating standard smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
