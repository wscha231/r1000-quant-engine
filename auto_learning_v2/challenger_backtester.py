"""Challenger review for AutoLearning v2 policy candidates."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


def run_challenger_review(candidate: dict[str, Any], counterfactuals: list[dict[str, Any]]) -> dict[str, Any]:
    missing = [row for row in counterfactuals if row.get("status") in {"needs_full_challenger_backtest", "missing_experiment"}]
    production_ready = [row for row in counterfactuals if row.get("production_ready")]
    discovery_ready = [row for row in counterfactuals if row.get("passed_discovery")]
    validation = candidate.get("validation") or {}
    blocked = bool(missing) or not validation.get("valid")
    return {
        "status": "blocked" if blocked else "review_ready",
        "approved_for_production": False,
        "approved_for_shadow": validation.get("valid") is True and bool(candidate.get("policy_candidates")),
        "production_ready_count": len(production_ready),
        "discovery_ready_count": len(discovery_ready),
        "missing_counterfactual_count": len(missing),
        "validation": validation,
        "hard_blockers": _hard_blockers(validation, missing),
    }


def _hard_blockers(validation: dict[str, Any], missing: list[dict[str, Any]]) -> list[str]:
    blockers: list[str] = []
    for issue in validation.get("issues") or []:
        blockers.append(f"validation:{issue}")
    for row in missing:
        blockers.append(f"counterfactual:{row.get('hypothesis_id')}:{row.get('status')}")
    blockers.append("human_approval_required")
    return blockers


def write_challenger_csv(path: Path, counterfactuals: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "hypothesis_id",
        "experiment_id",
        "status",
        "passed_discovery",
        "production_ready",
        "cagr_delta_pp",
        "maxdd_delta_pp",
        "sharpe_delta",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in counterfactuals:
            writer.writerow({key: row.get(key) for key in fieldnames})


def render_challenger_report(review: dict[str, Any]) -> str:
    lines = [
        "# AutoLearning v2 Challenger Review",
        "",
        f"- Status: `{review.get('status')}`",
        f"- Approved for shadow: `{str(review.get('approved_for_shadow')).lower()}`",
        f"- Approved for production: `{str(review.get('approved_for_production')).lower()}`",
        f"- Discovery-ready hypotheses: {review.get('discovery_ready_count')}",
        f"- Production-ready hypotheses: {review.get('production_ready_count')}",
        f"- Missing counterfactuals: {review.get('missing_counterfactual_count')}",
        "",
        "Hard blockers:",
        "",
    ]
    for blocker in review.get("hard_blockers") or []:
        lines.append(f"- `{blocker}`")
    lines.append("")
    return "\n".join(lines)
