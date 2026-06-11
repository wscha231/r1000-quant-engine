# User Current Action Summary

- action_status: `REVIEW_REQUIRED`
- official_metric_mode: `broker_ledger_next_close`
- valid_for_production: `True`
- production_applied: `false`
- sidecar_only: `true`
- current_holdings_source: `production_operating_target_book`
- cash_policy_flag: `cash_above_target`
- combined_projected_cash_after_ready_orders: `3.12%`

## Research Sidecar Context

- Market Leader / Multi-Lane / Crisis outputs are research-only and did not alter current holdings.
- replay_gate_status: `review_required`
- promotion_gate_status: `rejected`
- production_mutation_check_status: `passed`

## Reasons

- cash_policy_flag=cash_above_target
- current-vs-target implied turnover 80.58% > 30%

## Operating Rules

- This report shows current simulated broker-ledger holdings only.
- Current holdings follow the production operating book, not research sidecar target books.
- Target recommendation books are hidden by default.
- REVIEW_REQUIRED is not an auto-trade instruction.
- Research metrics are not promotion evidence.
