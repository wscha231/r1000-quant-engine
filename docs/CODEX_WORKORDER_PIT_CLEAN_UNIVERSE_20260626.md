# Codex Work Order - PIT-Clean Universe Membership (2026-06-26)

## Summary

Build the Track A substrate needed to earn `pit_universe_label_clean=true`.
This is a production-evidence blocker, not an alpha lever. Do not change
selection, scoring, sizing, cash, target policy, workflow dispatch, production
promotion, or live trading.

Current clean 7Y research status:

- Run `28074476465` has a valid 7Y broker window, but remains research-only.
- Main: `33.15% CAGR / -26.02% MDD`.
- Concentrated: `46.24% CAGR / -25.82% MDD`.
- `pit_universe_label_clean=false` remains the standing non-performance
  evidence/substrate blocker.
- Performance acceptance remains a separate blocker because both sleeves still
  miss the current target contract.

The specific substrate problem to remove is the survivorship-risk fallback in
`r1000_config.py`:

```python
universe_mode = "historical_snapshot_preferred"
universe_membership_path = ""
universe_fallback_mode = "current_constituents"
```

Past rebalance dates must not silently use today's constituents as if they were
historical Russell 1000 membership. If official historical membership is not
available, label the run as proxy/research and keep production promotion
blocked.

## In Scope

1. Add a PIT membership manifest/schema.
2. Add a no-future-membership audit.
3. Wire universe health/readiness so `pit_universe_label_clean=true` is emitted
   only when the audit is clean.
4. Keep proxy/current-constituent fallback available only with explicit
   non-production labels.
5. Add smoke tests that fail on current-constituents backfill masquerading as
   PIT membership.

## Out of Scope

- No alpha A/B.
- No T3/recovery.
- No proxy 8Y/10Y work.
- No production promotion claim.
- No live trading or canonical production sync.
- No manual flag flip to make `pit_universe_label_clean=true`.

## Current Consumers

Do not loosen these consumers.

- `tools/run_account_evaluation.py::pit_universe_label_clean()` accepts a clean
  label only from one of these fields in broker metrics/readiness/universe
  health:
  - `pit_universe_label_clean`
  - `pit_universe_clean`
  - `historical_universe_pit_clean`
  - `official_pit_r1000`
- `tools/run_account_evaluation.py::evaluate_window_gate()` uses that clean
  label to prevent longer proxy windows from being mistaken for production
  evidence.
- `tools/run_clean7y_window_preflight.py` already names the expected date
  fields, including:
  - `membership_available_from`
  - `universe_available_from`
  - feature/fundamental `available_from` fields.
- `tools/run_universe_health_audit.py::infer_primary_source()` currently
  identifies `historical_membership_file`, `current_constituents_proxy`, and
  `static_iwb_seed`. Preserve that distinction.

## Required Artifacts

Write the artifacts under `outputs/universe_health/` in full rebuild and under
the chosen output directory for local runs.

### `pit_membership_manifest.json`

Required fields:

- `schema_version`: `pit-membership-manifest-v1`
- `generated_at_utc`
- `membership_source`
- `membership_source_kind`: one of
  - `official_historical_membership`
  - `historical_membership_file`
  - `pit_proxy_universe`
  - `current_constituents_proxy`
  - `static_seed`
- `universe_label`
- `official_r1000_membership_proven`
- `proxy_universe_flag`
- `start_date`
- `end_date`
- `rebalance_date_count`
- `ticker_count`
- `coverage_by_date`
- `known_gaps`
- `promotion_eligible`
- `production_mutation_allowed`: must be `false`

### `pit_membership_by_month.csv`

Required columns:

- `rebalance_date`
- `ticker`
- `membership_source`
- `membership_available_from`
- `membership_end_date`
- `universe_label`
- `official_r1000_membership_proven`
- `proxy_universe_flag`
- `survivorship_status`
- `delisted_coverage_status`
- `ticker_change_coverage_status`
- `membership_pit_status`

### `pit_membership_audit.json`

Required fields:

- `schema_version`: `pit-membership-audit-v1`
- `status`: `pass | blocked`
- `pit_universe_label_clean`
- `historical_universe_pit_clean`
- `official_pit_r1000`
- `no_future_membership_violations`
- `membership_available_from_future_rows`
- `unknown_membership_available_from_rows`
- `current_constituents_proxy_rows`
- `static_seed_rows`
- `proxy_rows`
- `official_rows`
- `coverage_floor`
- `coverage_pass`
- `violations_sample`
- `blockers`

### `pit_membership_audit.md`

Human-readable summary. It must explicitly state whether the result is:

- `official_pit_r1000`
- `pit_proxy_universe`
- `current_constituents_proxy`
- `static_seed`

