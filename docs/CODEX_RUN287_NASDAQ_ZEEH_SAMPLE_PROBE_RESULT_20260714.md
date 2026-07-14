# Run287 Nasdaq ZACKS/EEH bounded sample probe - 2026-07-14

## Decision

Nasdaq Data Link `ZACKS/EEH` is now registered as a bounded schema-probe
candidate, not as an approved Run287 PIT source.  The probe can issue at most
two HTTP requests and retain at most 50 data rows.  It cannot join returns,
run portfolio A/B, authorize a purchase, run fullrun, or affect production.

The provider metadata identifies EEH as the premium, continuously updated
Zacks Consensus Earnings Estimates History table.  Its advertised primary key
contains `m_ticker, per_end_date, obs_date, per_type`.  The decisive unresolved
question is whether an entitled sample supplies an exact observation and
availability timestamp plus stable security, delisted, and ADR identity.  A
date-only `obs_date` is not converted to a fabricated midnight timestamp.

Official references:

- <https://data.nasdaq.com/api/v3/datatables/ZACKS/EEH/metadata.json>
- <https://docs.data.nasdaq.com/docs/data-organization>
- <https://docs.data.nasdaq.com/docs/api-and-analysis-tools-for-tables-data>

## Implementation

`tools/probe_run287_nasdaq_zeeh_sample.py`:

- reads the key only from `NASDAQ_DATA_LINK_API_KEY` by default;
- never accepts a secret value as a CLI argument;
- makes zero requests when the key is missing;
- makes at most one metadata and one 50-row data request when a key exists;
- redacts API-key query parameters and the exact key from persisted errors;
- writes raw successful responses once and records SHA-256 hashes;
- blocks row counts above 50, future observation dates, malformed rows,
  duplicate provider keys, and immutable evidence collisions;
- reports exact-timestamp, stable-ID, delisted, and ADR gaps separately;
- leaves all promotion and execution permissions false.

The machine-readable restrictions are frozen in
`docs/run287_nasdaq_zeeh_sample_contract.json`.

## Local preflight

The 2026-07-14 local run found no configured `NASDAQ_DATA_LINK_API_KEY`.

- status: `BLOCKED_CREDENTIAL_MISSING`;
- HTTP requests: `0`;
- provider charges or trial activation: none;
- return joins, backtests, book changes, orders, fullrun, production: none.

Evidence is retained locally at
`outputs/run287_nasdaq_zeeh_sample/20260714_local_preflight/`.  Outputs and any
future provider sample rows remain untracked.

The earlier keyless EEH data attempt returned HTTP 403.  Do not retry the same
keyless data request.  Metadata availability does not imply sample-data
entitlement.

## Gate interpretation

A successful 50-row response can reach only
`READY_50_ROW_SCHEMA_REVIEW`.  It does not reach the existing
`READY_FOR_SOURCE_SCREEN` gate.  In particular:

- `obs_date` must carry time and timezone on every fired row, or a separate
  exact `available_from` field must be supplied and verified;
- permanent security identity and symbol history must cover inactive names;
- delisted membership and delisting return or cash proceeds must be supplied;
- ADR/global identity must be explicit;
- the frozen 50-security request and 2019-2026 window must pass the existing
  source audit before any outcome label is joined.

If the entitled sample confirms date-only availability or lacks these identity
fields, close the EEH lane rather than coercing timestamps or adding inferred
delisted/ADR labels.

## Cost-efficient next action

No paid action is authorized.  If an existing self-service Nasdaq Data Link key
with ZEEH sample entitlement becomes available, place it only in the local
`NASDAQ_DATA_LINK_API_KEY` environment variable and run this single bounded
probe.  If no such entitlement exists, keep the lane blocked and evaluate a
different self-service source against the same frozen contract; do not repeat
FMP 402, the failed SEC guidance keyword lane, or date-only PIT proxies.

## Validation

`tests/run287_nasdaq_zeeh_sample_smoke.py` covers:

- missing-key zero-request behavior;
- HTTP 403 entitlement blocking and secret redaction;
- a 50-row date-only sample that is schema-reviewable but not PIT-ready;
- row-limit and future-date failures;
- raw-evidence idempotence and collision blocking.

The complete local PR validation passed `170/170` test files in `214.76`
seconds.  No fullrun was executed.
