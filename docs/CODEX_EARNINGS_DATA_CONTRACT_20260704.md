# CODEX Earnings Data Contract - 2026-07-04

## Purpose

This contract separates earnings-related data into three non-interchangeable
layers:

1. **SEC actuals**: backward-looking reported fundamentals.
2. **Internal proxy scores**: diagnostic model features.
3. **True PIT revision/guidance**: forward expectation changes from dated
   analyst, vendor, company-guidance, or approved manual sources.

This is a research/data contract. It does not activate production, live
trading, fullrun dispatch, selection boosts, or policy hooks.

## Canonical Event Fields

Every normalized earnings event should preserve these fields when available:

- `ticker`
- `event_id`
- `event_date`
- `fiscal_period`
- `metric`
- `source_type`
- `source_name`
- `source_file`
- `source_hash`
- `observation_date`
- `available_from`
- `ingested_at`
- `value`
- `previous_value`
- `new_value`
- `delta`
- `delta_pct`
- `direction`
- `confidence`
- `is_coverage_eligible`
- `is_proxy`
- `is_actual`
- `pit_validated`
- `schema_version`

`available_from` is mandatory for every PIT use. Rows with
`available_from > decision_date` must be filtered before any measurement.

## Source Types

Coverage-eligible source types:

- `historical_revision`
- `vendor_estimate_revision`
- `company_guidance`
- `manual_research_import`

Not coverage-eligible source types:

- `sec_actual_snapshot`
- `current_snapshot`
- `internal_proxy_score`
- `actual_results_score`
- `eps_revision_score_proxy`
- `earnings_call_keyword`

SEC actuals can support thesis actualization diagnostics. They must not count
as R1 `earnings_guidance` coverage. Internal proxy scores can support research
screens. They must not be displayed or treated as analyst revision/guidance
confirmation.

## Readiness Tiers

### Plumbing Ready

Minimum for schema and wiring tests:

- `coverage_eligible_rows >= 5`, or
- `coverage_eligible_tickers >= 5`

This is not enough for R1 research/service claims.

### Research Ready

Minimum for internal R1 earnings/guidance coverage:

- at least 10 coverage-eligible tickers with at least 2 dated estimate
  observations, observation span at least 14 days, and recency at most 30 days;
  or
- at least 10 directional guidance rows across at least 5 tickers, with recency
  at most 30 days.

### Service Ready

Minimum for service/dashboard coverage:

- `research_ready=true`, and
- current or target book coverage weight at least 60%, or top-50 candidate
  coverage at least 40%, and
- at least 2 AI buckets / sectors covered when bucket data is available.

### Policy Ready

Minimum before any policy hook may use earnings confirmation:

- `research_ready=true`
- current or target book coverage weight at least 70%
- at least 15 coverage-eligible tickers
- at least 3 AI buckets / sectors covered when bucket data is available
- at least 2 quarters of dated history
- PIT audit pass

Until `policy_ready=true`, AI Capex, rotation, and replacement-quality hooks
must not use earnings confirmation as a hard gate.

## Service Labels

- `actuals_confirmed`: reported actuals confirmed. Backward-looking; does not
  imply analyst estimate revision.
- `analyst_revision_confirmed`: PIT analyst estimate revision confirmed from a
  dated coverage-eligible source.
- `company_guidance_confirmed`: company guidance direction confirmed from a
  dated coverage-eligible source.
- `proxy_score_diagnostic_only`: internal proxy score; not a substitute for
  analyst revision or guidance.
- `data_insufficient`: insufficient PIT revision/guidance data; do not use as
  earnings confirmation.

## Current Implementation

- Raw revision/guidance contract:
  `data_raw/events/earnings_revisions.csv`
- PIT revision/guidance signals:
  `data_pit/events/earnings_revision_signals.parquet`
- SEC actual snapshot output:
  `data_pit/events/sec_actuals_snapshot.parquet`
- Coverage tier check:
  `tools/check_earnings_guidance_coverage.py`
- Inventory:
  `tools/run_earnings_data_inventory.py`

## Non-Negotiables

- No production promotion.
- No live trading.
- No fullrun trigger.
- No policy hook from proxy-only evidence.
- No R1 `earnings_guidance` coverage from SEC actuals/current snapshots.
- No service-facing phrase that conflates actuals with revision/guidance.
