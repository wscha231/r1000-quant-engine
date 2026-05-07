# Portfolio System Guard

Fast integrated check from existing artifacts. Production defaults are not changed.

## Target Status

| Portfolio | CAGR | Target | Gap | MaxDD | Target | DD improvement needed | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 21.40% | 25.00% | 3.60pp | -27.27% | -20.00% | 7.27pp | false |
| concentrated | 34.85% | 40.00% | 5.15pp | -22.94% | -22.00% | 0.94pp | false |

Strict target mode: `false`

## Candidate Priority

| Experiment | Status | Discovery | Needs replay | CAGR delta pp | MaxDD delta pp |
| --- | --- | ---: | ---: | ---: | ---: |
| E4_concentrated_balanced | `standalone_sleeve_policy_audit` | true | true | 13.45 | 4.33 |
| E6_risk_sensing_on | `simplified_layer2_backtest` | true | false | -2.94 | 5.65 |
| E4_concentrated_balanced_replay | `blocked_missing_concentrated_monthly` | false | true |  |  |
| E2_main_v2_balanced | `snapshot_report_only` | false | true | 0.00 | 0.00 |
| E3_main_v2_aggressive | `snapshot_report_only` | false | true | 0.00 | 0.00 |
| E5_orchestrator_balanced | `snapshot_report_only` | false | true | 0.00 | 0.00 |

## Goal Search

| Portfolio | Best candidate | CAGR | Gap | MaxDD | Gap | Target Pass | Action |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| main | `experiment_E6_risk_sensing_on` | 18.47% | 6.53pp | -21.63% | 1.63pp | false | `blocked_both` |
| concentrated | `concentrated_latest_champion` | 34.85% | 5.15pp | -22.94% | 0.94pp | false | `blocked_both` |

## Error Checks

- `PASS` main_metrics_available: cloud_results/full_rebuild/latest_global_alpha_universe/backtest_metrics.json
- `PASS` concentrated_metrics_available: cloud_results/full_rebuild/latest_global_alpha_universe/concentrated_backtest_metrics.json
- `PASS` experiment_matrix_available: outputs/experiments/experiment_matrix_summary.json
- `PASS` auto_learning_v2_challenger_available: outputs/auto_learning_v2/challenger_review.json
- `PASS` auto_learning_v2_policy_available: outputs/auto_learning_v2/policy_candidate.json
- `PASS` orchestrator_replay_available: outputs/orchestrator_replay/concentrated_balanced/metrics.json
- `PASS` portfolio_goal_search_available: outputs/portfolio_goal_search/goal_search_summary.json
- `PASS` github_workflows_available: .github/workflows
- `WARN` counterfactual_replay_coverage: missing_counterfactual_count=4
- `WARN` candidate_production_ready: production_ready_count=0
- `WARN` orchestrator_replay_valid_for_promotion: status=blocked_missing_concentrated_monthly; data_mode=proxy_top_raw_score_within_main_holdings

## Automation Plan

- Fast guard: Fast PR/manual target gap, artifact, error, and promotion-blocker check from committed data.
- Data refresh: Refresh Finnhub/theme substrate before deeper rebuilds.
- Full rebuild: Manual long-run only; use skip_collector=true and fast_mode=true when cached data exists.
- Aggressive lab: Discovery experiments; failures are retained as research artifacts.
- AutoLearning: Feature gates plus Alpha Scientist hypotheses. Proposal-only by default.

## Next Focus

- Concentrated full orchestrator replay at 20-30% capacity with caps.
- Main v2 historical replay with target N 12/15 and future_winner-heavy sleeve allocation.
- Risk sensing Layer 1/3/4 position-aware exits to keep MaxDD improvement without CAGR drag.
- Alpha Sprint bull-only replay using breakout/RS/catalyst fallback because explosion_* is dormant.
