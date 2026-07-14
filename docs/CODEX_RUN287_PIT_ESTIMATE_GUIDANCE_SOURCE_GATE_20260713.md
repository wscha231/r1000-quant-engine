# Run287 PIT estimate/guidance source gate - 2026-07-13

## Decision

The next CAGR-gap lane is now open only as a provider-neutral data procurement
gate. No estimate/guidance alpha screen, fixed-book arm, generated-book arm,
fullrun, portfolio mutation, purchase, production activation, or live trading
was performed.

The exact preregistered research key is:

`pit_estimate_guidance_composite_revision_state + single_source_screen + single_source_events + 2019-06-03_2026-07-10`

The do-not-repeat preflight returned `ALLOWED_NEW_COMBINATION`. The source gate
must pass before the composite state is implemented or any historical returns
are joined.

## Why the current free archive cannot be reused historically

GitHub run `29028159934` requested 863 names but found true forward estimates
for only 13 (`1.5064%`). Its rows are current snapshots with date-only
`available_from=2026-07-09`; they correctly remain forward-only.

Applying the new source audit to that artifact returns `BLOCKED_SCHEMA`:

- the event export has no stable `security_id`, provider observation ID,
  exact `observed_at`, fiscal-period event key, long-form metric/value role, or
  row-level source hash;
- the requested universe has no stable `security_id` or `is_delisted` flag;
- current snapshots must not be pasted backward into 2019-2026.

This is a data-entitlement result, not a strategy failure. The 13 usable
snapshots continue only in the true-forward paper archive.

## Frozen sample contract

The machine-readable thresholds are in
`docs/run287_pit_estimate_guidance_source_requirements.json`. They are frozen
before alpha labels and must not be weakened after a provider result is seen.

The first export is a small, stratified sample, not a full-universe license:

- at least 50 stable security IDs, including at least five delisted names;
- exact timezone-bearing `observed_at` and `available_from` on 100% of rows;
- `available_from >= observed_at`, unique append-only observation IDs, no rows
  after the frozen 2026-07-10 endpoint, and SHA-256 source provenance on 100%
  of rows;
- consensus EPS and revenue revision-ready history for at least 80% of the
  requested sample;
- reproducible company-guidance/preceding-consensus pairs for at least 50%;
- at least 90% any-event coverage, 80% full-window coverage, 80% OOS2 coverage
  from 2023-01-01, and 80% OOS coverage from 2024-07-01;
- at least 80% coverage of the requested delisted names;
- symbol history, delisted history, PIT history, and research reproduction
  rights must be explicitly represented in provider metadata.
- outcome compatibility for fixed 21/63/126/252/504-trading-day horizons under
  `docs/run287_pit_estimate_guidance_outcome_contract.json`.

Missing securities or components are coverage failures and remain neutral.
They are never imputed as positive or negative evidence.

## Provider-neutral long-event schema

Each CSV or Parquet row must contain:

- identity: `provider`, `observation_id`, `security_id`, `ticker`;
- event key: `record_type`, `metric`, `fiscal_period_end`,
  `fiscal_period_type`, `value_role`;
- value: `value`, `currency`, `unit`, `analyst_count`;
- PIT provenance: `observed_at`, `available_from`, `source_hash`.

Registered rows are intentionally narrow:

- `consensus_estimate` + `consensus_mean` for `eps` or `revenue`;
- `company_guidance` + `guidance_midpoint` for `eps` or `revenue`;
- period type `FY` or `FQ`.

The requested-universe file must contain `security_id`, `ticker`, and
`is_delisted`. Stable security IDs, rather than current ticker alone, are the
join key for symbol changes and delisted history.

## Procurement boundary

The metadata JSON records the quoted sample amount and a separately approved
cost ceiling in the same currency. The audit fails if the quote exceeds that
ceiling, if long-term lock-in is required, or if the provider does not grant
enough rights to reproduce the research. The tool never creates approval:
`purchase_authorized=false` is always emitted.

A zero-cost sample can be audited immediately with both amounts set to zero. A
paid sample requires the user to approve a fixed ceiling before acquisition.
Full-universe licensing is not considered until a delivered sample reaches
`READY_FOR_SOURCE_SCREEN` and then passes the separate preregistered alpha
source screen.

## Gate states and stop rules

`tools/audit_pit_estimate_guidance_source.py` emits `summary.json`,
`checks.csv`, `coverage_by_security.csv`, and `report.md`.

- `BLOCKED_SCHEMA`: required identity/event/provenance fields are absent.
- `BLOCKED_PIT`: timestamps, chronology, uniqueness, endpoint, or source hashes
  fail.
- `BLOCKED_PROCUREMENT`: capability, lock-in, rights, or approved-cost checks
  fail.
- `UNDER_COVERED`: the exact contract is valid but the sample is too sparse.
- `READY_FOR_SOURCE_SCREEN`: data may enter the single-source screen only; no
  alpha or portfolio acceptance is implied.

Any blocked state means do not purchase the full history and do not backtest
that export. Replace or repair the sample without inspecting return labels.

Example:

```powershell
py -3 tools/audit_pit_estimate_guidance_source.py `
  --input H:\data\candidate_estimate_events.parquet `
  --universe H:\data\candidate_sample_universe.csv `
  --metadata H:\data\candidate_provider_metadata.json `
  --output-dir outputs\run287_pit_estimate_guidance_source_gate
```

## Validation

`tests/pit_estimate_guidance_source_gate_smoke.py` covers:

- a valid exact-time export reaching `READY_FOR_SOURCE_SCREEN`;
- date-only timestamps and availability-before-observation blocking PIT;
- missing-security coverage staying neutral and returning `UNDER_COVERED`;
- provider lock-in returning `BLOCKED_PROCUREMENT`;
- required-column loss returning `BLOCKED_SCHEMA`;
- all promotion, purchase, fullrun, production, and live-trading flags staying
  false.

## Next action

The deterministic request is now generated under
`outputs/run287_pit_estimate_guidance_sample_request_20260714/`: 45 current
stratified issuers, five ADR/global slots within that active sample, and five
historical-delisted provider-query slots. Request a zero-cost schema export
first. If no candidate supplies that export without lock-in, present a fixed
sample-cost ceiling and exact required fields to the user for separate
approval. Do not buy a full license and do not build the composite alpha state
yet.
