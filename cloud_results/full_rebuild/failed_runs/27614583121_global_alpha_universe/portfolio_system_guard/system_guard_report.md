# Portfolio System Guard

Fast integrated check from existing artifacts. Production defaults are not changed.

## Target Status

| Portfolio | CAGR | Target | Gap | MaxDD | Target | DD improvement needed | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 35.01% | 30.00% | 0.00pp | -26.05% | -25.00% | 1.05pp | false |
| concentrated | 45.00% | 50.00% | 5.00pp | -25.82% | -28.00% | 0.00pp | false |

Metric sources:
- `main`: `broker_ledger_next_close`
- `concentrated`: `broker_ledger_next_close`

Strict target mode: `false`

## Cash Trap Guard

- `main`: severity=`ok`, avg_cash=26.67%, latest_cash=14.20%, reasons=none
- `concentrated`: severity=`warn`, avg_cash=42.29%, latest_cash=0.01%, reasons=cash_drag_with_cagr_gap

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
| main | `main_rebalance_interval_fixed_interval_I1` | 33.44% | 0.00pp | -18.06% | 0.00pp | true | `target_pass_review` |
| concentrated | `concentrated_latest_champion` | 50.35% | 0.00pp | -26.68% | 0.00pp | true | `target_pass_review` |

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
- `ERROR` data_readiness_ready_for_production_replay: status=blocked; ready_for_fullrun=False; ready_for_policy_replay=False; blockers=['scored_latest.csv row count is below threshold: 259']; policy_replay_blockers=['scored_latest.csv row count is below threshold: 259']; warnings=['latest target date 2026-06-16 is after latest observable close 2026-06-12; freshness gate uses observable close', 'dated target snapshot archive is missing for this run']
- `PASS` dataset_coverage_audit_available: outputs/reports/dataset_coverage_audit.json
- `PASS` sec_enriched_candidate_materialized_for_audit: sec_enriched_candidate_present=True; rows_with_smart_money_evidence=34256
- `PASS` alphaops_vnext_uses_sec_enriched_candidate_book: candidate_book=/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/sec_enriched_candidate_replay/candidate_replay_book_sec_enriched.csv; rows_with_smart_money_evidence=34256
- `WARN` orchestrator_replay_valid_for_promotion: status=blocked_missing_concentrated_monthly; data_mode=proxy_top_raw_score_within_main_holdings
- `PASS` main_target_book_reaches_broker_end: selected_role=operating_target_book; target_book_max=2026-06-12; broker_end=2026-06-15; date_gap_days=3; allowed_lag_days=7; rows=1281; path=/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/operating_main_target_book.csv
- `PASS` main_operating_target_book_available: operating_book=/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/operating_main_target_book.csv; rows=1281; max_date=2026-06-12
- `WARN` main_historical_research_book_reaches_broker_end: historical_book_max=2026-03-31; broker_end=2026-06-15; rows=2105; operating_book_max=2026-06-12; operating_rows=1281
- `PASS` main_broker_replay_uses_operating_target_book: metric_target_book=/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/operating_main_target_book.csv
- `PASS` concentrated_target_book_reaches_broker_end: selected_role=operating_target_book; target_book_max=2026-06-12; broker_end=2026-06-15; date_gap_days=3; allowed_lag_days=7; rows=497; path=/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/operating_concentrated_target_book.csv
- `PASS` concentrated_operating_target_book_available: operating_book=/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/operating_concentrated_target_book.csv; rows=497; max_date=2026-06-12
- `WARN` concentrated_historical_research_book_reaches_broker_end: historical_book_max=2026-03-31; broker_end=2026-06-15; rows=23235; operating_book_max=2026-06-12; operating_rows=497
- `PASS` concentrated_broker_replay_uses_operating_target_book: metric_target_book=/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/operating_concentrated_target_book.csv
- `PASS` current_only_operating_holdings_available: /home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/operating_snapshot/current_operating_holdings_latest.csv; rows=20; legacy_snapshot_exists=True
- `PASS` main_current_position_count_near_latest_target_count: main_positions=13; latest_target_rows=19; excess=0
- `PASS` concentrated_replay_filter_matches_latest_target: broker_filter_n=operating_book; latest_operating_target_n=5; broker_mode=operating_book; latest_mode=alphaops_vnext_score_power
- `PASS` alphaops_vnext_production_flags_correct: {"current_holdings_source": "alphaops_vnext_policy_target_book", "production_applied": true, "sidecar_applied_to_production": true, "sidecar_only": false}
- `PASS` main_official_broker_metrics_valid_for_production: metric_source=broker_ledger_next_close; valid_for_production=True; fill_mode=next_close
- `PASS` concentrated_official_broker_metrics_valid_for_production: metric_source=broker_ledger_next_close; valid_for_production=True; fill_mode=next_close
- `PASS` sec_drive_restore_manifest_available: restored_count=5; missing=[]; errors=[]
- `WARN` theme_leadership_tape_available: top_theme=missing; top_theme_state=missing
- `WARN` macro_circuit_diagnostics_available: main_status=missing; concentrated_status=missing
- `PASS` feature_source_coverage_available: outputs/data_readiness/summary.json::feature_source_coverage
- `PASS` feature_source_coverage_pit_available_from_clean: pit_future_available_from_rows=0; available_from_column_count=8
- `PASS` feature_source_groups_present_for_target_books: missing_groups=[]
- `PASS` main_cash_position_count_contract: latest_date=2026-06-12; cash=19.24%; stock_count=13; crisis_state=GREEN; violations=[]; preexisting_in_baseline=[]
- `PASS` concentrated_concentration_contract: latest_date=2026-06-12; max_name=SNDK@28.50%; max_industry_group=Tech Hardware & Storage@45.06%; group_source=industry_group; violations=[]; preexisting_in_baseline=[]

## Data Quality Update Plan

- Readiness: ready_for_fullrun=`false`, ready_for_policy_replay=`false`, blockers=['scored_latest.csv row count is below threshold: 259'], policy_blockers=['scored_latest.csv row count is below threshold: 259']
- Coverage: sec_enriched_candidate_present=`true`, smart_money_rows=34256, candidate_book=`/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/sec_enriched_candidate_replay/candidate_replay_book_sec_enriched.csv`
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
