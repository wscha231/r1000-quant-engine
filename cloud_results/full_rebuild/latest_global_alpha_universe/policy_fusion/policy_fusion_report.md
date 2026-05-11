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
| highest | `idle_cash_redeploy` | main | `confirm_with_production_compatible_replay` | monthly_proxy | true | 80.22 |
| highest | `macro_crisis_cash_ladder` | main | `confirm_with_production_compatible_replay` | monthly_proxy | true | 72.86 |
| high | `style_macro_router` | main | `candidate_for_combination` | historical_replay | false | -15.03 |
| high | `monster_early_staged_sizing` | concentrated | `conditional_defense_only` | historical_replay | false | -72.91 |
| watch | `position_hard_stop_distribution` | main | `shadow_watch` | diagnostic | false | -27.71 |
| watch | `stale_leader_trim` | main | `shadow_watch` | diagnostic | false | -27.71 |
| watch | `shakeout_hold_veto` | main | `shadow_watch` | diagnostic | false | -27.71 |
| watch | `monster_early_staged_sizing` | main | `shadow_watch` | diagnostic | false | -27.71 |
| watch | `long_winner_hold_template` | main | `shadow_watch` | diagnostic | false | -27.71 |
| watch | `governance_catalyst_watch` | main | `shadow_watch` | diagnostic | false | -27.71 |
| watch | `auto_learning_policy_candidate` | main | `shadow_watch` | proposal | false | -27.71 |
| watch | `account_aware_execution` | concentrated | `shadow_watch` | production | false | -78.07 |

## Policy Evidence

| Policy | Portfolio | CAGR | MaxDD | Sharpe | Delta CAGR | Delta MaxDD | Stage | Source |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `position_hard_stop_distribution` | main | 21.09% | -31.69% | 1.003 | 0.00pp | 0.00pp | `shadow_watch` | outputs/historical_trade_journey/historical_decision_priorities.csv |
| `position_hard_stop_distribution` | concentrated | 17.00% | -47.76% | 0.757 | -14.31pp | -8.53pp | `reject_current_form` | sidecar:outputs/broker_position_risk_replay/concentrated/metrics.json |
| `macro_crisis_cash_ladder` | main | 31.35% | -12.62% | 1.973 | 10.26pp | 19.07pp | `confirm_with_production_compatible_replay` | outputs/crisis_reentry_replay/metrics.json#best_by_cagr |
| `stale_leader_trim` | main | 21.09% | -31.69% | 1.003 | 0.00pp | 0.00pp | `shadow_watch` | outputs/historical_trade_journey/historical_decision_priorities.csv |
| `shakeout_hold_veto` | main | 21.09% | -31.69% | 1.003 | 0.00pp | 0.00pp | `shadow_watch` | outputs/shakeout_breakdown_study/pattern_summary.json |
| `monster_early_staged_sizing` | main | 21.09% | -31.69% | 1.003 | 0.00pp | 0.00pp | `shadow_watch` | outputs/winner_onset_study/pattern_summary.json |
| `monster_early_staged_sizing` | concentrated | 13.79% | -26.71% | 0.863 | -17.52pp | 12.52pp | `conditional_defense_only` | sidecar:outputs/monster_lifecycle_review_concentrated/metrics.json |
| `long_winner_hold_template` | main | 21.09% | -31.69% | 1.003 | 0.00pp | 0.00pp | `shadow_watch` | outputs/historical_trade_journey/historical_decision_priorities.csv |
| `idle_cash_redeploy` | main | 36.37% | -12.88% | 1.898 | 15.28pp | 18.80pp | `confirm_with_production_compatible_replay` | outputs/main_cash_drag_replay/summary.json#best_by_cagr |
| `style_macro_router` | main | 21.61% | -27.22% | 1.007 | 0.51pp | 4.47pp | `candidate_for_combination` | sidecar:outputs/main_v2_backtest/metrics.json |
| `style_macro_router` | concentrated | 12.43% | -47.85% | 0.541 | -18.88pp | -8.62pp | `reject_current_form` | sidecar:outputs/concentrated_policy_replay/metrics.json |
| `governance_catalyst_watch` | main | 21.09% | -31.69% | 1.003 | 0.00pp | 0.00pp | `shadow_watch` | outputs/governance_catalyst/summary.json |
| `auto_learning_policy_candidate` | main | 21.09% | -31.69% | 1.003 | 0.00pp | 0.00pp | `shadow_watch` | outputs/autolearning_winner_challenger/summary.json |
| `account_aware_execution` | main | 19.88% | -35.76% | 0.919 | -1.22pp | -4.07pp | `reject_current_form` | sidecar:outputs/broker_execution_policy_replay/main/metrics.json |
| `account_aware_execution` | concentrated | 20.23% | -38.58% | 0.790 | -11.07pp | 0.65pp | `shadow_watch` | sidecar:outputs/broker_execution_policy_replay/concentrated/metrics.json |

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
