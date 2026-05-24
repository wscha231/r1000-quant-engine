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
| high | `idle_cash_redeploy` | main | `candidate_for_combination` | monthly_proxy | false | 34.64 |
| high | `macro_crisis_cash_ladder` | main | `candidate_for_combination` | monthly_proxy | false | 27.16 |
| high | `long_winner_hold_template` | main | `conditional_defense_only` | historical_replay | false | -11.41 |
| high | `monster_early_staged_sizing` | main | `conditional_defense_only` | historical_replay | false | -15.64 |
| high | `style_macro_router` | main | `candidate_for_combination` | historical_replay | false | -17.31 |
| high | `style_macro_router` | concentrated | `conditional_defense_only` | historical_replay | false | -47.38 |
| high | `monster_early_staged_sizing` | concentrated | `conditional_defense_only` | historical_replay | false | -51.33 |
| watch | `account_aware_execution` | main | `shadow_watch` | production | false | -21.10 |
| watch | `position_hard_stop_distribution` | main | `shadow_watch` | diagnostic | false | -27.96 |
| watch | `stale_leader_trim` | main | `shadow_watch` | diagnostic | false | -27.96 |
| watch | `shakeout_hold_veto` | main | `shadow_watch` | diagnostic | false | -27.96 |
| watch | `governance_catalyst_watch` | main | `shadow_watch` | diagnostic | false | -27.96 |

## Policy Evidence

| Policy | Portfolio | CAGR | MaxDD | Sharpe | Delta CAGR | Delta MaxDD | Stage | Source |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `position_hard_stop_distribution` | main | 21.45% | -32.45% | 1.044 | 0.00pp | 0.00pp | `shadow_watch` | outputs/historical_trade_journey/historical_decision_priorities.csv |
| `position_hard_stop_distribution` | concentrated | 19.63% | -45.68% | 0.773 | -16.98pp | -3.10pp | `reject_current_form` | sidecar:outputs/broker_position_risk_replay/concentrated/metrics.json |
| `macro_crisis_cash_ladder` | main | 30.32% | -16.08% | 1.926 | 8.87pp | 16.36pp | `candidate_for_combination` | outputs/crisis_reentry_replay/metrics.json#best_by_cagr |
| `stale_leader_trim` | main | 21.45% | -32.45% | 1.044 | 0.00pp | 0.00pp | `shadow_watch` | outputs/historical_trade_journey/historical_decision_priorities.csv |
| `shakeout_hold_veto` | main | 21.45% | -32.45% | 1.044 | 0.00pp | 0.00pp | `shadow_watch` | outputs/shakeout_breakdown_study/pattern_summary.json |
| `monster_early_staged_sizing` | main | 18.17% | -22.18% | 1.066 | -3.28pp | 10.27pp | `conditional_defense_only` | sidecar:outputs/monster_lifecycle_review_main/metrics.json |
| `monster_early_staged_sizing` | concentrated | 19.13% | -21.45% | 1.137 | -17.48pp | 21.12pp | `conditional_defense_only` | sidecar:outputs/monster_lifecycle_review_concentrated/metrics.json |
| `long_winner_hold_template` | main | 18.84% | -21.15% | 1.068 | -2.61pp | 11.30pp | `conditional_defense_only` | sidecar:outputs/lifecycle_review_overlay_main/metrics.json |
| `idle_cash_redeploy` | main | 34.99% | -15.93% | 1.913 | 13.54pp | 16.52pp | `candidate_for_combination` | outputs/main_cash_drag_replay/summary.json#best_by_cagr |
| `style_macro_router` | main | 21.75% | -28.67% | 1.070 | 0.30pp | 3.77pp | `candidate_for_combination` | sidecar:outputs/main_v2_backtest/metrics.json |
| `style_macro_router` | concentrated | 28.55% | -34.40% | 1.132 | -8.07pp | 8.17pp | `conditional_defense_only` | sidecar:outputs/concentrated_policy_replay/metrics.json |
| `governance_catalyst_watch` | main | 21.45% | -32.45% | 1.044 | 0.00pp | 0.00pp | `shadow_watch` | outputs/governance_catalyst/summary.json |
| `auto_learning_policy_candidate` | main | 21.45% | -32.45% | 1.044 | 0.00pp | 0.00pp | `shadow_watch` | outputs/autolearning_winner_challenger/summary.json |
| `account_aware_execution` | main | 21.22% | -31.65% | 1.021 | -0.23pp | 0.79pp | `shadow_watch` | sidecar:outputs/broker_execution_policy_replay/main/metrics.json |
| `account_aware_execution` | concentrated | 17.41% | -41.11% | 0.699 | -19.20pp | 1.47pp | `shadow_watch` | sidecar:outputs/broker_execution_policy_replay/concentrated/metrics.json |

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
