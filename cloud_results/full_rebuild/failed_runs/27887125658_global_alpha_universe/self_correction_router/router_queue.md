# Self-Correction Router Queue

- production_mutation_allowed: `false`
- latest_focus: `concentrated:structural_underinvestment_bull`
- repeat_confirmed: `true`
- requires_completed_plan_ids: `full_rebuild_8y_official_after_data_bootstrap`
- duplicate_suppressed_count: `0`
- stale_payload_count: `0`
- oos_lock_status: `fail`

| Experiment | Status | Source Leak | Source Run | Env | Requires Approval |
| --- | --- | --- | --- | --- | :---: |
| conc_continuation_winner_relaxation | queued | concentrated:structural_underinvestment_bull | 27887125658 | PHASE_CONCENTRATED_CONTINUATION_RELAX_ENABLED=1 | yes |
| conc_bull_floor_stock_min | queued | concentrated:structural_underinvestment_bull | 27887125658 | PHASE_REGIME_CAPACITY_BULL_FLOOR_ENABLED=1 | yes |
| conc_reentry_quality | queued | concentrated:structural_underinvestment_bull | 27887125658 | PHASE_CONCENTRATED_REENTRY_QUALITY_ENABLED=1 | yes |
| conc_theme_leadership_boost | queued | concentrated:structural_underinvestment_bull | 27887125658 | PHASE_THEME_LEADERSHIP_BOOST_ENABLED=1 | yes |
| conc_concentration_cap_relaxation | queued | concentrated:structural_underinvestment_bull | 27887125658 | PHASE_CONCENTRATED_CAP_RELAX_ENABLED=1 | yes |

## Dispatch Artifacts

- `workflow_dispatch_payloads.json`: REST/GraphQL-ready workflow dispatch payloads.
- `workflow_dispatch_commands.sh`: equivalent `gh workflow run` commands for manual review.
- These files are generated only; this router never dispatches workflows itself.

## Review Tasks

| Task | Portfolio | Failure | Dispatch Mode | Next Action |
| --- | --- | --- | --- | --- |
| concentrated_oos_lottery_era_name_review | concentrated | oos_is_cagr_ratio_above_lock | manual_review_no_workflow_dispatch | Compare IS/OOS top-name contribution and era buckets; require a new 8-year rebuild plus A/B verifier before promotion. |
| main_oos_lottery_era_name_review | main | oos_is_cagr_ratio_above_lock | manual_review_no_workflow_dispatch | Compare IS/OOS top-name contribution and era buckets; require a new 8-year rebuild plus A/B verifier before promotion. |
