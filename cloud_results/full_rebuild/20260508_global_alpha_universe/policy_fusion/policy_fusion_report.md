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
| highest | `position_hard_stop_distribution` | concentrated | `confirm_with_production_compatible_replay` | weekly_validation | true | 320679943879700546322432.00 |
| highest | `idle_cash_redeploy` | main | `confirm_with_production_compatible_replay` | monthly_proxy | true | 49.71 |
| high | `macro_crisis_cash_ladder` | main | `candidate_for_combination` | monthly_proxy | false | 1.74 |
| watch | `position_hard_stop_distribution` | main | `shadow_watch` | diagnostic | false | -5.09 |
| watch | `stale_leader_trim` | main | `shadow_watch` | diagnostic | false | -5.09 |
| watch | `shakeout_hold_veto` | main | `shadow_watch` | diagnostic | false | -5.09 |
| watch | `monster_early_staged_sizing` | main | `shadow_watch` | diagnostic | false | -5.09 |
| watch | `long_winner_hold_template` | main | `shadow_watch` | diagnostic | false | -5.09 |
| watch | `style_macro_router` | main | `shadow_watch` | diagnostic | false | -5.09 |
| watch | `governance_catalyst_watch` | main | `shadow_watch` | diagnostic | false | -5.09 |
| watch | `auto_learning_policy_candidate` | main | `shadow_watch` | proposal | false | -5.09 |
| blocked | `monster_early_staged_sizing` | concentrated | `reject_current_form` | historical_replay | false | -128.75 |

## Policy Evidence

| Policy | Portfolio | CAGR | MaxDD | Sharpe | Delta CAGR | Delta MaxDD | Stage | Source |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `position_hard_stop_distribution` | concentrated | 168778917831421347233792.00% | 0.00% | 31.177 | 168778917831421347233792.00pp | 19.72pp | `confirm_with_production_compatible_replay` | sidecar:outputs/position_risk_weekly_validation/concentrated/metrics.json |
| `position_hard_stop_distribution` | main | 28.12% | -15.92% | 1.620 | 0.00pp | 0.00pp | `shadow_watch` | outputs/historical_trade_journey/historical_decision_priorities.csv |
| `macro_crisis_cash_ladder` | main | 29.04% | -12.64% | 1.866 | 0.93pp | 3.28pp | `candidate_for_combination` | outputs/crisis_reentry_replay/metrics.json#best_by_cagr |
| `stale_leader_trim` | main | 28.12% | -15.92% | 1.620 | 0.00pp | 0.00pp | `shadow_watch` | outputs/historical_trade_journey/historical_decision_priorities.csv |
| `shakeout_hold_veto` | main | 28.12% | -15.92% | 1.620 | 0.00pp | 0.00pp | `shadow_watch` | outputs/shakeout_breakdown_study/pattern_summary.json |
| `monster_early_staged_sizing` | main | 28.12% | -15.92% | 1.620 | 0.00pp | 0.00pp | `shadow_watch` | outputs/winner_onset_study/pattern_summary.json |
| `monster_early_staged_sizing` | concentrated | 14.11% | -26.71% | 0.868 | -33.59pp | -6.99pp | `reject_current_form` | sidecar:outputs/monster_lifecycle_review_concentrated/metrics.json |
| `long_winner_hold_template` | main | 28.12% | -15.92% | 1.620 | 0.00pp | 0.00pp | `shadow_watch` | outputs/historical_trade_journey/historical_decision_priorities.csv |
| `idle_cash_redeploy` | main | 33.94% | -13.36% | 1.807 | 5.82pp | 2.57pp | `confirm_with_production_compatible_replay` | outputs/main_cash_drag_replay/summary.json#best_by_cagr |
| `style_macro_router` | main | 28.12% | -15.92% | 1.620 | 0.00pp | 0.00pp | `shadow_watch` | outputs/macro_policy_engine/summary.json |
| `style_macro_router` | concentrated | 15.84% | -47.88% | 0.636 | -31.87pp | -28.16pp | `reject_current_form` | sidecar:outputs/concentrated_policy_replay/metrics.json |
| `governance_catalyst_watch` | main | 28.12% | -15.92% | 1.620 | 0.00pp | 0.00pp | `shadow_watch` | outputs/governance_catalyst/summary.json |
| `auto_learning_policy_candidate` | main | 28.12% | -15.92% | 1.620 | 0.00pp | 0.00pp | `shadow_watch` | outputs/autolearning_winner_challenger/summary.json |

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
