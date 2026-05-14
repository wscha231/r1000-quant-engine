# Portfolio System Guard

Fast integrated check from existing artifacts. Production defaults are not changed.

## Target Status

| Portfolio | CAGR | Target | Gap | MaxDD | Target | DD improvement needed | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 23.10% | 30.00% | 6.90pp | -29.98% | -15.00% | 14.98pp | false |
| concentrated | 33.00% | 50.00% | 17.00pp | -41.82% | -18.00% | 23.82pp | false |

Metric sources:
- `main`: `broker_ledger_next_close`
- `concentrated`: `broker_ledger_next_close`

Strict target mode: `false`

## Candidate Priority

| Experiment | Status | Discovery | Needs replay | CAGR delta pp | MaxDD delta pp |
| --- | --- | ---: | ---: | ---: | ---: |
| E4_concentrated_balanced | `standalone_sleeve_policy_audit` | true | true | 13.45 | 4.33 |
| E6_risk_sensing_on | `simplified_layer2_backtest` | true | false | -2.94 | 5.65 |
| E4_concentrated_balanced_replay | `completed` | true | false |  |  |
| E2_main_v2_balanced | `snapshot_report_only` | false | true | 0.00 | 0.00 |
| E3_main_v2_aggressive | `snapshot_report_only` | false | true | 0.00 | 0.00 |
| E5_orchestrator_balanced | `snapshot_report_only` | false | true | 0.00 | 0.00 |

## Goal Search

| Portfolio | Best candidate | CAGR | Gap | MaxDD | Gap | Target Pass | Action |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| main | `main_v2_position_aware_risk_proxy` | 36.13% | 0.00pp | -12.68% | 0.00pp | true | `target_pass_review` |
| concentrated | `concentrated_position_risk_proxy` | 50.59% | 0.00pp | -17.99% | 0.00pp | true | `target_pass_review` |

## Error Checks

- `PASS` main_metrics_available: outputs/backtest_metrics.json
- `PASS` concentrated_metrics_available: outputs/concentrated_backtest_metrics.json
- `PASS` experiment_matrix_available: outputs/experiments/experiment_matrix_summary.json
- `PASS` auto_learning_v2_challenger_available: outputs/auto_learning_v2/challenger_review.json
- `PASS` auto_learning_v2_policy_available: outputs/auto_learning_v2/policy_candidate.json
- `PASS` orchestrator_replay_available: outputs/orchestrator_replay/concentrated_balanced/metrics.json
- `PASS` portfolio_goal_search_available: outputs/portfolio_goal_search/goal_search_summary.json
- `PASS` account_evaluation_available: outputs/account_evaluation/account_evaluation_summary.json
- `PASS` github_workflows_available: .github/workflows
- `WARN` counterfactual_replay_coverage: missing_counterfactual_count=2
- `WARN` candidate_production_ready: production_ready_count=0
- `PASS` operating_event_backtest_available: outputs/operating_event_backtest/operating_event_backtest_summary.json
- `PASS` daily_risk_overlay_backtest_validated: daily_risk_overlay_validated=True; nonmonthly_risk_action_count=743
- `WARN` full_nonmonthly_entry_replacement_backtest_validated: full_nonmonthly_entry_replacement_validated=False; daily_risk_action_evidence_count=743
- `PASS` orchestrator_replay_valid_for_promotion: status=completed; data_mode=historical_concentrated_monthly
- `PASS` main_target_book_reaches_broker_end: selected_role=operating_target_book; target_book_max=2026-05-13; broker_end=2026-05-13; rows=2140; path=/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/operating_main_target_book.csv
- `PASS` main_operating_target_book_available: operating_book=/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/operating_main_target_book.csv; rows=2140; max_date=2026-05-13
- `WARN` main_historical_research_book_reaches_broker_end: historical_book_max=2026-02-27; broker_end=2026-05-13; rows=2123; operating_book_max=2026-05-13; operating_rows=2140
- `PASS` main_broker_replay_uses_operating_target_book: metric_target_book=/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/operating_main_target_book.csv
- `PASS` concentrated_target_book_reaches_broker_end: selected_role=operating_target_book; target_book_max=2026-05-13; broker_end=2026-05-13; rows=23457; path=/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/operating_concentrated_target_book.csv
- `PASS` concentrated_operating_target_book_available: operating_book=/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/operating_concentrated_target_book.csv; rows=23457; max_date=2026-05-13
- `WARN` concentrated_historical_research_book_reaches_broker_end: historical_book_max=2026-02-27; broker_end=2026-05-13; rows=23454; operating_book_max=2026-05-13; operating_rows=23457
- `PASS` concentrated_broker_replay_uses_operating_target_book: metric_target_book=/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/operating_concentrated_target_book.csv
- `PASS` current_only_operating_holdings_available: /home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/operating_snapshot/current_operating_holdings_latest.csv; rows=23; legacy_snapshot_exists=True
- `PASS` main_current_position_count_near_latest_target_count: main_positions=18; latest_target_rows=17; excess=1
- `PASS` concentrated_replay_filter_matches_latest_target: broker_filter_n=3; latest_target_n=3; broker_mode=winner_take_all; latest_mode=winner_take_all

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
