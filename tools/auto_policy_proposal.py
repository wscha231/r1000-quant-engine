#!/usr/bin/env python3
"""Generate a research-only AutoLearning policy candidate.

This is the Stage D proposal builder for AutoLearning v2. It consumes existing
evidence artifacts and emits a proposal-only YAML policy plus a review diff.
It does not run challenger backtests and does not modify active production
configuration.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from r1000_auto_learning_evidence import load_auto_learning_evidence, safe_float  # noqa: E402
from r1000_auto_learning_policy import (  # noqa: E402
    DEFAULT_GUARDRAILS,
    diff_text,
    empty_policy,
    render_policy_yaml,
    validate_policy,
)


DEFAULT_LATEST_RUN = "cloud_results/full_rebuild/latest_global_alpha_universe"
DEFAULT_CANDIDATE_OUT = "research/auto_learning_policy_candidate.yaml"
DEFAULT_ACTIVE_POLICY = "research/auto_learning_policy_active.yaml"
DEFAULT_DIFF_OUT = "outputs/auto_learning/policy_proposal_diff.md"
DEFAULT_EVIDENCE_OUT = "outputs/auto_learning/evidence_snapshot.json"
DEFAULT_SUMMARY_OUT = "outputs/auto_learning/policy_candidate_summary.md"


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def build_policy_from_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    metrics = evidence.get("metrics") or {}
    main_metrics = metrics.get("main") or {}
    conc_metrics = metrics.get("concentrated") or {}
    trades = evidence.get("trade_journal") or {}
    sleeve_audit = evidence.get("sleeve_audit") or {}
    feature_gate_candidate = evidence.get("feature_gate_candidate") or {}
    main_v2 = evidence.get("main_v2") or {}
    concentrated_policy = evidence.get("concentrated_policy") or {}
    alpha_sprint = evidence.get("alpha_sprint") or {}

    evidence_summary = {
        "main_cagr": main_metrics.get("cagr"),
        "main_sharpe": main_metrics.get("sharpe"),
        "main_max_dd": main_metrics.get("max_dd"),
        "main_avg_turnover_monthly": main_metrics.get("avg_turnover_monthly"),
        "main_avg_stock_names": main_metrics.get("avg_stock_names"),
        "concentrated_cagr": conc_metrics.get("cagr"),
        "concentrated_sharpe": conc_metrics.get("sharpe"),
        "concentrated_max_dd": conc_metrics.get("max_dd"),
        "trade_count": trades.get("trade_count"),
        "feature_gate_candidate_count": feature_gate_candidate.get("gate_count", 0),
        "main_v2_positions": main_v2.get("n_positions"),
        "main_v2_cash_target": main_v2.get("cash_target"),
        "concentrated_policy_cap_violations": len(concentrated_policy.get("cap_violations") or []),
        "alpha_sprint_candidates": alpha_sprint.get("candidate_count"),
        "alpha_sprint_active": alpha_sprint.get("active"),
    }

    policy = empty_policy(evidence_summary=evidence_summary)
    policy["guardrails"] = {
        **dict(DEFAULT_GUARDRAILS),
        "capital_allocation_auto_apply": False,
        "broker_execution_auto_apply": False,
        "candidate_policy_only": True,
    }
    policy["feature_gates"] = feature_gate_candidate.get("gates") or []

    policy["sleeve_policy"] = {
        "main_v2_balanced": {
            "deep_bear": {"core": 0.40, "future_winner": 0.20, "early_scout": 0.00, "cash": 0.40},
            "bear": {"core": 0.45, "future_winner": 0.25, "early_scout": 0.05, "cash": 0.25},
            "neutral": {"core": 0.25, "future_winner": 0.55, "early_scout": 0.15, "cash": 0.05},
            "bull": {"core": 0.20, "future_winner": 0.60, "early_scout": 0.20, "cash": 0.00},
            "strong_bull": {"core": 0.15, "future_winner": 0.65, "early_scout": 0.20, "cash": 0.00},
        }
    }
    policy["target_n"] = {
        "main": {"bear": 18, "neutral": 15, "bull": 12, "strong_bull": 12},
        "main_v2_sleeves": {
            "deep_bear": {"core": 5, "future_winner": 3, "early_scout": 0},
            "bear": {"core": 5, "future_winner": 4, "early_scout": 1},
            "neutral": {"core": 4, "future_winner": 7, "early_scout": 2},
            "bull": {"core": 3, "future_winner": 8, "early_scout": 3},
            "strong_bull": {"core": 2, "future_winner": 8, "early_scout": 3},
        },
        "concentrated": {"deep_bear": 0, "bear": 3, "neutral": 5, "bull": 5, "strong_bull": 3},
        "alpha_sprint": {"deep_bear": 0, "bear": 0, "neutral": 0, "bull": 3, "strong_bull": 3},
    }
    policy["orchestrator_policy"] = {
        "deep_bear": {"main": 0.40, "concentrated": 0.00, "alpha_sprint": 0.00, "tactical": 0.00, "cash": 0.60},
        "bear": {"main": 0.55, "concentrated": 0.05, "alpha_sprint": 0.00, "tactical": 0.00, "cash": 0.40},
        "neutral": {"main": 0.55, "concentrated": 0.25, "alpha_sprint": 0.00, "tactical": 0.00, "cash": 0.20},
        "bull": {"main": 0.60, "concentrated": 0.25, "alpha_sprint": 0.05, "tactical": 0.00, "cash": 0.10},
        "strong_bull": {"main": 0.55, "concentrated": 0.25, "alpha_sprint": 0.10, "tactical": 0.00, "cash": 0.10},
    }
    policy["entry_timing"] = {
        "main": {
            "new_buy_frequency": "monthly_only",
            "incumbent_buffer": 3,
            "winner_buffer": 5,
        },
        "concentrated": {
            "staged_entry": True,
            "initial_pct": 0.60,
            "add_on_trigger": "follow_through_5pct_or_1atr",
            "review_days": 7,
        },
        "alpha_sprint": {
            "staged_entry": True,
            "initial_pct": 0.50,
            "add_on_trigger": "follow_through_5pct_or_breakout_retest",
            "activation_regimes": ["bull", "strong_bull"],
        },
    }
    policy["exit_rules"] = {
        "main": {
            "exit_on": ["thesis_break", "rs_decay", "theme_ending", "ma200_break", "risk_sensing_exit"],
            "avoid_rank_only_exit": True,
        },
        "concentrated": {
            "hard_stop": -0.10,
            "trailing_stop": -0.15,
            "rs_decay_pp": -30,
            "weekly_review": True,
            "enable_better_replacement_swap": True,
        },
        "alpha_sprint": {
            "hard_stop": -0.07,
            "trailing_stop": -0.12,
            "time_stop_days": 30,
            "failed_breakout_exit": True,
        },
    }
    policy["cash_policy"] = {
        "deep_bear": {"cash_floor": 0.60},
        "bear": {"cash_floor": 0.40},
        "neutral": {"cash_floor": 0.15},
        "bull": {"cash_floor": 0.05},
        "strong_bull": {"cash_floor": 0.05},
    }
    policy["execution_policy"] = {
        "default_order_type": "limit",
        "main_order_style": "limit_or_twap",
        "concentrated_order_style": "staged_marketable_limit",
        "alpha_sprint_order_style": "marketable_limit",
        "auto_broker_execution": False,
    }
    policy["promotion_gates"] = {
        "main_gate": {
            "max_cagr_regression_pp": 1.0,
            "max_sharpe_regression": 0.08,
            "max_dd_worsening_pp": 1.0,
            "turnover_worsening_limit_pp": 5.0,
        },
        "concentrated_gate": {
            "min_cagr": 0.30,
            "max_dd_floor": -0.25,
            "single_name_cap_violations_allowed": 0,
        },
        "orchestrator_gate": {
            "min_cagr_improvement_pp": 2.0,
            "max_dd_floor": -0.25,
            "max_avg_cash": 0.25,
        },
        "stress_gate": {
            "required_windows": ["2020", "2022", "momentum_drawdown", "rate_shock", "vix_spike"],
        },
        "cost_sensitivity_bps": [25, 50, 75],
        "stability_gate": {
            "require_rolling_3y_pass": True,
            "require_rolling_5y_pass": True,
        },
    }

    future = sleeve_audit.get("future_winner") or {}
    early = sleeve_audit.get("early_scout") or {}
    core = sleeve_audit.get("core_compounder") or {}
    policy["proposals"] = [
        {
            "kind": "feature_gate_learning",
            "status": "carry_forward_candidate",
            "proposal_count": len(policy["feature_gates"]),
            "rationale": "Existing feature-gate learner found regime-specific bear gates; keep as policy input, still proposal-only.",
        },
        {
            "kind": "target_n_learning",
            "mandate": "main",
            "current_avg_stock_names": main_metrics.get("avg_stock_names"),
            "proposed_neutral_n": 15,
            "rationale": "Main is broad while Main v2 latest concentrates to 11 shadow positions with explicit sleeve books.",
        },
        {
            "kind": "sleeve_allocation_learning",
            "mandate": "main_v2",
            "proposed_neutral": policy["sleeve_policy"]["main_v2_balanced"]["neutral"],
            "evidence": {
                "future_latest_multi_year_winner": future.get("latest_gate_avg_multi_year_winner_score"),
                "early_latest_multi_year_winner": early.get("latest_gate_avg_multi_year_winner_score"),
                "core_latest_multi_year_winner": core.get("latest_gate_avg_multi_year_winner_score"),
            },
            "rationale": "Future winner sleeve has the strongest latest multi-year winner evidence; early scout stays capped.",
        },
        {
            "kind": "concentrated_policy_learning",
            "mandate": "concentrated",
            "proposed_neutral_capacity": policy["orchestrator_policy"]["neutral"]["concentrated"],
            "cap_violations": len(concentrated_policy.get("cap_violations") or []),
            "entry_blocks": len(concentrated_policy.get("entry_blocked") or []),
            "risk_blocks": len(concentrated_policy.get("risk_blocked") or []),
            "rationale": "Concentrated is high CAGR but needs cap/timing gates before larger capital allocation.",
        },
        {
            "kind": "alpha_sprint_policy_learning",
            "mandate": "alpha_sprint",
            "activation": policy["orchestrator_policy"]["bull"]["alpha_sprint"],
            "latest_candidate_count": alpha_sprint.get("candidate_count"),
            "latest_active": alpha_sprint.get("active"),
            "rationale": "Sprint stays 0% in neutral; candidates are tracked for bull/strong_bull activation tests.",
        },
        {
            "kind": "exit_timing_learning",
            "mandate": "concentrated",
            "proposed_exit_rules": policy["exit_rules"]["concentrated"],
            "rationale": "Risk audit found current holdings with RS decay; weekly review and better-replacement swap become challenger rules.",
        },
    ]
    return policy


def render_summary(policy: dict[str, Any], validation: dict[str, Any]) -> str:
    ev = policy.get("evidence_summary") or {}
    lines = [
        "# AutoLearning Policy Candidate Summary",
        "",
        "This candidate is proposal-only. It does not change production defaults.",
        "",
        "## Evidence",
        "",
        f"- Main CAGR: {safe_float(ev.get('main_cagr')):.2%}",
        f"- Main Sharpe: {ev.get('main_sharpe')}",
        f"- Main MaxDD: {safe_float(ev.get('main_max_dd')):.2%}",
        f"- Main average stock names: {safe_float(ev.get('main_avg_stock_names')):.2f}",
        f"- Concentrated CAGR: {safe_float(ev.get('concentrated_cagr')):.2%}",
        f"- Concentrated Sharpe: {ev.get('concentrated_sharpe')}",
        f"- Concentrated MaxDD: {safe_float(ev.get('concentrated_max_dd')):.2%}",
        f"- Trade count: {ev.get('trade_count')}",
        f"- Feature-gate candidates carried forward: {ev.get('feature_gate_candidate_count')}",
        "",
        "## Candidate Scope",
        "",
        "- Feature gates: carry forward existing bear regime proposals.",
        "- Main v2: propose sleeve allocation and target-N policies.",
        "- Concentrated: propose capacity, cap, entry, and exit policy candidates.",
        "- Alpha Sprint: propose bull-only activation and risk rules.",
        "- Orchestrator: propose regime capital maps for challenger backtest only.",
        "",
        "## Validation",
        "",
        f"- Schema valid: {validation.get('valid')}",
        f"- Issues: {', '.join(validation.get('issues') or []) or 'none'}",
        "",
        "## Next Required Step",
        "",
        "Build `tools/auto_policy_challenger.py` to run this policy as a challenger against legacy champion metrics.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--candidate-out", default=DEFAULT_CANDIDATE_OUT)
    parser.add_argument("--active-policy", default=DEFAULT_ACTIVE_POLICY)
    parser.add_argument("--diff-out", default=DEFAULT_DIFF_OUT)
    parser.add_argument("--evidence-out", default=DEFAULT_EVIDENCE_OUT)
    parser.add_argument("--summary-out", default=DEFAULT_SUMMARY_OUT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    evidence = load_auto_learning_evidence(repo_path(args.latest_run), root=REPO_ROOT)
    policy = build_policy_from_evidence(evidence)
    validation = validate_policy(policy)
    yaml_text = render_policy_yaml(policy)

    active_path = repo_path(args.active_policy)
    old_text = active_path.read_text(encoding="utf-8") if active_path.exists() else ""
    diff = diff_text(
        old_text,
        yaml_text,
        str(active_path.relative_to(REPO_ROOT)) if active_path.exists() else "auto_learning_policy_active.yaml (missing)",
        str(Path(args.candidate_out)),
    )
    diff_md = "# AutoLearning Policy Proposal Diff\n\n```diff\n" + diff + "\n```\n"
    summary_md = render_summary(policy, validation)

    if args.dry_run:
        print(summary_md)
        print(diff_md)
        return 0 if validation.get("valid") else 1

    candidate_path = repo_path(args.candidate_out)
    diff_path = repo_path(args.diff_out)
    evidence_path = repo_path(args.evidence_out)
    summary_path = repo_path(args.summary_out)

    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_path.write_text(yaml_text, encoding="utf-8")
    diff_path.parent.mkdir(parents=True, exist_ok=True)
    diff_path.write_text(diff_md, encoding="utf-8")
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(summary_md, encoding="utf-8")
    write_json(evidence_path, evidence)

    print(f"[auto-policy] wrote {candidate_path}")
    print(f"[auto-policy] wrote {summary_path}")
    print(f"[auto-policy] schema_valid={validation.get('valid')}")
    return 0 if validation.get("valid") else 1


if __name__ == "__main__":
    raise SystemExit(main())
