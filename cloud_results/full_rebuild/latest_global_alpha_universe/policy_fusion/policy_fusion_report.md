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
| highest | `idle_cash_redeploy` | main | `confirm_with_production_compatible_replay` | monthly_proxy | true | 83.15 |
| highest | `macro_crisis_cash_ladder` | main | `confirm_with_production_compatible_replay` | monthly_proxy | true | 76.03 |
| high | `account_aware_execution` | concentrated | `candidate_for_combination` | production | false | -0.07 |
| high | `style_macro_router` | main | `candidate_for_combination` | historical_replay | false | -12.69 |
| high | `account_aware_execution` | main | `candidate_for_combination` | production | false | -21.81 |
| high | `monster_early_staged_sizing` | main | `conditional_defense_only` | historical_replay | false | -27.16 |
| high | `monster_early_staged_sizing` | concentrated | `conditional_defense_only` | historical_replay | false | -67.64 |
| watch | `position_hard_stop_distribution` | main | `shadow_watch` | diagnostic | false | -29.59 |
| watch | `stale_leader_trim` | main | `shadow_watch` | diagnostic | false | -29.59 |
| watch | `shakeout_hold_veto` | main | `shadow_watch` | diagnostic | false | -29.59 |
| watch | `long_winner_hold_template` | main | `shadow_watch` | diagnostic | false | -29.59 |
| watch | `governance_catalyst_watch` | main | `shadow_watch` | diagnostic | false | -29.59 |

## Policy Evidence

| Policy | Portfolio | CAGR | MaxDD | Sharpe | Delta CAGR | Delta MaxDD | Stage | Source |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `position_hard_stop_distribution` | main | 19.85% | -32.13% | 0.916 | 0.00pp | 0.00pp | `shadow_watch` | outputs/historical_trade_journey/historical_decision_priorities.csv |
| `position_hard_stop_distribution` | concentrated | 24.81% | -34.92% | 0.971 | -7.84pp | -6.07pp | `reject_current_form` | sidecar:outputs/broker_position_risk_replay/concentrated/metrics.json |
| `macro_crisis_cash_ladder` | main | 32.72% | -14.09% | 1.897 | 12.87pp | 18.03pp | `confirm_with_production_compatible_replay` | outputs/crisis_reentry_replay/metrics.json#best_by_cagr |
| `stale_leader_trim` | main | 19.85% | -32.13% | 0.916 | 0.00pp | 0.00pp | `shadow_watch` | outputs/historical_trade_journey/historical_decision_priorities.csv |
| `shakeout_hold_veto` | main | 19.85% | -32.13% | 0.916 | 0.00pp | 0.00pp | `shadow_watch` | outputs/shakeout_breakdown_study/pattern_summary.json |
| `monster_early_staged_sizing` | main | 15.55% | -25.04% | 0.885 | -4.31pp | 7.09pp | `conditional_defense_only` | sidecar:outputs/monster_lifecycle_review_main/metrics.json |
| `monster_early_staged_sizing` | concentrated | 18.83% | -25.23% | 1.025 | -13.82pp | 3.62pp | `conditional_defense_only` | sidecar:outputs/monster_lifecycle_review_concentrated/metrics.json |
| `long_winner_hold_template` | main | 19.85% | -32.13% | 0.916 | 0.00pp | 0.00pp | `shadow_watch` | outputs/historical_trade_journey/historical_decision_priorities.csv |
| `idle_cash_redeploy` | main | 37.55% | -14.45% | 1.871 | 17.70pp | 17.68pp | `confirm_with_production_compatible_replay` | outputs/main_cash_drag_replay/summary.json#best_by_cagr |
| `style_macro_router` | main | 21.31% | -27.19% | 1.001 | 1.45pp | 4.94pp | `candidate_for_combination` | sidecar:outputs/main_v2_backtest/metrics.json |
| `style_macro_router` | concentrated | 14.04% | -47.93% | 0.584 | -18.60pp | -19.08pp | `reject_current_form` | sidecar:outputs/concentrated_policy_replay/metrics.json |
| `governance_catalyst_watch` | main | 19.85% | -32.13% | 0.916 | 0.00pp | 0.00pp | `shadow_watch` | outputs/governance_catalyst/summary.json |
| `auto_learning_policy_candidate` | main | 19.85% | -32.13% | 0.916 | 0.00pp | 0.00pp | `shadow_watch` | outputs/autolearning_winner_challenger/summary.json |
| `account_aware_execution` | concentrated | 39.56% | -28.69% | 1.215 | 6.91pp | 0.16pp | `candidate_for_combination` | sidecar:outputs/broker_execution_policy_replay/concentrated/metrics.json |
| `account_aware_execution` | main | 20.08% | -31.66% | 0.882 | 0.23pp | 0.47pp | `candidate_for_combination` | sidecar:outputs/broker_execution_policy_replay/main/metrics.json |

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
