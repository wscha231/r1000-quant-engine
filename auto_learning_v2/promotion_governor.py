"""Promotion governor for AutoLearning v2."""
from __future__ import annotations

from typing import Any


def evaluate_promotion(candidate: dict[str, Any], challenger_review: dict[str, Any], human_approved: bool = False) -> dict[str, Any]:
    validation = candidate.get("validation") or {}
    hard_failures: list[str] = []
    if candidate.get("mode") != "proposal_only":
        hard_failures.append("candidate_not_proposal_only")
    if validation.get("valid") is not True:
        hard_failures.extend([f"validation:{issue}" for issue in validation.get("issues") or []])
    if challenger_review.get("approved_for_production") is not True:
        hard_failures.append("challenger_not_approved_for_production")
    if not human_approved:
        hard_failures.append("human_approval_missing")

    promoted = not hard_failures and human_approved
    return {
        "status": "approved" if promoted else "blocked",
        "promoted": promoted,
        "write_active_policy": False,
        "production_activation_allowed": False,
        "human_approved": human_approved,
        "hard_failures": hard_failures,
        "next_allowed_stage": "shadow" if challenger_review.get("approved_for_shadow") else "research_only",
    }


def render_promotion_report(decision: dict[str, Any]) -> str:
    lines = [
        "# AutoLearning v2 Promotion Decision",
        "",
        f"- Status: `{decision.get('status')}`",
        f"- Promoted: `{str(decision.get('promoted')).lower()}`",
        f"- Write active policy: `{str(decision.get('write_active_policy')).lower()}`",
        f"- Production activation allowed: `{str(decision.get('production_activation_allowed')).lower()}`",
        f"- Next allowed stage: `{decision.get('next_allowed_stage')}`",
        "",
        "Hard failures:",
        "",
    ]
    failures = decision.get("hard_failures") or []
    if failures:
        lines.extend(f"- `{failure}`" for failure in failures)
    else:
        lines.append("- None")
    lines.append("")
    return "\n".join(lines)
