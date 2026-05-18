# AlphaOps Policy Fusion

This report fuses sidecar and replay evidence into one conflict-aware activation plan.
It does not mutate production defaults.

## Production Rule

1. Hard exits and crisis defense win over alpha expansion.
2. Shakeout logic can defer soft trims, but never hard stops.
3. Monster staged sizing can add risk only after liquidity, market-cap, macro, and risk gates pass.
4. AutoLearning can propose policies, but replay gates decide activation.

## Activation Queue

| Priority | Policy | Portfolio | Stage | Evidence | Target Pass | Score |
| --- | --- | --- | --- | --- | ---: | ---: |
| highest | `idle_cash_redeploy` | main | `confirm_with_production_compatible_replay` | monthly_proxy | true | 85.42 |
| highest | `macro_crisis_cash_ladder` | main | `confirm_with_production_compatible_replay` | monthly_proxy | true | 77.55 |
| high | `style_macro_router` | main | `candidate_for_combination` | historical_replay | false | -9.33 |
| high | `long_winner_hold_template` | main | `candidate_for_combination` | historical_replay | false | -10.89 |
| high | `monster_early_staged_sizing` | main | `conditional_defense_only` | historical_replay | false | -24.34 |
| watch | `position_hard_stop_distribution` | main | `shadow_watch` | diagnostic | false | -31.10 |
| watch | `stale_leader_trim` | main | `shadow_watch` | diagnostic | false | -31.10 |
| watch | `shakeout_hold_veto` | main | `shadow_watch` | diagnostic | false | -31.10 |
| watch | `governance_catalyst_watch` | main | `shadow_watch` | diagnostic | false | -31.10 |
| watch | `auto_learning_policy_candidate` | main | `shadow_watch` | proposal | false | -31.10 |
| blocked | `account_aware_execution` | main | `reject_current_form` | production | false | -39.86 |
| blocked | `account_aware_execution` | concentrated | `reject_current_form` | production | false | -66.94 |

## Policy Evidence

| Policy | Portfolio | CAGR | MaxDD | Sharpe | Delta CAGR | Delta MaxDD | Stage | Source |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `position_hard_stop_distribution` | main | 18.44% | -31.93% | 0.848 | 0.00pp | 0.00pp | `shadow_watch` | outputs/historical_trade_journey/historical_decision_priorities.csv |
| `position_hard_stop_distribution` | concentrated | 26.93% | -31.77% | 1.164 | -8.17pp | -9.10pp | `reject_current_form` | sidecar:outputs/broker_position_risk_replay/concentrated/metrics.json |
| `macro_crisis_cash_ladder` | main | 32.08% | -13.65% | 1.877 | 13.64pp | 18.27pp | `confirm_with_production_compatible_replay` | outputs/crisis_reentry_replay/metrics.json#best_by_cagr |
| `stale_leader_trim` | main | 18.44% | -31.93% | 0.848 | 0.00pp | 0.00pp | `shadow_watch` | outputs/historical_trade_journey/historical_decision_priorities.csv |
| `shakeout_hold_veto` | main | 18.44% | -31.93% | 0.848 | 0.00pp | 0.00pp | `shadow_watch` | outputs/shakeout_breakdown_study/pattern_summary.json |
| `monster_early_staged_sizing` | main | 15.55% | -25.04% | 0.885 | -2.89pp | 6.89pp | `conditional_defense_only` | sidecar:outputs/monster_lifecycle_review_main/metrics.json |
| `monster_early_staged_sizing` | concentrated | 18.83% | -25.23% | 1.025 | -16.28pp | -2.55pp | `reject_current_form` | sidecar:outputs/monster_lifecycle_review_concentrated/metrics.json |
| `long_winner_hold_template` | main | 21.51% | -28.10% | 1.052 | 3.07pp | 3.83pp | `candidate_for_combination` | sidecar:outputs/lifecycle_review_overlay_main/metrics.json |
| `idle_cash_redeploy` | main | 37.06% | -13.40% | 1.848 | 18.62pp | 18.53pp | `confirm_with_production_compatible_replay` | outputs/main_cash_drag_replay/summary.json#best_by_cagr |
| `style_macro_router` | main | 21.48% | -27.20% | 1.006 | 3.04pp | 4.72pp | `candidate_for_combination` | sidecar:outputs/main_v2_backtest/metrics.json |
| `style_macro_router` | concentrated | 14.02% | -47.95% | 0.584 | -21.08pp | -25.28pp | `reject_current_form` | sidecar:outputs/concentrated_policy_replay/metrics.json |
| `governance_catalyst_watch` | main | 18.44% | -31.93% | 0.848 | 0.00pp | 0.00pp | `shadow_watch` | outputs/governance_catalyst/summary.json |
| `auto_learning_policy_candidate` | main | 18.44% | -31.93% | 0.848 | 0.00pp | 0.00pp | `shadow_watch` | outputs/autolearning_winner_challenger/summary.json |
| `account_aware_execution` | main | 14.94% | -32.40% | 0.672 | -3.50pp | -0.47pp | `reject_current_form` | sidecar:outputs/broker_execution_policy_replay/main/metrics.json |
| `account_aware_execution` | concentrated | 26.72% | -29.98% | 1.039 | -8.38pp | -7.31pp | `reject_current_form` | sidecar:outputs/broker_execution_policy_replay/concentrated/metrics.json |

## Conflict Matrix

| Policy A | Policy B | Winner | Reason |
| --- | --- | --- | --- |
| `position_hard_stop_distribution` | `shakeout_hold_veto` | `position_hard_stop_distribution` | A hard stop or confirmed distribution is a survival rule; shakeout logic can only veto soft/partial trims. |
| `position_hard_stop_distribution` | `long_winner_hold_template` | `position_hard_stop_distribution` | Long-hold patience never protects a position that has hit hard exit criteria. |
| `macro_crisis_cash_ladder` | `idle_cash_redeploy` | `macro_crisis_cash_ladder` | Crisis cash floors must be satisfied before normal-market idle cash is redeployed. |
| `macro_crisis_cash_ladder` | `monster_early_staged_sizing` | `macro_crisis_cash_ladder` | New risk-on scouting is blocked in red/crisis regimes unless the policy is explicitly a recovery re-entry. |
| `stale_leader_trim` | `long_winner_hold_template` | `stale_leader_trim` | A former winner that underperforms SPY/QQQ and loses trend quality is trimmed before long-hold protection applies. |
| `shakeout_hold_veto` | `stale_leader_trim` | `conditional` | Shakeout evidence can defer the first half-trim, but only when hard-distribution and relative-strength breakdown are absent. |
| `monster_early_staged_sizing` | `idle_cash_redeploy` | `conditional` | Idle cash should fund confirmed monster stages first; otherwise it is spread across the ranked book. |
| `style_macro_router` | `monster_early_staged_sizing` | `style_macro_router` | The style router determines whether breakout growth, turnaround, or quality is the preferred opportunity set. |
| `auto_learning_policy_candidate` | `all_production_policies` | `all_production_policies` | AutoLearning may propose and replay policies, but it cannot mutate production without passing gates. |
