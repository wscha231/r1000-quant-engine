# Run287 H3 risk and Reserve correctness result

Date: 2026-07-22

Scope: Issue #315 H3 only

Performance impact: none; this is state, Reserve provenance, accounting, and
replay-boundary correctness hardening

## Result

The historical replay, same-close target path, account preview, bootstrap, and
daily paper ledger now share explicit crisis-state and Reserve contracts.

- Legacy crisis names are converted only at input adapters. Downstream state
  consumers use the canonical state set.
- Missing, unknown, or malformed states become `DEGRADED_DATA`; they cannot
  silently become `GREEN`.
- Source stale flags use a strict boolean parser. Ambiguous values fail closed.
- Re-entry stages do not regress solely because a recovery score weakens. A
  new `WATCH`, `DEFENSE`, or `CRISIS` state is required to worsen exposure.
- Residual target capacity is materialized as an explicit `CASH` row.
- Reserve reasons reconcile to Reserve weight and carry a deterministic
  `reserve_reason_source_hash` from target through preview, ledger manifest,
  and account state.
- Position reporting distinguishes `position_count_total`,
  `equity_position_count`, and `reserve_position_count`; legacy
  `position_count` remains the equity count where Reserve is explicit.
- Explicit tradeable Reserve modes remain research-only and cannot report
  `valid_for_production=true`.
- Integrated broker replay period ends are clamped to the available stock
  evidence end date.

## Fixture evidence

The H3 fixtures prove:

1. canonical validation rejects legacy and unknown state names while the input
   adapter performs the intended legacy conversion;
2. missing and unknown states never become `GREEN`, including the empty-state
   integrated replay boundary;
3. string `false` remains false and ambiguous stale values are rejected;
4. a weakening recovery score cannot silently move re-entry backward;
5. implicit target cash becomes explicit `CASH` and Reserve reasons reconcile;
6. conflicting Reserve source hashes fail closed, while the accepted hash is
   preserved through target, preview, ledger manifest, and account;
7. BIL research replay exposes separate equity/Reserve counts and remains
   invalid for production;
8. no broker replay period extends beyond the stock evidence end date.

## Regression evidence

- Focused crisis, Reserve, preview, bootstrap, daily-ledger, same-close,
  transaction, and integrated-replay smoke tests: PASS.
- Repository pytest: `129 passed`.
- Full Tier-1 PR validation: `191/191` in `452.77s`.
- The first full run passed `188/191`; the three failures identified an
  expected count-schema update, an unlabeled crisis-raised Reserve amount, and
  an old fixture that treated missing crisis inputs as implicit `GREEN`. After
  those fixes, the second run passed `190/191`; its remaining independent
  leadership-persistence fixture had the same implicit-`GREEN` assumption.
  Giving that fixture an explicit known-`GREEN` input produced the final clean
  `191/191` run.
- Python compilation and `git diff --check`: PASS.

The tests use temporary fixtures. No durable paper account, public operating
target, downloaded artifact, Drive archive, or existing untracked output was
modified. No fullrun, production activation, or live order was executed.

## Performance status and next gate

Official historical evidence remains unchanged:

- Main: CAGR `34.4032%`, MDD `-25.3629%` through 2026-07-10.
- Concentrated: CAGR `49.0968%`, MDD `-22.9560%` through 2026-07-10.

These are not refreshed 2026-07-17 or 2026-07-20 figures. H3 requires a clean
current-head review, merge, and exact-merge smoke before H4. Durable catch-up
and any new CAGR/MDD challenger remain blocked.

## Exact-head review follow-up

The Codex exact-head review found five additional boundary defects. All five
were corrected before merge:

- next-close fills after `stock_evidence_end_date` are excluded, so the final
  signal cannot create a post-evidence trade or equity mark;
- implicit cash is assigned to one Reserve reason only;
- pre-existing cash and newly materialized residual cash reconcile to the full
  explicit Reserve weight;
- an embedded `reserve_reason_source_hash` must match the hash recomputed from
  the current Reserve weight and reason allocation;
- the research-only residual-cash filter retains its documented unannotated
  historical-book boundary, while non-blank unknown crisis states still fail
  closed as `DEGRADED_DATA`.

Post-fix validation passed: focused affected suites, repository pytest
(`129/129`), full Tier-1 validation (`191/191`, `454.55s`), Python compilation,
and `git diff --check`. Fullrun remained unexecuted.

## Second exact-head review follow-up

The second Codex exact-head review found four remaining fail-closed gaps. They
were corrected together with targeted regression fixtures:

- daily paper bootstrap preserves the embedded Reserve reason source hash so a
  stale or conflicting provenance value cannot be silently recomputed;
- `DEGRADED_DATA` blocks the production shakeout guard instead of suppressing a
  required trim during a crisis-data outage;
- all known alternative lanes, and any unrecognized lane, are blocked from new
  buys while crisis data is degraded;
- tradeable Reserve history coverage is checked only through the explicit
  stock evidence cutoff rather than through later cached stock observations.

The four targeted smoke suites passed. Repository pytest passed `129/129`, and
full Tier-1 validation passed `191/191` in `454.51s`. Python compilation and
`git diff --check` also passed on the final exact head. Fullrun remained
unexecuted.

## Third exact-head review follow-up

The third Codex exact-head review found four remaining provenance/audit
consumers. They are corrected with focused regressions:

- broker target normalization preserves and validates embedded Reserve source
  hashes rather than replacing stale input provenance;
- direct account-order preview writes the reconciled source hash into
  `target_weights.csv` as well as its manifest and metrics;
- a lifecycle-mutated effective target intentionally discards the pre-mutation
  source hash, then writes the newly reconciled hash;
- the cash/re-entry quality audit maps degraded, blank, unknown, and explicitly
  missing crisis states to its existing `MISSING` bucket, which triggers
  `REVIEW_REQUIRED_MISSING_CRISIS_STATE` and excludes the rows from green-regime
  cash and rebound statistics.

Final validation passed: focused affected suites, repository pytest `129/129`,
full Tier-1 `191/191` in `446.39s`, Python compilation, and
`git diff --check`. Fullrun remained unexecuted.
