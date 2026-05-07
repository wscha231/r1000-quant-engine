"""Novel regime detection for AutoLearning v2."""
from __future__ import annotations

from collections import Counter
from typing import Any

from r1000_auto_learning_evidence import safe_float


def detect_novelty_regime(anomalies: list[dict[str, Any]]) -> dict[str, Any]:
    category_counts = Counter(str(item.get("category") or "unknown") for item in anomalies)
    regime_counts = Counter(str(item.get("regime") or "system") for item in anomalies)
    severity_score = sum(safe_float(item.get("severity_score"), 0.0) for item in anomalies)
    confidence_score = sum(safe_float(item.get("confidence"), 0.0) for item in anomalies)
    novelty_score = round(severity_score + confidence_score, 4)

    flags: list[str] = []
    if any(item.get("id") == "bear_rs_theme_inversion" for item in anomalies):
        flags.append("bear_factor_inversion")
    if any(item.get("id") == "concentrated_alpha_underallocated" for item in anomalies):
        flags.append("leadership_concentration")
    if any(item.get("id") == "explosion_stack_dormant" for item in anomalies):
        flags.append("sprint_signal_gap")
    if any(item.get("id") == "risk_sensing_defense_return_tradeoff" for item in anomalies):
        flags.append("defense_return_tradeoff")

    # This is a research triage score, not a classifier probability. Keep a
    # floor so the report does not overstate certainty from sparse artifacts.
    known_regime_confidence = max(0.05, min(1.0, 1.0 - novelty_score / 32.0))
    if novelty_score >= 14:
        status = "novel_regime_watch"
    elif novelty_score >= 8:
        status = "regime_assumption_review"
    else:
        status = "normal_research_review"

    return {
        "status": status,
        "novelty_score": novelty_score,
        "known_regime_confidence": round(known_regime_confidence, 4),
        "flags": flags,
        "category_counts": dict(category_counts),
        "regime_counts": dict(regime_counts),
        "recommended_mode": "shadow_only",
        "production_activation_allowed": False,
    }


def render_novelty_report(report: dict[str, Any]) -> str:
    lines = [
        "# Novel Regime Report",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Novelty score: {safe_float(report.get('novelty_score'), 0.0):.2f}",
        f"- Known-regime confidence: {safe_float(report.get('known_regime_confidence'), 0.0):.2f}",
        f"- Recommended mode: `{report.get('recommended_mode')}`",
        f"- Production activation allowed: `{str(report.get('production_activation_allowed')).lower()}`",
        "",
        "Flags:",
        "",
    ]
    flags = report.get("flags") or []
    if flags:
        lines.extend(f"- `{flag}`" for flag in flags)
    else:
        lines.append("- None")
    lines.extend(["", "Category counts:", ""])
    for key, value in sorted((report.get("category_counts") or {}).items()):
        lines.append(f"- `{key}`: {value}")
    lines.append("")
    return "\n".join(lines)
