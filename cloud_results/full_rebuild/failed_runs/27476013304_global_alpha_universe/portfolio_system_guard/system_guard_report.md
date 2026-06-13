# Portfolio System Guard

Fast integrated check from existing artifacts. Production defaults are not changed.

## Target Status

| Portfolio | CAGR | Target | Gap | MaxDD | Target | DD improvement needed | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 22.40% | 35.00% | 12.60pp | -31.66% | -25.00% | 6.66pp | false |
| concentrated | 30.79% | 50.00% | 19.21pp | -37.90% | -25.00% | 12.90pp | false |

Metric sources:
- `main`: `broker_ledger_next_close`
- `concentrated`: `broker_ledger_next_close`

Strict target mode: `false`

## Cash Trap Guard

- `main`: severity=`ok`, avg_cash=5.98%, latest_cash=26.73%, reasons=none
- `concentrated`: severity=`ok`, avg_cash=0.05%, latest_cash=0.00%, reasons=none

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
| main | `main_rebalance_interval_fixed_interval_I1` | 33.04% | 1.96pp | -15.63% | 0.00pp | false | `needs_alpha_boost` |
| concentrated | `concentrated_grid_N3_score_power_I1` | 43.28% | 6.72pp | -24.87% | 0.00pp | false | `needs_alpha_boost` |

## Error Checks

- `PASS` main_metrics_available: outputs/broker_replay/main/metrics.json
- `PASS` concentrated_metrics_available: outputs/broker_replay/concentrated/metrics.json
- `PASS` experiment_matrix_available: outputs/experiments/experiment_matrix_summary.json
- `PASS` auto_learning_v2_challenger_available: outputs/auto_learning_v2/challenger_review.json
- `PASS` auto_learning_v2_policy_available: outputs/auto_learning_v2/policy_candidate.json
- `PASS` orchestrator_replay_available: outputs/orchestrator_replay/concentrated_balanced/metrics.json
- `PASS` portfolio_goal_search_available: outputs/portfolio_goal_search/goal_search_summary.json
- `PASS` account_evaluation_available: outputs/account_evaluation/account_evaluation_summary.json
- `PASS` github_workflows_available: .github/workflows
- `WARN` counterfactual_replay_coverage: missing_counterfactual_count=4
- `WARN` candidate_production_ready: production_ready_count=0
- `WARN` operating_event_backtest_available: outputs/operating_event_backtest/operating_event_backtest_summary.json
- `PASS` data_readiness_audit_available: outputs/data_readiness/summary.json
- `PASS` data_readiness_ready_for_production_replay: status=warn; ready_for_fullrun=True; ready_for_policy_replay=False; blockers=[]; policy_replay_blockers=['SEC evidence store exists but operating target books are missing sec_smart_money feature columns']; warnings=['dated target snapshot archive is missing for this run', 'operating target books are missing sec_smart_money feature columns for portfolios: main']
- `PASS` dataset_coverage_audit_available: outputs/reports/dataset_coverage_audit.json
- `PASS` sec_enriched_candidate_materialized_for_audit: sec_enriched_candidate_present=False; rows_with_smart_money_evidence=0
- `WARN` orchestrator_replay_valid_for_promotion: status=blocked_missing_concentrated_monthly; data_mode=proxy_top_raw_score_within_main_holdings
- `PASS` main_target_book_reaches_broker_end: selected_role=operating_target_book; target_book_max=2026-06-12; broker_end=2026-06-12; date_gap_days=0; allowed_lag_days=7; rows=1805; path=/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/operating_main_target_book.csv
- `PASS` main_operating_target_book_available: operating_book=/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/operating_main_target_book.csv; rows=1805; max_date=2026-06-12
- `WARN` main_historical_research_book_reaches_broker_end: historical_book_max=2026-03-31; broker_end=2026-06-12; rows=1787; operating_book_max=2026-06-12; operating_rows=1805
- `PASS` main_broker_replay_uses_operating_target_book: metric_target_book=/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/operating_main_target_book.csv
- `PASS` concentrated_target_book_reaches_broker_end: selected_role=operating_target_book; target_book_max=2026-06-12; broker_end=2026-06-12; date_gap_days=0; allowed_lag_days=7; rows=23176; path=/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/operating_concentrated_target_book.csv
- `PASS` concentrated_operating_target_book_available: operating_book=/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/operating_concentrated_target_book.csv; rows=23176; max_date=2026-06-12
- `WARN` concentrated_historical_research_book_reaches_broker_end: historical_book_max=2026-03-31; broker_end=2026-06-12; rows=23172; operating_book_max=2026-06-12; operating_rows=23176
- `PASS` concentrated_broker_replay_uses_operating_target_book: metric_target_book=/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/operating_concentrated_target_book.csv
- `PASS` current_only_operating_holdings_available: /home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/operating_snapshot/current_operating_holdings_latest.csv; rows=23; legacy_snapshot_exists=True
- `PASS` main_current_position_count_near_latest_target_count: main_positions=17; latest_target_rows=18; excess=0
- `PASS` concentrated_replay_filter_matches_latest_target: broker_filter_n=4; latest_operating_target_n=4; broker_mode=score_power; latest_mode=score_power
- `PASS` main_official_broker_metrics_valid_for_production: metric_source=broker_ledger_next_close; valid_for_production=True; fill_mode=next_close
- `PASS` concentrated_official_broker_metrics_valid_for_production: metric_source=broker_ledger_next_close; valid_for_production=True; fill_mode=next_close
- `PASS` sec_drive_restore_manifest_available: restored_count=5; missing=[]; errors=[]
- `WARN` theme_leadership_tape_available: top_theme=missing; top_theme_state=missing
- `WARN` macro_circuit_diagnostics_available: main_status=missing; concentrated_status=missing
- `PASS` feature_source_coverage_available: outputs/data_readiness/summary.json::feature_source_coverage
- `PASS` feature_source_coverage_pit_available_from_clean: pit_future_available_from_rows=0; available_from_column_count=0
- `WARN` feature_source_groups_present_for_target_books: missing_groups=['main:quality_confirmation', 'main:sec_smart_money', 'main:theme_leadership']
- `PASS` main_cash_position_count_contract: latest_date=2026-06-12; cash=0.00%; stock_count=18; crisis_state=unknown; violations=[]; preexisting_in_baseline=[]
- `ERROR` concentrated_concentration_contract: latest_date=2026-06-12; max_name=AMD@31.99%; max_industry_group=Semiconductors@83.82%; group_source=industry_group; violations=['concentrated_industry_group_weight_gt_60pct']; preexisting_in_baseline=[]

