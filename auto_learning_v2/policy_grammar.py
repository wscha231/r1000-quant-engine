"""Policy grammar and guardrails for AutoLearning v2 candidates."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


ALLOWED_RULE_TYPES = {
    "feature_gate",
    "sleeve_allocation",
    "target_n",
    "entry_timing",
    "exit_timing",
    "cash_policy",
    "orchestrator_allocation",
    "theme_policy",
    "risk_governor",
    "counterfactual_required",
}

EXPLORATION_STAGES = ["shadow", "paper", "micro", "small", "production"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def isoformat_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def default_guardrails(ttl_days: int = 90) -> dict[str, Any]:
    return {
        "mode": "proposal_only",
        "production_activation_allowed": False,
        "requires_human_approval": True,
        "requires_challenger_backtest": True,
        "requires_counterfactual_report": True,
        "max_initial_exploration_stage": "shadow",
        "max_shadow_capital_weight": 0.0,
        "max_micro_capital_weight": 0.02,
        "max_small_capital_weight": 0.05,
        "ttl_days": ttl_days,
        "kill_switch": {
            "candidate_drawdown": -0.05,
            "rolling_3m_underperformance": -0.03,
            "loss_rate_spike": True,
        },
    }

def validate_rule(rule: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    rule_type = str(rule.get("rule_type") or "")
    if rule_type not in ALLOWED_RULE_TYPES:
        issues.append(f"invalid_rule_type:{rule_type}")
    if not rule.get("if") and rule_type != "counterfactual_required":
        issues.append("missing_if_clause")
    if not rule.get("then") and rule_type != "counterfactual_required":
        issues.append("missing_then_clause")
    limits = rule.get("limits") or {}
    if limits.get("proposal_only") is not True:
        issues.append("rule_must_be_proposal_only")
    if limits.get("production_activation_allowed") is not False:
        issues.append("rule_production_activation_must_be_false")
    return issues


def validate_policy_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    issues: list[str] = []
    if candidate.get("mode") != "proposal_only":
        issues.append("mode_must_be_proposal_only")
    guardrails = candidate.get("guardrails") or {}
    if guardrails.get("production_activation_allowed") is not False:
        issues.append("production_activation_must_be_false")
    if guardrails.get("requires_human_approval") is not True:
        issues.append("human_approval_required")
    if guardrails.get("requires_challenger_backtest") is not True:
        issues.append("challenger_backtest_required")
    for policy in candidate.get("policy_candidates") or []:
        for rule in policy.get("rules") or []:
            for issue in validate_rule(rule):
                issues.append(f"{policy.get('id')}:{issue}")
    return {"valid": not issues, "issues": issues}


def make_base_candidate(policy_version: str = "2026-05-alpha-scientist-v1", ttl_days: int = 90) -> dict[str, Any]:
    generated = utc_now()
    return {
        "policy_version": policy_version,
        "generated_at": isoformat_z(generated),
        "expires_at": (generated + timedelta(days=ttl_days)).strftime("%Y-%m-%d"),
        "mode": "proposal_only",
        "generated_by": "auto_learning_v2.alpha_scientist",
        "guardrails": default_guardrails(ttl_days=ttl_days),
        "novelty_regime": {},
        "anomalies": [],
        "hypotheses": [],
        "policy_candidates": [],
        "counterfactuals": [],
        "promotion_gates": {
            "discovery_gate": {
                "min_cagr_delta_pp_or": 2.0,
                "min_maxdd_improvement_pp_or": 2.0,
                "min_sharpe_delta_or": 0.08,
                "max_turnover_worsening_pp": 10.0,
            },
            "production_gate": {
                "min_cagr_improvement_pp": 3.0,
                "max_dd_floor": -0.25,
                "min_sharpe": 1.20,
                "max_monthly_turnover": 0.35,
                "stress_window_must_pass": True,
                "cap_violations_allowed": 0,
            },
        },
    }
