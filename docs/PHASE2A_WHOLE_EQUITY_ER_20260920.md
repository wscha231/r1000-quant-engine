# [PROJECT_HANDOFF] Phase 2A — Whole-Equity ER Integration

Date: 2026-09-20 UTC. Base audited before implementation: `0140c81eab1ad7ec94eadaef2e03a22892419a7d`.
Tracking: issue #470; parent program issue #465.

## Decision

Control Plane v2 Phase 1 (#468) is already merged and is not repeated. The next
causal dependency is to bind the complete US-equity cohort to the existing
Run287 expected-return challenger. No new ER model is introduced.

The existing challenger remains authoritative for the currently implemented
research horizons: 21/63/126 NYSE sessions, corresponding approximately to
1/3/6 months. Its existing PIT/purge/embargo/OOS code and public latest proposal
are reused. Historical `r_12m`/`bench_r_12m` columns are not promoted to a model.

## Implemented slice

`tools/run_phase2a_whole_equity_er.py` is an evidence-bound adapter, not a
trainer. It consumes:

- admitted Theme/ETF whole-equity cohort publication;
- the exact security identity registry associated with that cohort;
- `latest_expected_return_proposal.csv` from the existing challenger;
- the challenger summary and source manifest;
- the existing challenger contract.

It verifies the exact proposal and summary bytes against the challenger source
manifest, requires the current cohort session, rejects realized/label/target/outcome
columns, preserves every cohort `security_id`, and maps ticker only when the
identity registry proves a one-to-one relation. The cohort publication's own
`bridge_sha256` is recomputed, and the supplied identity registry must byte-match
the single authenticated `*/securities/data.json` member recorded in cohort evidence. The source manifest must carry the
existing Run287 schema, producer Git SHA, canonical U0 artifact identity and
feature-store fingerprint. The challenger contract is checked with the same
canonical-JSON SHA-256 semantics used by the existing runner, including the pinned
Run287 contract hash; a raw-file hash is not substituted for that identity.

A1 fail-closed checks require issuer/security identity, public availability,
research eligibility, COMMON/ADR share-basis classification, an explicitly
attested split/dividend-adjusted total-return corporate-action basis, and ADR
ratio/currency evidence for ADRs. Any A1/identity or row-level evidence failure keeps the row but nulls all 1/3/6m
ER fields. A failure isolated to one validated horizon nulls only that horizon and
preserves independently validated horizons; the security remains PARTIAL and
whole-equity readiness stays false. Missing ER rows are never converted to zero
or neutral values.

For admitted rows A3 maps the existing 21/63/126-session absolute return,
benchmark-excess, alpha and downside outputs. An implied benchmark expected
return is reported only as `absolute - benchmark_excess` and is explicitly
labelled with that basis. Expected drawdown, calibrated signal confidence,
valuation/thesis status and thesis confidence remain null because this slice
does not validate them.

All 12-month ER/alpha/benchmark/downside fields remain null and carry
`BLOCKED_MODEL_NOT_VALIDATED`. No 6m extension or momentum conversion exists.

The packet always keeps `global_ranking_ready=false`, `a5_execution_allowed=false`,
target/order authority false, and no portfolio/champion/fullrun authority.

## Known current blocker

The merged H1 input-integrity handoff explicitly records unresolved APH split
and TSM ADR/FX/share-basis repair; correct corporate-action/issuer conversion is
not produced by that patch. Therefore this adapter is intentionally capable of
returning `PARTIAL_BLOCKED_WHOLE_EQUITY_ER` against current real inputs rather
than fabricating G0 readiness.

## Validation

The focused synthetic smoke suite covers:

- successful complete 1/3/6m mapping;
- permanent null/blocked 12m behavior;
- incomplete cohort coverage;
- corporate-action basis failure;
- ADR ratio/share-basis failure;
- future identity availability;
- non-unique ticker identity;
- proposal byte/hash mismatch;
- stale/future decision dates;
- forward/realized label leakage in the public proposal;
- nonfinite ER values;
- output artifact hash binding;
- canonical-JSON challenger-contract hash parity versus raw-file hashing;
- summary byte/hash and decision/candidate-count binding;
- canonical U0 artifact and feature-store identity presence;
- horizon-specific failure isolation without erasing independently validated ER horizons.

The focused suite now adds adversarial cohort/registry provenance cases: a registry
whose bytes differ from the authenticated securities component and a tampered
bridge publication both fail before A1 mapping. Final exact-head CI is the
authoritative test result after this correction. The suite now also verifies
producer Timestamp-to-session normalization, U0 workflow-path binding and the
raw contract-input fingerprint recorded separately from the canonical contract
identity. Earlier 12- and 16-test passes predated these fixes and are not
final-head evidence.

## Self-audit correction

Before independent review, a provenance mismatch was found: the existing Run287
challenger records `contract_sha256` over canonical JSON, while the first adapter
draft compared it with a raw file SHA-256. Synthetic fixtures had mirrored the
wrong raw-hash behavior. The adapter and fixtures were corrected before review so
real challenger output is checked with the producer's actual hash semantics.
A second pre-review compatibility audit found that the producer summary may
serialize a pandas decision Timestamp as an ISO datetime rather than a bare date;
the adapter now normalizes both the proposal and summary decision value to a
NYSE session date. U0 workflow path/digest and the producer-recorded raw contract
input fingerprint are also bound to the pinned contract.

## A6 provenance correction

A pre-review A6 audit found that the earlier adapter compared registry IDs and
tickers but did not prove that the registry bytes came from the admitted cohort.
That allowed a separately modified registry to fabricate corporate-action or ADR
basis fields. The adapter now binds the registry to the authenticated securities
component in cohort evidence and verifies the cohort publication hash itself.
This intentionally means current real inputs remain BLOCKED until the upstream
securities producer itself carries the required corporate-action/ADR basis or a
separately authenticated A1 producer is introduced; downstream enrichment cannot
silently rewrite the admitted registry.

## Next action / stop condition

Run the adapter only after materializing the exact verified cohort, identity
registry and challenger outputs from one current session. If corporate-action,
ADR/share-basis, PIT availability, proposal hash or whole-cohort coverage fails,
record Phase 2A as BLOCKED and repair that upstream evidence. Do not advance to
Phase 2B or A5 on a blocked packet.