## Data Quality Update Plan

- Readiness: ready_for_fullrun=`true`, ready_for_policy_replay=`false`, blockers=[], policy_blockers=['SEC evidence store exists but operating target books are missing sec_smart_money feature columns']
- Coverage: sec_enriched_candidate_present=`false`, smart_money_rows=0, candidate_book=`missing`
- Large data restore: manifest_available=`true`, restored=['outputs/sec_institutional_signals', 'outputs/sec_ownership_signals', 'data_pit/sec', 'outputs/etf_thematic_signals', 'data_pit/etf_holdings'], missing=[], errors=[]
- PIT rules:
  - Every external evidence row must have available_from or latest_available_from before it can boost scoring.
  - SEC 13F must use public filing accepted/available time, never report_period as availability.
  - Macro release-lagged series must preserve publication lag and must not be backfilled into earlier rebalance dates.
  - ETF holdings are latest/discovery aids unless a point-in-time holding snapshot exists.
  - Missing evidence is neutral: no boost, no standalone penalty, and no buy rule.
- Next data work:
  - Add a full-period feature-store coverage report by month, source, and portfolio target book.
  - Track universe membership, delistings, ADR eligibility, and symbol changes as monthly PIT snapshots.
  - Add macro regime features for QQQ-vs-SPY damage, credit/rate/liquidity stress, breadth, and theme rotation before changing production sizing.
  - Run broker-trade attribution first, then promote only PIT-safe rules that improve official broker MDD without losing target CAGR.

## Automation Plan

- Fast guard: Fast PR/manual target gap, artifact, error, and promotion-blocker check from committed data.
- Data refresh: Refresh substrate data, PIT freshness, universe, theme, and coverage diagnostics before deeper rebuilds.
- Full rebuild: Manual long-run only; use skip_collector=true and fast_mode=true when cached data exists.
- Aggressive lab: Discovery experiments; failures are retained as research artifacts.
- AutoLearning: Feature gates plus Alpha Scientist hypotheses. Proposal-only by default.

## Next Focus

- Run data quality and PIT coverage checks before interpreting CAGR/MDD.
- Use broker-trade attribution to separate data gaps from policy errors across the full period.
- Improve theme leadership and macro regime features before adding broad cash or sizing rules.
- Promote only reversible PIT-safe rules that improve official broker MDD without losing target CAGR.
