#!/usr/bin/env python3
"""Guarded promotion check for AutoLearning policy candidates.

This tool never edits model code, broker settings, or production defaults. The
only possible write is copying a fully approved candidate policy to the
research active-policy file, and that requires explicit `--approve` and
`--write-active` flags plus a passing challenger decision.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from r1000_auto_learning_policy import load_policy, validate_policy  # noqa: E402


DEFAULT_CHALLENGER_DECISION = "outputs/auto_learning/challenger/challenger_decision.json"
DEFAULT_CANDIDATE = "research/auto_learning_policy_candidate.yaml"
DEFAULT_ACTIVE = "research/auto_learning_policy_active.yaml"
DEFAULT_OUT_DIR = "outputs/auto_learning/promotion"


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def render_report(decision: dict[str, Any]) -> str:
    lines = [
        "# AutoLearning Policy Promotion Decision",
        "",
        "This decision only concerns the research active-policy artifact. It does not change production defaults.",
        "",
        f"- Status: `{decision.get('status')}`",
        f"- Promoted: `{decision.get('promoted')}`",
        f"- Dry run: `{decision.get('dry_run')}`",
        f"- Candidate: `{decision.get('candidate_policy')}`",
        f"- Active policy target: `{decision.get('active_policy')}`",
        "",
        "## Checks",
        "",
        "| Check | Passed |",
        "| --- | --- |",
    ]
    for key, value in (decision.get("checks") or {}).items():
        lines.append(f"| {key} | `{value}` |")
    lines.extend(["", "## Reasons", ""])
    reasons = decision.get("reasons") or []
    if not reasons:
        lines.append("No blockers.")
    else:
        for reason in reasons:
            lines.append(f"- `{reason}`")
    lines.append("")
    return "\n".join(lines)


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    challenger_path = repo_path(args.challenger_decision)
    candidate_path = repo_path(args.candidate_policy)
    active_path = repo_path(args.active_policy)
    challenger = read_json(challenger_path)
    policy = load_policy(candidate_path) if candidate_path.exists() else {}
    validation = validate_policy(policy) if policy else {"valid": False, "issues": ["candidate_missing"]}

    checks = {
        "candidate_exists": candidate_path.exists(),
        "challenger_decision_exists": challenger_path.exists(),
        "challenger_approved": challenger.get("approved_for_promotion") is True,
        "policy_schema_valid": validation.get("valid") is True,
        "production_activation_disabled": (policy.get("guardrails") or {}).get("production_activation_allowed") is False,
        "human_approval_flag": bool(args.approve),
        "write_active_flag": bool(args.write_active),
    }
    reasons = [name for name, ok in checks.items() if not ok]
    approved_to_copy = all(checks.values())
    dry_run = not (args.approve and args.write_active)
    promoted = False
    if approved_to_copy and not dry_run:
        active_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidate_path, active_path)
        promoted = True

    return {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "promoted" if promoted else "blocked",
        "promoted": promoted,
        "dry_run": dry_run,
        "research_only": True,
        "production_activation_allowed": False,
        "checks": checks,
        "reasons": reasons,
        "candidate_policy": str(candidate_path),
        "active_policy": str(active_path),
        "challenger_decision": str(challenger_path),
        "policy_validation": validation,
        "challenger_status": challenger.get("status"),
        "hard_failures": challenger.get("hard_failures", []),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--challenger-decision", default=DEFAULT_CHALLENGER_DECISION)
    parser.add_argument("--candidate-policy", default=DEFAULT_CANDIDATE)
    parser.add_argument("--active-policy", default=DEFAULT_ACTIVE)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--approve", action="store_true", help="Explicit human approval flag.")
    parser.add_argument("--write-active", action="store_true", help="Allow copying candidate to research active policy if all gates pass.")
    args = parser.parse_args()

    decision = evaluate(args)
    out_dir = repo_path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "promotion_decision.json", decision)
    (out_dir / "promotion_report.md").write_text(render_report(decision), encoding="utf-8")
    print(f"[auto-policy-promote] status={decision['status']} promoted={decision['promoted']}")
    print(f"[auto-policy-promote] wrote {out_dir / 'promotion_decision.json'}")
    return 0 if decision["promoted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
