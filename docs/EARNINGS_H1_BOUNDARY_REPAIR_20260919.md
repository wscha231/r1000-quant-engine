# Earnings H1 boundary repair — 2026-09-19

Scope: H1 validation and an explicit, unscheduled legacy-collector adapter. No H2
replay, alpha tuning, target writing, accepted-book change, secrets, or live order.

## Source identity

Audited master: `90b55fe92f25236c663a71cad7ab9138da497919`.
Original helper: PR453 head `55661460228674e56f1e15bb277179a1e64acd6f`,
blob `261f84812f42939c3cd4b584af78d13fafbbfda3`; exact bytes were reconstructed
and git-object-verified before eight baseline counterexamples were reproduced.
Adapter interface: PR454 head `ff05ab63ca78b8983d985f5da53ea223059db90d`,
blob `ccbafd7330ec50eb2760053b716179ea962549a4` was read through GitHub.

This clean slice brings only the H1 capability forward. PR453's historical
Layer-B replay remains a separate research experiment, not a dependency or
performance justification. PR454's original interface is reused, not a second
vendor collector or scheduled loop.

## Changes

- Reject boolean numeric values and fractional/negative analyst counts.
- Require aware intraday timestamps; retain microseconds and reject date-only
  times instead of assuming UTC midnight. Validate observation chronology.
- Preserve unknown numeric/context values; never synthesize issuer, currency,
  accounting, annual/quarterly or common-share/ADR identities.
- Match security, issuer, provider, currency, accounting basis, share unit,
  period type and actual fiscal period before computing a revision.
- Freeze pre-event consensus strictly before the event; filter instrument and
  context; refuse same-timestamp conflicting values.
- Unknown/negative success age is not fresh. Request eligibility is distinct
  from priority; blocked sources cannot be reactivated by a priority boost.
- Adapter uses actual availability for lookbacks and retains the anchor age.
  A fiscal period previously in FY2 can match that same period now in FY1.
- Absolute and percentage surprise are distinct. Fiscal period end is not an
  earnings-release date. Unverified actuals do not become eligible surprises.
- Restore temporary legacy callbacks on success and failure. This adapter is
  single-process only; it does not claim thread-safe concurrent patching.
- No revision-driven replacement permission; multiplier remains 1.0.

## Validation performed

44 unique helper boundary tests + 17 adapter tests = 61 unique test methods.
The same tests pass in normal and optimized Python 3.13.5; NOT 122 unique tests.
Local pandas is 2.2.3. Compilation succeeds. New tests use unittest assertions
that still run under -O. Baseline eight counterexamples are separately logged.
Adapter routing is tested with a fake legacy coordinator, not a live API call.

## Important non-claims / remaining integration

The scheduled earnings workflow is unchanged and still uses the old collector.
No actual API access, entitlement, full-universe repair or Drive publication by
the collector is proven by these tests. Date-only legacy clocks now fail closed;
the coordinator must pass an actual aware observation timestamp and exact
cutoff. Producer identity must be supplied, not invented by a caller. Existing
archive rows without that identity remain observation-only. No current data is
backfilled into historical returns. Full repository pinned CI and independent
exact-head review are still required; there is no gate bypass or auto-merge.

## Shared lesson

A valid payload hash and a VERIFIED string do not establish semantic identity,
PIT availability, data completeness, successful integration or alpha. A smoke
script printing PASS under -O is not evidence that removable assert statements
ran. Separately measure source integrity, executable connection, real input
coverage, end-to-end completion and out-of-sample performance.
