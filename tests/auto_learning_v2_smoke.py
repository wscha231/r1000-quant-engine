#!/usr/bin/env python3
"""Smoke tests for AutoLearning v2 Alpha Scientist scaffolding."""
from __future__ import annotations

import json
import sys
from tempfile import TemporaryDirectory
from argparse import Namespace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from auto_learning_v2.anomaly_detector import detect_anomalies  # noqa: E402
from auto_learning_v2.counterfactual_tester import build_counterfactual_results  # noqa: E402
from auto_learning_v2.hypothesis_generator import generate_hypotheses  # noqa: E402
from auto_learning_v2.novelty_regime_detector import detect_novelty_regime  # noqa: E402
from auto_learning_v2.policy_candidate_builder import build_policy_candidate  # noqa: E402
from auto_learning_v2.policy_grammar import validate_policy_candidate  # noqa: E402
from r1000_auto_learning_evidence import load_auto_learning_evidence  # noqa: E402
from tools.run_auto_learning_v2 import run  # noqa: E402


def test_alpha_scientist_builds_proposal_only_candidate() -> None:
    evidence = load_auto_learning_evidence(root=REPO_ROOT)
    anomalies = detect_anomalies(evidence, root=REPO_ROOT)
    novelty = detect_novelty_regime(anomalies)
    hypotheses = generate_hypotheses(anomalies, novelty)
    counterfactuals = build_counterfactual_results(hypotheses, REPO_ROOT)
    candidate = build_policy_candidate(anomalies, hypotheses, novelty, counterfactuals)
    validation = validate_policy_candidate(candidate)
    anomaly_ids = {str(item["id"]) for item in anomalies}
    hypothesis_ids = {str(item["id"]) for item in hypotheses}
    assert validation["valid"] is True, validation
    assert candidate["mode"] == "proposal_only"
    assert candidate["guardrails"]["production_activation_allowed"] is False
    assert len(anomalies) >= 1
    assert len(hypotheses) >= 1
    assert all(h["status"] == "proposal_only" for h in hypotheses)
    assert any((h.get("rules") or []) for h in hypotheses)
    if "bear_rs_theme_inversion" in anomaly_ids:
        assert "bear_rs_reversal_v1" in hypothesis_ids
    if "concentrated_alpha_underallocated" in anomaly_ids:
        assert "concentrated_neutral_25_v1" in hypothesis_ids
    if "main_broad_high_turnover" in anomaly_ids:
        assert "main_future_alpha_concentration_v1" in hypothesis_ids


def test_auto_learning_v2_runner_writes_expected_outputs() -> None:
    with TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        out_dir = tmp_path / "outputs"
        research_dir = tmp_path / "research"
        summary = run(
            Namespace(
                latest_run=str(REPO_ROOT / "cloud_results" / "full_rebuild" / "latest_global_alpha_universe"),
                output_dir=str(out_dir),
                research_dir=str(research_dir),
                human_approved=False,
            )
        )
        assert summary["policy_valid"] is True, summary
        assert summary["promotion_status"] == "blocked"
        assert (out_dir / "alpha_scientist_report.md").exists()
        assert (research_dir / "policy_candidates.yaml").exists()


def test_weekly_leader_counterfactual_feeds_autolearning() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "outputs" / "weekly_leader_broker_replay" / "concentrated").mkdir(parents=True)
        (root / "outputs" / "broker_replay" / "concentrated").mkdir(parents=True)
        (root / "outputs" / "weekly_leader_broker_replay" / "concentrated" / "metrics.json").write_text(
            json.dumps({"status": "completed", "cagr": 0.45, "sharpe": 1.4, "max_dd": -0.20}),
            encoding="utf-8",
        )
        (root / "outputs" / "broker_replay" / "concentrated" / "metrics.json").write_text(
            json.dumps({"status": "completed", "cagr": 0.35, "sharpe": 1.1, "max_dd": -0.22}),
            encoding="utf-8",
        )
        rows = build_counterfactual_results(
            [{"id": "alpha_sprint_breakout_fallback_v1", "hypothesis": "weekly leaders improve alpha"}],
            root,
        )
        assert rows[0]["experiment_id"] == "weekly_leader_entry_broker_replay"
        assert rows[0]["status"] == "counterfactual_available"
        assert rows[0]["passed_discovery"] is True
        gate = rows[0].get("discovery_gate") or {}
        assert gate.get("sharpe_delta_min") == -0.10
        assert gate.get("maxdd_delta_pp_min") == -5.0


def test_weekly_leader_counterfactual_blocks_sharpe_regression() -> None:
    """A candidate that boosts CAGR but tanks Sharpe must not pass discovery.

    Before C4 the gate was `cagr_delta > 0 AND maxdd_delta >= -5.0`. A
    candidate that levered CAGR through high-vol concentration could pass
    despite a Sharpe collapse. The Sharpe gate keeps AutoLearning from
    promoting CAGR-only wins that destroy risk-adjusted return.
    """
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "outputs" / "weekly_leader_broker_replay" / "concentrated").mkdir(parents=True)
        (root / "outputs" / "broker_replay" / "concentrated").mkdir(parents=True)
        # CAGR jumps +10pp and MaxDD is flat, but Sharpe collapses 1.10 -> 0.50.
        (root / "outputs" / "weekly_leader_broker_replay" / "concentrated" / "metrics.json").write_text(
            json.dumps({"status": "completed", "cagr": 0.45, "sharpe": 0.50, "max_dd": -0.22}),
            encoding="utf-8",
        )
        (root / "outputs" / "broker_replay" / "concentrated" / "metrics.json").write_text(
            json.dumps({"status": "completed", "cagr": 0.35, "sharpe": 1.10, "max_dd": -0.22}),
            encoding="utf-8",
        )
        rows = build_counterfactual_results(
            [{"id": "alpha_sprint_breakout_fallback_v1"}],
            root,
        )
        assert rows[0]["passed_discovery"] is False, (
            "Sharpe gate must block CAGR-only candidates that regress risk-adjusted return"
        )
        assert rows[0]["sharpe_delta"] < -0.10
        assert rows[0]["cagr_delta_pp"] > 0.0


if __name__ == "__main__":
    test_alpha_scientist_builds_proposal_only_candidate()
    test_auto_learning_v2_runner_writes_expected_outputs()
    test_weekly_leader_counterfactual_feeds_autolearning()
    test_weekly_leader_counterfactual_blocks_sharpe_regression()
    print("auto_learning_v2_smoke: ok")