Do not call proxy data official Russell 1000 membership.

## Clean-Flag Rules

Emit `historical_universe_pit_clean=true` or
`pit_universe_label_clean=true` only if all are true:

1. `membership_source_kind` is `official_historical_membership` or a validated
   `historical_membership_file`.
2. `membership_available_from <= rebalance_date` for every selected and scored
   membership row.
3. `no_future_membership_violations == 0`.
4. `current_constituents_proxy_rows == 0`.
5. `static_seed_rows == 0` for the evaluated historical period.
6. Delisted/ticker-change coverage is either clean or explicitly documented as
   a production blocker.
7. Coverage floor passes for every rebalance month.

If any condition fails:

- `pit_universe_label_clean=false`
- `historical_universe_pit_clean=false`
- `official_pit_r1000=false`
- `production_promotion_allowed=false`
- `evidence_label=research_proxy_or_diagnostic`

## Implementation Steps

### Step 1 - Locate and Label Membership Source

Trace the data path that populates R1000 membership for scored rows and
candidate replay rows. The first pass may be audit-only.

Record for every membership row:

- `rebalance_date`
- `ticker`
- `membership_source`
- `membership_available_from`
- `universe_label`
- `official_r1000_membership_proven`
- `proxy_universe_flag`

If the row came from current IWB/R1000 constituents projected backward, set:

- `membership_source=current_constituents_proxy`
- `universe_label=current_constituents_proxy`
- `proxy_universe_flag=true`
- `membership_pit_status=blocked_current_constituents_backfill`

### Step 2 - Add No-Future Audit

Audit these violations:

- `membership_available_from > rebalance_date`
- missing/unknown `membership_available_from`
- current-constituents proxy used for historical membership
- static seed used without explicit proxy label
- ticker changes not traceable to the historical ticker at rebalance date
- delisted coverage unknown

The audit should run without needing a 4-hour full rebuild.

### Step 3 - Wire Universe Health

Extend `tools/run_universe_health_audit.py` or a focused helper that it calls.
The output must preserve current source classification and add PIT membership
fields. The existing source distinctions are useful:

- `historical_membership_file`
- `current_constituents_proxy`
- `static_iwb_seed`

Do not collapse these into one generic "universe pass".

### Step 4 - Wire Readiness / Account Evaluation

`run_account_evaluation.py` already consumes clean labels. Prefer emitting the
right fields into universe health/readiness instead of loosening the consumer.

Expected result before official data exists:

- `pit_universe_label_clean=false`
- `primary_universe_source=current_constituents_proxy` or `pit_proxy_universe`
- production promotion still blocked.

Expected result after PIT-clean data exists and audit passes:

- `pit_universe_label_clean=true`
- `historical_universe_pit_clean=true` or `official_pit_r1000=true`
- no future membership violations.

### Step 5 - Keep Research Running

This track must not block clean 7Y research/A/B. It only blocks production
promotion. Research artifacts must keep their label:

- `research_7y` for clean 7Y broker ledger with data readiness pass.
- `pit_proxy_universe` for proxy historical membership.
- `official_pit_r1000` only when official/historical membership is proven.

## Test Plan

Add focused tests. Avoid requiring a full rebuild.

### Unit / Smoke

1. `pit_membership_audit_smoke`
   - synthetic membership with `membership_available_from <= rebalance_date`
     passes no-future audit.
   - one future membership row blocks clean label.
   - missing `membership_available_from` blocks clean label.
   - current constituents projected backward blocks clean label.

2. `universe_health_pit_label_smoke`
   - `historical_membership_file` with clean audit emits
     `historical_universe_pit_clean=true`.
   - `current_constituents_proxy` emits
     `pit_universe_label_clean=false`.

3. `account_evaluation_pit_clean_consumer_smoke`
   - existing consumer recognizes clean labels.
   - proxy/current-constituent labels do not unlock production.

### Regression

- `pit_universe_label_clean=false` continues to block production promotion even
  if broker CAGR/MDD are strong.
- clean 7Y research remains usable for diagnostics/A/B when data readiness and
  universe health pass.
- No test should require live trading, workflow dispatch, or a long fullrun.

## Acceptance

Accepted when a local synthetic test and one real artifact audit show:

- no future membership violations are counted correctly;
- current-constituents backfill is explicitly blocked from clean label;
- account evaluation still blocks production when PIT membership is unclean;
- no alpha/scoring/cash/target behavior changes.

## Reporting

When done, report:

- exact producer path changed;
- clean-label source and audit artifact paths;
- violation counts;
- whether `pit_universe_label_clean` is earned or still blocked;
- why any remaining blocker is data availability rather than code plumbing.
