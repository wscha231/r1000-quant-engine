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
| highest | `idle_cash_redeploy` | main | `confirm_with_production_compatible_replay` | monthly_proxy | true | 79.48 |
| high | `macro_crisis_cash_ladder` | main | `candidate_for_combination` | monthly_proxy | false | 33.81 |
| high | `long_winner_hold_template` | main | `candidate_for_combination` | historical_replay | false | -9.10 |
| high | `style_macro_router` | main | `candidate_for_combination` | historical_replay | false | -12.12 |
| high | `account_aware_execution` | main | `candidate_for_combination` | production | false | -22.69 |
| high | `monster_early_staged_sizing` | main | `conditional_defense_only` | historical_replay | false | -30.85 |
| high | `monster_early_staged_sizing` | concentrated | `conditional_defense_only` | historical_replay | false | -62.90 |
| watch | `position_hard_stop_distribution` | main | `shadow_watch` | diagnostic | false | -32.80 |
| watch | `stale_leader_trim` | main | `shadow_watch` | diagnostic | false | -32.80 |
| watch | `shakeout_hold_veto` | main | `shadow_watch` | diagnostic | false | -32.80 |
| watch | `governance_catalyst_watch` | main | `shadow_watch` | diagnostic | false | -32.80 |
| watch | `auto_learning_policy_candidate` | main | `shadow_watch` | proposal | false | -32.80 |

## Policy Evidence

| Policy | Portfolio | CAGR | MaxDD | Sharpe | Delta CAGR | Delta MaxDD | Stage | Source |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `position_hard_stop_distribution` | main | 18.39% | -33.75% | 0.906 | 0.00pp | 0.00pp | `shadow_watch` | outputs/historical_trade_journey/historical_decision_priorities.csv |
| `position_hard_stop_distribution` | concentrated | 16.69% | -50.24% | 0.748 | -10.39pp | -11.06pp | `reject_current_form` | sidecar:outputs/broker_position_risk_replay/concentrated/metrics.json |
| `macro_crisis_cash_ladder` | main | 29.40% | -14.04% | 1.857 | 11.01pp | 19.71pp | `candidate_for_combination` | outputs/crisis_reentry_replay/metrics.json#best_by_cagr |
| `stale_leader_trim` | main | 18.39% | -33.75% | 0.906 | 0.00pp | 0.00pp | `shadow_watch` | outputs/historical_trade_journey/historical_decision_priorities.csv |
| `shakeout_hold_veto` | main | 18.39% | -33.75% | 0.906 | 0.00pp | 0.00pp | `shadow_watch` | outputs/shakeout_breakdown_study/pattern_summary.json |
| `monster_early_staged_sizing` | main | 12.99% | -25.05% | 0.804 | -5.40pp | 8.70pp | `conditional_defense_only` | sidecar:outputs/monster_lifecycle_review_main/metrics.json |
| `monster_early_staged_sizing` | concentrated | 14.18% | -26.71% | 0.887 | -12.89pp | 12.46pp | `conditional_defense_only` | sidecar:outputs/monster_lifecycle_review_concentrated/metrics.json |
| `long_winner_hold_template` | main | 20.32% | -26.23% | 1.018 | 1.93pp | 7.52pp | `candidate_for_combination` | sidecar:outputs/lifecycle_review_overlay_main/metrics.json |
| `idle_cash_redeploy` | main | 33.23% | -15.00% | 1.795 | 14.84pp | 18.75pp | `confirm_with_production_compatible_replay` | outputs/main_cash_drag_replay/summary.json#best_by_cagr |
| `style_macro_router` | main | 19.62% | -26.52% | 0.952 | 1.23pp | 7.23pp | `candidate_for_combination` | sidecar:outputs/main_v2_backtest/metrics.json |
| `style_macro_router` | concentrated | 13.82% | -47.79% | 0.607 | -13.25pp | -8.61pp | `reject_current_form` | sidecar:outputs/concentrated_policy_replay/metrics.json |
| `governance_catalyst_watch` | main | 18.39% | -33.75% | 0.906 | 0.00pp | 0.00pp | `shadow_watch` | outputs/governance_catalyst/summary.json |
| `auto_learning_policy_candidate` | main | 18.39% | -33.75% | 0.906 | 0.00pp | 0.00pp | `shadow_watch` | outputs/autolearning_winner_challenger/summary.json |
| `account_aware_execution` | main | 19.07% | -33.05% | 0.905 | 0.68pp | 0.70pp | `candidate_for_combination` | sidecar:outputs/broker_execution_policy_replay/main/metrics.json |
| `account_aware_execution` | concentrated | 23.36% | -39.16% | 0.905 | -3.71pp | 0.01pp | `shadow_watch` | sidecar:outputs/broker_execution_policy_replay/concentrated/metrics.json |

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
