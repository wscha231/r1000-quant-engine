#!/usr/bin/env python3
"""Run the research-only AutoLearning v2 Alpha Scientist pipeline."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from auto_learning_v2.anomaly_detector import detect_anomalies, render_anomaly_report  # noqa: E402
from auto_learning_v2.challenger_backtester import (  # noqa: E402
    render_challenger_report,
    run_challenger_review,
    write_challenger_csv,
)
from auto_learning_v2.counterfactual_tester import (  # noqa: E402
    build_counterfactual_results,
    render_counterfactual_report,
    write_counterfactual_csv,
)
from auto_learning_v2.hypothesis_generator import generate_hypotheses, render_hypothesis_report  # noqa: E402
from auto_learning_v2.novelty_regime_detector import detect_novelty_regime, render_novelty_report  # noqa: E402
from auto_learning_v2.policy_candidate_builder import build_policy_candidate, render_candidate_yaml  # noqa: E402
from auto_learning_v2.promotion_governor import evaluate_promotion, render_promotion_report  # noqa: E402
from r1000_auto_learning_evidence import load_auto_learning_evidence  # noqa: E402


DEFAULT_LATEST_RUN = "cloud_results/full_rebuild/latest_global_alpha_universe"
DEFAULT_OUTPUT_DIR = "outputs/auto_learning_v2"
DEFAULT_RESEARCH_DIR = "research/auto_learning_v2"


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def render_alpha_scientist_report(
    novelty_report: dict[str, Any],
    anomalies: list[dict[str, Any]],
    hypotheses: list[dict[str, Any]],
    challenger_review: dict[str, Any],
    promotion_decision: dict[str, Any],
) -> str:
    lines = [
        "# AutoLearning v2 Alpha Scientist Report",
        "",
        "This run is research-only. It creates hypotheses and policy candidates, but production remains unchanged.",
        "",
        "## Summary",
        "",
        f"- Novelty status: `{novelty_report.get('status')}`",
        f"- Known-regime confidence: {float(novelty_report.get('known_regime_confidence') or 0.0):.2f}",
        f"- Anomalies detected: {len(anomalies)}",
        f"- Hypotheses generated: {len(hypotheses)}",
        f"- Challenger status: `{challenger_review.get('status')}`",
        f"- Promotion status: `{promotion_decision.get('status')}`",
        f"- Next allowed stage: `{promotion_decision.get('next_allowed_stage')}`",
        "",
        "## Top Anomalies",
        "",
    ]
    for anomaly in anomalies[:5]:
        lines.append(f"- `{anomaly.get('id')}`: {anomaly.get('observation')}")
    lines.extend(["", "## Hypotheses", ""])
    for hypothesis in hypotheses:
        lines.append(f"- `{hypothesis.get('id')}`: {hypothesis.get('hypothesis')}")
    lines.extend(["", "## Production Safety", ""])
    lines.append("Production activation is blocked by design until full challenger replay, promotion gates, and human approval pass.")
    lines.append("")
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    output_dir = repo_path(args.output_dir)
    research_dir = repo_path(args.research_dir)

    evidence = load_auto_learning_evidence(latest_run=latest_run, root=REPO_ROOT)
    anomalies = detect_anomalies(evidence, root=REPO_ROOT, latest_run=latest_run)
    novelty_report = detect_novelty_regime(anomalies)
    hypotheses = generate_hypotheses(anomalies, novelty_report)
    counterfactuals = build_counterfactual_results(hypotheses, root=REPO_ROOT)
    candidate = build_policy_candidate(anomalies, hypotheses, novelty_report, counterfactuals)
    challenger_review = run_challenger_review(candidate, counterfactuals)
    promotion_decision = evaluate_promotion(candidate, challenger_review, human_approved=args.human_approved)

    write_json(output_dir / "evidence_snapshot.json", evidence)
    write_json(output_dir / "anomalies_latest.json", anomalies)
    write_text(output_dir / "anomalies_latest.md", render_anomaly_report(anomalies))
    write_json(output_dir / "novelty_regime_latest.json", novelty_report)
    write_text(output_dir / "novelty_regime_latest.md", render_novelty_report(novelty_report))
    write_json(output_dir / "hypotheses_latest.json", hypotheses)
    write_text(research_dir / "hypotheses.md", render_hypothesis_report(hypotheses))
    write_counterfactual_csv(output_dir / "counterfactual_results.csv", counterfactuals)
    write_text(output_dir / "counterfactual_report.md", render_counterfactual_report(counterfactuals))
    write_json(output_dir / "policy_candidate.json", candidate)
    write_text(research_dir / "policy_candidates.yaml", render_candidate_yaml(candidate))
    write_challenger_csv(output_dir / "challenger_results.csv", counterfactuals)
    write_json(output_dir / "challenger_review.json", challenger_review)
    write_text(output_dir / "challenger_review.md", render_challenger_report(challenger_review))
    write_json(output_dir / "promotion_decision.json", promotion_decision)
    write_text(output_dir / "promotion_decision.md", render_promotion_report(promotion_decision))
    report = render_alpha_scientist_report(novelty_report, anomalies, hypotheses, challenger_review, promotion_decision)
    write_text(output_dir / "alpha_scientist_report.md", report)
    write_text(research_dir / "alpha_scientist_report.md", report)

    return {
        "anomaly_count": len(anomalies),
        "hypothesis_count": len(hypotheses),
        "novelty_status": novelty_report.get("status"),
        "challenger_status": challenger_review.get("status"),
        "promotion_status": promotion_decision.get("status"),
        "policy_valid": (candidate.get("validation") or {}).get("valid"),
        "output_dir": str(output_dir),
        "research_dir": str(research_dir),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--research-dir", default=DEFAULT_RESEARCH_DIR)
    parser.add_argument("--human-approved", action="store_true", help="Records approval flag only; production activation remains disabled.")
    return parser.parse_args()


def main() -> int:
    summary = run(parse_args())
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
