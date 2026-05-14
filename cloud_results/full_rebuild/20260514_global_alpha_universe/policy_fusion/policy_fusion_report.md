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
| highest | `idle_cash_redeploy` | main | `confirm_with_production_compatible_replay` | monthly_proxy | true | 72.85 |
| highest | `macro_crisis_cash_ladder` | main | `confirm_with_production_compatible_replay` | monthly_proxy | true | 66.46 |
| high | `monster_early_staged_sizing` | concentrated | `conditional_defense_only` | historical_replay | false | -70.55 |
| watch | `long_winner_hold_template` | main | `shadow_watch` | historical_replay | false | -12.47 |
| watch | `style_macro_router` | main | `shadow_watch` | historical_replay | false | -23.35 |
| watch | `position_hard_stop_distribution` | main | `shadow_watch` | diagnostic | false | -23.77 |
| watch | `stale_leader_trim` | main | `shadow_watch` | diagnostic | false | -23.77 |
| watch | `shakeout_hold_veto` | main | `shadow_watch` | diagnostic | false | -23.77 |
| watch | `monster_early_staged_sizing` | main | `shadow_watch` | diagnostic | false | -23.77 |
| watch | `governance_catalyst_watch` | main | `shadow_watch` | diagnostic | false | -23.77 |
| watch | `auto_learning_policy_candidate` | main | `shadow_watch` | proposal | false | -23.77 |
| watch | `account_aware_execution` | concentrated | `shadow_watch` | production | false | -66.71 |

## Policy Evidence

| Policy | Portfolio | CAGR | MaxDD | Sharpe | Delta CAGR | Delta MaxDD | Stage | Source |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `position_hard_stop_distribution` | main | 23.10% | -29.98% | 1.090 | 0.00pp | 0.00pp | `shadow_watch` | outputs/historical_trade_journey/historical_decision_priorities.csv |
| `position_hard_stop_distribution` | concentrated | 20.29% | -52.47% | 0.856 | -12.71pp | -10.65pp | `reject_current_form` | sidecar:outputs/broker_position_risk_replay/concentrated/metrics.json |
| `macro_crisis_cash_ladder` | main | 31.31% | -14.15% | 1.887 | 8.22pp | 15.83pp | `confirm_with_production_compatible_replay` | outputs/crisis_reentry_replay/metrics.json#best_by_cagr |
| `stale_leader_trim` | main | 23.10% | -29.98% | 1.090 | 0.00pp | 0.00pp | `shadow_watch` | outputs/historical_trade_journey/historical_decision_priorities.csv |
| `shakeout_hold_veto` | main | 23.10% | -29.98% | 1.090 | 0.00pp | 0.00pp | `shadow_watch` | outputs/shakeout_breakdown_study/pattern_summary.json |
| `monster_early_staged_sizing` | main | 23.10% | -29.98% | 1.090 | 0.00pp | 0.00pp | `shadow_watch` | outputs/winner_onset_study/pattern_summary.json |
| `monster_early_staged_sizing` | concentrated | 14.69% | -26.71% | 0.894 | -18.31pp | 15.11pp | `conditional_defense_only` | sidecar:outputs/monster_lifecycle_review_concentrated/metrics.json |
| `long_winner_hold_template` | main | 26.65% | -31.27% | 1.258 | 3.55pp | -1.29pp | `shadow_watch` | sidecar:outputs/lifecycle_review_overlay_main/metrics.json |
| `idle_cash_redeploy` | main | 35.88% | -14.82% | 1.846 | 12.78pp | 15.16pp | `confirm_with_production_compatible_replay` | outputs/main_cash_drag_replay/summary.json#best_by_cagr |
| `style_macro_router` | main | 20.92% | -27.18% | 0.999 | -2.17pp | 2.80pp | `shadow_watch` | sidecar:outputs/main_v2_backtest/metrics.json |
| `style_macro_router` | concentrated | 12.43% | -41.38% | 0.577 | -20.57pp | 0.43pp | `shadow_watch` | sidecar:outputs/concentrated_policy_replay/metrics.json |
| `governance_catalyst_watch` | main | 23.10% | -29.98% | 1.090 | 0.00pp | 0.00pp | `shadow_watch` | outputs/governance_catalyst/summary.json |
| `auto_learning_policy_candidate` | main | 23.10% | -29.98% | 1.090 | 0.00pp | 0.00pp | `shadow_watch` | outputs/autolearning_winner_challenger/summary.json |
| `account_aware_execution` | main | 21.61% | -33.95% | 0.998 | -1.48pp | -3.96pp | `reject_current_form` | sidecar:outputs/broker_execution_policy_replay/main/metrics.json |
| `account_aware_execution` | concentrated | 23.59% | -38.85% | 0.867 | -9.40pp | 2.97pp | `shadow_watch` | sidecar:outputs/broker_execution_policy_replay/concentrated/metrics.json |

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
