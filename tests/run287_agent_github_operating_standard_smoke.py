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


def main() -> int:
    require_immediate_board_failure_details()
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
