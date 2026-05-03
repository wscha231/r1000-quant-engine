#!/usr/bin/env python3
"""Smoke tests for AutoLearning policy proposal scaffolding."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from r1000_auto_learning_evidence import load_auto_learning_evidence  # noqa: E402
from r1000_auto_learning_policy import render_policy_yaml, validate_policy  # noqa: E402
from tools.auto_policy_proposal import build_policy_from_evidence  # noqa: E402


def test_policy_candidate_is_proposal_only() -> None:
    evidence = load_auto_learning_evidence(root=REPO_ROOT)
    policy = build_policy_from_evidence(evidence)
    validation = validate_policy(policy)
    assert validation["valid"] is True, validation
    assert policy["mode"] == "proposal_only"
    assert policy["guardrails"]["production_activation_allowed"] is False
    assert policy["guardrails"]["requires_human_approval"] is True
    assert policy["guardrails"]["requires_challenger_backtest"] is True
    assert policy["target_n"]["main"]["neutral"] == 15
    assert policy["orchestrator_policy"]["neutral"]["alpha_sprint"] == 0.0
    assert policy["orchestrator_policy"]["bull"]["alpha_sprint"] == 0.05
    assert len(policy["proposals"]) >= 5


def test_policy_yaml_renders_core_sections() -> None:
    evidence = load_auto_learning_evidence(root=REPO_ROOT)
    policy = build_policy_from_evidence(evidence)
    yaml_text = render_policy_yaml(policy)
    assert "mode: \"proposal_only\"" in yaml_text
    assert "feature_gates:" in yaml_text
    assert "sleeve_policy:" in yaml_text
    assert "orchestrator_policy:" in yaml_text
    assert "production_activation_allowed: false" in yaml_text


if __name__ == "__main__":
    test_policy_candidate_is_proposal_only()
    test_policy_yaml_renders_core_sections()
    print("auto_learning_policy_smoke: ok")
