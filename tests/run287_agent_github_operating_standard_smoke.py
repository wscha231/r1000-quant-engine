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


def main() -> int:
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
    require_terms(
        "Tier-1 validation runner",
        runner,
        ("tests/run287_agent_github_operating_standard_smoke.py",),
    )

    print("run287 agent GitHub operating standard smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
