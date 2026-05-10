"""Hypothesis generation for AutoLearning v2."""
from __future__ import annotations

from typing import Any


def _ids(anomalies: list[dict[str, Any]]) -> set[str]:
    return {str(item.get("id")) for item in anomalies}


def generate_hypotheses(anomalies: list[dict[str, Any]], novelty_report: dict[str, Any]) -> list[dict[str, Any]]:
    anomaly_ids = _ids(anomalies)
    hypotheses: list[dict[str, Any]] = []

    if "bear_rs_theme_inversion" in anomaly_ids:
        hypotheses.append(
            {
                "id": "bear_rs_reversal_v1",
                "status": "proposal_only",
                "observation_ids": ["bear_rs_theme_inversion", "bear_oversold_value_positive_ic"],
                "hypothesis": "In bear regimes, price-confirmed RS recovery and oversold value outperform static theme classification.",
                "rules": [
                    {
                        "rule_type": "feature_gate",
                        "if": {"regime": "bear"},
                        "then": {
                            "amplify": {"rs_acceleration_score": 1.30, "h1_oversold_value_score": 1.30},
                            "disable": ["theme_phase_multiplier_primary", "theme_phase_multiplier_max"],
                        },
                        "limits": {"proposal_only": True, "production_activation_allowed": False, "max_ttl_days": 90},
                    },
                    {
                        "rule_type": "sleeve_allocation",
                        "if": {"regime": "bear", "rs_recovery_ic_positive": True},
                        "then": {"main": {"core": 0.35, "future_winner": 0.35, "early_scout": 0.00, "cash": 0.30}},
                        "limits": {"proposal_only": True, "production_activation_allowed": False, "max_weight_delta": 0.10},
                    },
                ],
                "test_plan": {
                    "windows": ["all_bear_months", "2020", "2022"],
                    "metrics": ["CAGR", "MaxDD", "Sharpe", "turnover", "bear_hit_rate"],
                    "falsify_if": ["maxdd_worsens", "cagr_delta_pp < -1.0", "bear_trade_loss_rate_spikes"],
                },
                "exploration_budget": {"stage": "shadow", "capital_weight": 0.0},
            }
        )

    if "main_broad_high_turnover" in anomaly_ids:
        hypotheses.append(
            {
                "id": "main_future_alpha_concentration_v1",
                "status": "proposal_only",
                "observation_ids": ["main_broad_high_turnover"],
                "hypothesis": "Main alpha is diluted by broad target N; an internal sleeve orchestrator can concentrate future_winner while capping early_scout.",
                "rules": [
                    {
                        "rule_type": "target_n",
                        "if": {"mandate": "main", "avg_stock_names_gt": 20},
                        "then": {"target_n": {"neutral": 15, "bull": 12, "bear": 18}},
                        "limits": {"proposal_only": True, "production_activation_allowed": False, "max_target_n_delta": 5},
                    },
                    {
                        "rule_type": "sleeve_allocation",
                        "if": {"mandate": "main_v2", "regime": "neutral"},
                        "then": {"core": 0.25, "future_winner": 0.55, "early_scout": 0.15, "cash": 0.05},
                        "limits": {"proposal_only": True, "production_activation_allowed": False, "max_weight_delta": 0.10},
                    },
                ],
                "test_plan": {
                    "windows": ["all_months", "2022", "2024_ai_bull"],
                    "metrics": ["CAGR", "MaxDD", "Sharpe", "turnover", "sleeve_attribution"],
                    "falsify_if": ["turnover_not_reduced", "future_winner_contribution_not_positive"],
                },
                "exploration_budget": {"stage": "shadow", "capital_weight": 0.0},
            }
        )

    if "concentrated_alpha_underallocated" in anomaly_ids:
        hypotheses.append(
            {
                "id": "concentrated_neutral_25_v1",
                "status": "proposal_only",
                "observation_ids": ["concentrated_alpha_underallocated"],
                "hypothesis": "Concentrated should use a dynamic 20-30% risk budget when caps, entry quality, and weekly exits pass.",
                "rules": [
                    {
                        "rule_type": "orchestrator_allocation",
                        "if": {"regime": "neutral", "concentrated_gate": "pass"},
                        "then": {"main": 0.55, "concentrated": 0.25, "alpha_sprint": 0.00, "cash": 0.20},
                        "limits": {"proposal_only": True, "production_activation_allowed": False, "max_weight_delta": 0.15},
                    },
                    {
                        "rule_type": "exit_timing",
                        "if": {"mandate": "concentrated"},
                        "then": {"weekly_review": True, "hard_stop": -0.10, "trailing_stop": -0.15, "better_replacement_swap": True},
                        "limits": {"proposal_only": True, "production_activation_allowed": False, "max_stop_delta": 0.03},
                    },
                ],
                "test_plan": {
                    "windows": ["all_months", "all_bear_months", "2022", "2024_ai_bull"],
                    "metrics": ["portfolio_CAGR", "portfolio_MaxDD", "cap_violations", "cash_drag", "turnover"],
                    "falsify_if": ["unified_maxdd_below_floor", "single_name_cap_violation", "stress_window_worsens"],
                },
                "exploration_budget": {"stage": "shadow", "capital_weight": 0.0},
            }
        )

    if "risk_sensing_defense_return_tradeoff" in anomaly_ids:
        hypotheses.append(
            {
                "id": "risk_governor_layered_exit_v1",
                "status": "proposal_only",
                "observation_ids": ["risk_sensing_defense_return_tradeoff"],
                "hypothesis": "Risk sensing needs position-aware exits and better-replacement swaps rather than blunt portfolio cash cuts.",
                "rules": [
                    {
                        "rule_type": "risk_governor",
                        "if": {"drawdown_breaker": "active", "strong_alternate_available": True},
                        "then": {"prefer": "weak_to_strong_swap", "avoid": "blanket_cash_cut"},
                        "limits": {"proposal_only": True, "production_activation_allowed": False, "max_shadow_capital_weight": 0.0},
                    }
                ],
                "test_plan": {
                    "windows": ["2020", "2022", "all_drawdown_windows"],
                    "metrics": ["MaxDD", "CAGR", "Sharpe", "late_exit_rate", "swap_hit_rate"],
                    "falsify_if": ["cagr_delta_pp < -1.0", "sharpe_delta < 0.0"],
                },
                "exploration_budget": {"stage": "shadow", "capital_weight": 0.0},
            }
        )

    if "cluster_conviction_asymmetry" in anomaly_ids:
        hypotheses.append(
            {
                "id": "cluster_conviction_router_v1",
                "status": "proposal_only",
                "observation_ids": ["cluster_conviction_asymmetry"],
                "hypothesis": "Trade clusters can route risk: strong clusters get conviction boost, weak clusters trigger caution/block rules.",
                "rules": [
                    {
                        "rule_type": "theme_policy",
                        "if": {"trade_cluster": [1, 5]},
                        "then": {"allow_conviction_bonus": True, "max_bonus": 0.05},
                        "limits": {"proposal_only": True, "production_activation_allowed": False, "max_weight_delta": 0.05},
                    },
                    {
                        "rule_type": "feature_gate",
                        "if": {"trade_cluster": [0, 6]},
                        "then": {"pattern_block_or_caution": True},
                        "limits": {"proposal_only": True, "production_activation_allowed": False, "max_ttl_days": 90},
                    },
                ],
                "test_plan": {
                    "windows": ["all_months", "all_bear_months"],
                    "metrics": ["cluster_hit_rate", "loss_rate", "avg_return", "turnover"],
                    "falsify_if": ["strong_cluster_bonus_reduces_avg_return", "block_rule_removes_winners"],
                },
                "exploration_budget": {"stage": "shadow", "capital_weight": 0.0},
            }
        )

    if "explosion_stack_dormant" in anomaly_ids:
        hypotheses.append(
            {
                "id": "alpha_sprint_breakout_fallback_v1",
                "status": "proposal_only",
                "observation_ids": ["explosion_stack_dormant"],
                "hypothesis": "Alpha Sprint should use breakout/RS/catalyst fallback signals until explosion_* features become nonzero and validated.",
                "rules": [
                    {
                        "rule_type": "entry_timing",
                        "if": {"mandate": "alpha_sprint", "regime": ["bull", "strong_bull"]},
                        "then": {
                            "require_any": ["rs_acceleration_score", "breakout_fresh_20d", "entry_quality_score", "volatility_contraction_score"],
                            "staged_entry": True,
                            "hard_stop": -0.07,
                        },
                        "limits": {"proposal_only": True, "production_activation_allowed": False, "max_shadow_capital_weight": 0.0},
                    }
                ],
                "test_plan": {
                    "windows": ["bull_months", "strong_bull_months", "2024_ai_bull"],
                    "metrics": ["standalone_CAGR", "hit_rate", "avg_loss", "portfolio_contribution"],
                    "falsify_if": ["hit_rate < 0.45", "maxdd_worsens_by_more_than_2pp"],
                },
                "exploration_budget": {"stage": "shadow", "capital_weight": 0.0},
            }
        )

    if "sidecar_without_counterfactual_replay" in anomaly_ids:
        hypotheses.append(
            {
                "id": "counterfactual_replay_priority_v1",
                "status": "proposal_only",
                "observation_ids": ["sidecar_without_counterfactual_replay"],
                "hypothesis": "Policy creativity should be blocked from promotion until each sidecar has historical replay evidence.",
                "rules": [
                    {
                        "rule_type": "counterfactual_required",
                        "then": {"block_promotion_until": ["main_v2_replay", "orchestrator_replay", "alpha_sprint_replay"]},
                        "limits": {"proposal_only": True, "production_activation_allowed": False},
                    }
                ],
                "test_plan": {
                    "windows": ["all_months"],
                    "metrics": ["artifact_completeness", "backtest_executed", "stress_window_coverage"],
                    "falsify_if": ["none"],
                },
                "exploration_budget": {"stage": "shadow", "capital_weight": 0.0},
            }
        )

    if not hypotheses:
        hypotheses.append(
            {
                "id": "watch_only_no_material_anomaly_v1",
                "status": "proposal_only",
                "observation_ids": [],
                "hypothesis": "No material anomaly was detected; continue standard feature-gate proposal workflow.",
                "rules": [],
                "test_plan": {"windows": ["next_run"], "metrics": ["artifact_completeness"]},
                "exploration_budget": {"stage": "shadow", "capital_weight": 0.0},
            }
        )

    for hypothesis in hypotheses:
        hypothesis["novelty_context"] = {
            "status": novelty_report.get("status"),
            "flags": novelty_report.get("flags") or [],
            "known_regime_confidence": novelty_report.get("known_regime_confidence"),
        }
    return hypotheses


def render_hypothesis_report(hypotheses: list[dict[str, Any]]) -> str:
    lines = [
        "# AutoLearning v2 Hypotheses",
        "",
        "Each hypothesis is falsifiable and proposal-only. Backtests and human approval are required before use.",
        "",
    ]
    for idx, hypothesis in enumerate(hypotheses, 1):
        lines.extend(
            [
                f"## {idx}. {hypothesis['id']}",
                "",
                f"- Status: `{hypothesis.get('status')}`",
                f"- Hypothesis: {hypothesis.get('hypothesis')}",
                f"- Observations: {', '.join(hypothesis.get('observation_ids') or []) or 'none'}",
                f"- Exploration stage: `{(hypothesis.get('exploration_budget') or {}).get('stage')}`",
                "",
                "Test plan:",
                "",
                f"- Windows: {', '.join((hypothesis.get('test_plan') or {}).get('windows') or [])}",
                f"- Metrics: {', '.join((hypothesis.get('test_plan') or {}).get('metrics') or [])}",
                f"- Falsify if: {', '.join((hypothesis.get('test_plan') or {}).get('falsify_if') or [])}",
                "",
            ]
        )
    return "\n".join(lines)
