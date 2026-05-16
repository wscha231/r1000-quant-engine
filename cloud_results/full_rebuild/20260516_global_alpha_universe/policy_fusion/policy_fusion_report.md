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
| high | `idle_cash_redeploy` | main | `candidate_for_combination` | monthly_proxy | false | 27.04 |
| high | `macro_crisis_cash_ladder` | main | `candidate_for_combination` | monthly_proxy | false | 17.37 |
| high | `long_winner_hold_template` | main | `candidate_for_combination` | historical_replay | false | -8.25 |
| high | `monster_early_staged_sizing` | main | `candidate_for_combination` | historical_replay | false | -10.60 |
| high | `style_macro_router` | main | `candidate_for_combination` | historical_replay | false | -20.25 |
| high | `style_macro_router` | concentrated | `candidate_for_combination` | historical_replay | false | -28.29 |
| high | `monster_early_staged_sizing` | concentrated | `conditional_defense_only` | historical_replay | false | -31.86 |
| high | `position_hard_stop_distribution` | concentrated | `conditional_defense_only` | production | false | -59.84 |
| watch | `account_aware_execution` | main | `shadow_watch` | production | false | -32.81 |
| watch | `position_hard_stop_distribution` | main | `shadow_watch` | diagnostic | false | -33.43 |
| watch | `stale_leader_trim` | main | `shadow_watch` | diagnostic | false | -33.43 |
| watch | `shakeout_hold_veto` | main | `shadow_watch` | diagnostic | false | -33.43 |

## Policy Evidence

| Policy | Portfolio | CAGR | MaxDD | Sharpe | Delta CAGR | Delta MaxDD | Stage | Source |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `position_hard_stop_distribution` | main | 12.86% | -27.07% | 0.635 | 0.00pp | 0.00pp | `shadow_watch` | outputs/historical_trade_journey/historical_decision_priorities.csv |
| `position_hard_stop_distribution` | concentrated | 12.19% | -30.33% | 0.594 | -4.70pp | 3.48pp | `conditional_defense_only` | sidecar:outputs/broker_position_risk_replay/concentrated/metrics.json |
| `macro_crisis_cash_ladder` | main | 21.99% | -13.02% | 1.700 | 9.12pp | 14.06pp | `candidate_for_combination` | outputs/crisis_reentry_replay/metrics.json#best_by_cagr |
| `stale_leader_trim` | main | 12.86% | -27.07% | 0.635 | 0.00pp | 0.00pp | `shadow_watch` | outputs/historical_trade_journey/historical_decision_priorities.csv |
| `shakeout_hold_veto` | main | 12.86% | -27.07% | 0.635 | 0.00pp | 0.00pp | `shadow_watch` | outputs/shakeout_breakdown_study/pattern_summary.json |
| `monster_early_staged_sizing` | main | 15.02% | -20.75% | 0.999 | 2.16pp | 6.32pp | `candidate_for_combination` | sidecar:outputs/monster_lifecycle_review_main/metrics.json |
| `monster_early_staged_sizing` | concentrated | 15.31% | -20.89% | 1.056 | -1.58pp | 12.92pp | `conditional_defense_only` | sidecar:outputs/monster_lifecycle_review_concentrated/metrics.json |
| `long_winner_hold_template` | main | 15.01% | -19.52% | 0.968 | 2.14pp | 7.55pp | `candidate_for_combination` | sidecar:outputs/lifecycle_review_overlay_main/metrics.json |
| `idle_cash_redeploy` | main | 25.87% | -14.08% | 1.662 | 13.01pp | 12.99pp | `candidate_for_combination` | outputs/main_cash_drag_replay/summary.json#best_by_cagr |
| `style_macro_router` | main | 14.62% | -24.61% | 0.817 | 1.76pp | 2.46pp | `candidate_for_combination` | sidecar:outputs/main_v2_backtest/metrics.json |
| `style_macro_router` | concentrated | 23.04% | -31.27% | 0.989 | 6.15pp | 2.54pp | `candidate_for_combination` | sidecar:outputs/concentrated_policy_replay/metrics.json |
| `governance_catalyst_watch` | main | 12.86% | -27.07% | 0.635 | 0.00pp | 0.00pp | `shadow_watch` | outputs/governance_catalyst/summary.json |
| `auto_learning_policy_candidate` | main | 12.86% | -27.07% | 0.635 | 0.00pp | 0.00pp | `shadow_watch` | outputs/autolearning_winner_challenger/summary.json |
| `account_aware_execution` | main | 13.00% | -29.61% | 0.622 | 0.14pp | -2.54pp | `shadow_watch` | sidecar:outputs/broker_execution_policy_replay/main/metrics.json |
| `account_aware_execution` | concentrated | 16.56% | -31.49% | 0.715 | -0.33pp | 2.31pp | `shadow_watch` | sidecar:outputs/broker_execution_policy_replay/concentrated/metrics.json |

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
