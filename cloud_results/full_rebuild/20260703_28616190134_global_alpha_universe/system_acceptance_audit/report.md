# System Acceptance Audit

- status: `not_ready`
- production_activation_allowed: `false`
- live_trading_allowed: `false`
- hard_blocker_count: `4`
- warning_count: `0`

| Requirement | Status | Hard Blocker | Summary |
| --- | --- | :---: | --- |
| official_broker_ledger_metrics | pass | false | official broker-ledger next-close metrics exist for both portfolios |
| goal_contract_main30_conc50_mdd | fail | true | goal contract is not yet met |
| eight_year_broker_ledger_window | fail | true | official 8-year broker-ledger window is not proven |
| oos_holdout_lock | fail | true | locked IS/OOS holdout audit failed |
| data_readiness_price_macro_sec_etf | pass | false | data readiness has no hard blockers |
| broker_realism_next_close_integer_cash_costs | pass | false | broker replay uses next-close, integer shares, costs, and 7-day fill lag |
| target_book_broker_cash_contract | pass | false | target books have explicit CASH rows and broker cash drift is within limits |
| attribution_package_year_mdd_name | fail | true | attribution evidence package is incomplete |
| operational_order_preview_safety_bridge | pass | false | operating target books are bridged to safe paper order manifests |
| era_leadership_and_challenger | pass | false | era diagnostics and review-only challenger are present |
| daily_crisis_paper_action_wire | pass | false | crisis monitor and paper-order bridge are wired with approval gates |
| self_correction_router_queue | pass | false | self-correction queue and dispatcher dry-run are review-only |
| adr_universe_review_automation | pass | false | monthly ADR candidate review and guarded apply automation are present |
| portfolio_system_guard | pass | false | portfolio system guard has no hard errors |

## Next Actions

- Use IS attribution and challenger queues; do not promote until Tier-2 gates pass.
- Extend price/universe/cache and target books back to at least mid-2018, then rerun full rebuild.
- Treat the candidate as non-promotable; inspect outputs/oos_lock/report.md before another SHIP retry.
- Run IS attribution, era leadership, trade attribution, and MDD cash overlay sidecars before treating any promoted result as official.

## Manual Review Tasks

- These tasks are review-only and must not dispatch workflows or mutate production.

| Task | Source | Portfolio | Failure | Dispatch Mode | Next Action |
| --- | --- | --- | --- | --- | --- |
| concentrated_oos_lottery_era_name_review | oos_lock | concentrated | oos_is_cagr_ratio_above_lock | manual_review_no_workflow_dispatch | Compare IS/OOS top-name contribution and era buckets; require a new 8-year rebuild plus A/B verifier before promotion. |

## Review Dispatch Plan

- `workflow_dispatch_payloads.json` and `workflow_dispatch_commands.sh` are review-only.
- They require explicit user approval before use.

| Plan | Workflow | Dependencies | Reason |
| --- | --- | --- | --- |
| bootstrap_free_data_for_8y_window | free_data_lake_bootstrap.yml |  | 8-year broker-ledger window is not ready; extend/restore price and free-data cache first. |
| full_rebuild_8y_official_after_data_bootstrap | full_rebuild_manual.yml | bootstrap_free_data_for_8y_window | After free-data bootstrap, run the official 8-year broker-ledger rebuild with the production policy. |
| ab_conc_continuation_winner_relaxation | full_rebuild_manual.yml | full_rebuild_8y_official_after_data_bootstrap | Concentrated CAGR or Tier-2 gate is short; relax continuation-winner filters only as a review A/B. |
| ab_conc_bull_floor_stock_min | full_rebuild_manual.yml | full_rebuild_8y_official_after_data_bootstrap | Concentrated CAGR or Tier-2 gate is short; measure bull/strong_bull stock-floor exposure as an isolated A/B. |
| ab_conc_reentry_quality | full_rebuild_manual.yml | full_rebuild_8y_official_after_data_bootstrap | Concentrated CAGR or Tier-2 gate is short; measure reentry quality after cash/defense states as an isolated A/B. |
| ab_conc_theme_leadership_boost | full_rebuild_manual.yml | full_rebuild_8y_official_after_data_bootstrap | Concentrated CAGR or Tier-2 gate is short; test theme-leadership confirmation boost as an isolated A/B. |
| ab_conc_concentration_cap_relaxation | full_rebuild_manual.yml | full_rebuild_8y_official_after_data_bootstrap | Concentrated CAGR or Tier-2 gate is short; test confirmed-winner cap relaxation while preserving broker-ledger gates. |
