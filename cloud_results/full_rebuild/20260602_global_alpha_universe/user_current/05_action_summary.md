# User Current Action Summary

- action_status: `REVIEW_REQUIRED`
- official_metric_mode: `broker_ledger_next_close`
- valid_for_production: `True`
- production_applied: `true`
- sidecar_only: `false`
- production_policy: `alphaops_vnext_production`
- sidecar_applied_to_production: `true`
- current_holdings_source: `alphaops_vnext_policy_target_book`
- source_target_run_id: ``
- source_target_case_id: ``
- promotion_status: `applied`
- shadow_available: `false`
- projected_holdings_path: ``
- projected_market_leader_holdings_path: ``
- decision_cadence_available: `true`
- decision_cadence_path: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/decision_cadence/decision_cadence_summary.json`
- mid_month_reentry_allowed: `true`
- cash_policy_flag: `cash_above_target`
- combined_projected_cash_after_ready_orders: `2.77%`

## Research Sidecar Context

- Market Leader / Multi-Lane / Crisis outputs alter current holdings only after production activation.
- replay_gate_status: `passed`
- promotion_gate_status: `rejected`
- promotion_review_status: `missing`
- production_mutation_check_status: `passed`
- production_mutation_audit_status: `applied`

## Reasons

- cash_policy_flag=cash_above_target
- current-vs-target implied turnover 95.58% > 30%

## Operating Rules

- This report shows current simulated broker-ledger holdings only.
- Current holdings follow the production operating book generated before broker replay.
- If integrated_shadow is enabled, projected holdings show what the H-case target would do before approval.
- If market_leader_shadow is enabled, projected holdings show what the Market Leader target would do before approval.
- If alphaops_vnext_production or approved_integrated is active before broker replay, current holdings can change in the same run.
- Crisis defense does not force month-end waiting; decision_cadence can flag mid-month staged reentry review.
- Target recommendation books are hidden by default.
- REVIEW_REQUIRED is not an auto-trade instruction.
- Research metrics are not promotion evidence.
