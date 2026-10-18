# Supplied-price incremental research plan V1

`tools.research_price_incremental_plan.plan_incremental` is a pure local adapter.
It reuses supplied daily-close rows, lists missing **closed** exchange sessions,
and calls the existing `research.a2_research_intake_v1.plan_delta` for a bounded
price-only research review plan. It does not collect or schedule anything.

## Inputs

Pass exact `inventory_raw` bytes and their SHA256, an explicit aware `cutoff`,
and the existing sealed `intake.MemoryArtifacts`. Artifacts are keyed
`SHA256:<lowercase SHA256>`; every referenced blob is independently hash checked.
Existing memory/JSON budgets apply (4MiB per blob, 32MiB total, lexical depth and
token bounds). There are at most 1,000 subjects and 10,000 rows per artifact.

The inventory schema is `supplied-price-incremental-inventory-v1`. It contains
`observed_at`, `available_at`, `collected_at`, and `subjects`. These clocks obey
observation <= availability <= collection <= decision cutoff. Referenced
source/calendar/failure clocks must also precede inventory collection.

Each subject has exactly:

- `request_id`: caller's unique local label; never a security identity.
- `identity`: explicit `security_id`, `issuer_id`, `provider_security_id`, `mic`,
  `calendar_id`, `country=US`, `currency=USD`. No ticker-derived IDs.
- `provider`, `feed`, `adjustment` (`raw` or `split`).
- `window`: `start` inclusive and `end_exclusive`, ISO dates.
- `calendar_sha256`, `prior_sha256`, `current_sha256`, `failure_sha256`.
  Prior/current/failure may be null. Missing source is not verified no-data.
- `delta`: null or `{previous_sha256, current_sha256}` references to existing
  `plan_delta` context objects. Their nonprice research fingerprints are supplied,
  never synthesized by this adapter. Previous reference may be null only when
  no before-price object is supplied.

Calendar schema `supplied-price-session-calendar-v1` has `mic`, `calendar_id`,
`country`, `currency`, complete asserted `coverage` (same window structure),
the three original clocks, and ordered `sessions` of `{session, close_at}`.
Coverage must contain the requested window; MIC/calendar must match identity.
Only listed sessions closed by cutoff are expected. There is no weekday,
holiday, venue, timezone, or close-hour fallback. Hash consistency does not
authenticate the calendar's completeness or exchange origin.

Price schema `supplied-daily-close-inventory-v1` has the exact subject identity,
provider/feed/adjustment/window, three original clocks, explicit `expires_at`,
and ordered `bars` of `{session, close, observed_at, available_at, collected_at}`.
Closes must be positive finite numbers; boolean, missing, duplicate, off-calendar,
pre-close, future, or conflicting rows refuse. Original row clocks must precede
the envelope's corresponding clocks. This is an explicit normalized supplied-byte
contract, not a parser for arbitrary provider responses or a Source admission.
Before/after envelope and overlapping-row clocks must not regress; changed
prices with identical original clocks are conflicting vintages and refuse.
Failure schema `supplied-price-source-failure-v1` contains exact subject scope
and three original clocks. No provider error text or credentials are needed.

## Results and reuse

Per request: `FRESH`, `STALE`, `MISSING`, `CONFLICTING`, or `BLOCKED`, with reason,
expected/reusable/missing sessions and an inert collection plan. Reuse is the
union of valid exact-scope prior/current rows, preferring current for overlaps;
`reusable_sources` binds each session to the original artifact SHA256. Only
union-missing sessions enter the plan. Old rows remain reusable as supplied bytes
even when their source expires; any used expired source marks the plan STALE.
No closed session
or missing calendar is BLOCKED, never fresh. One blocked identity does not erase
an independently valid identity's plan. Duplicate requests refuse; duplicate
scopes cannot produce a second valid plan. Nothing is written or invoked.

Market-price fingerprints cover exact scope and session/close values. Accepted
integers/floats use tagged exact-integer-ratio strings before hashing: 100 and
100.0 agree, while distinct large integers and nearby floats remain distinct.
Original source bytes are unchanged; old representation-based context hashes
require a newly supplied matching research context, never an automatic rewrite. Transport
clock-only recollection is not an economic change. Both supplied research
contexts must match security/issuer, these fingerprints, and exact source expiry.
Nonprice fingerprint changes refuse this price-only bridge. The existing API
preserves same-hash expiry/catalyst/correction/source-failure/outcome/retraction
exceptions; an explicit failure requires its supplied source-failure exception.
Missing price sessions block price delta consumption. A partial current snapshot
can reuse prior rows without re-fetching them, but its separate delta stage stays
BLOCKED until a complete supplied current price snapshot/context exists. This
does not request recollection or fabricate a combined Source generation.
Complete but expired data
can produce an expiry review plan; it cannot grant execution or admission.

A price change yields only market/valuation/ER **review requirements**. It does
not calculate ER, rewrite industrial/moat theses, produce BUY/weights, update a
Registry, or change A5/book/orders. Every authority flag is false, validated ER
is null, and identity/source authentication remains NOT_VERIFIED/false.
Existing Source budgets, OWNER records, nonce, checkpoint and expiry remain
outside this local adapter. It cannot authorize collection or activate cron.

## Validation and actual-input boundary

Focused Native invocation: `python -B tests/research_price_incremental_plan_smoke.py`
and the same interpreter with `-O -B`. These are synthetic supplied-calendar and
price fixtures exercising the real existing `plan_delta` API. No provider/Drive
calls. The suite is registered exactly once in `tools/run_pr_validation.py`
`DEFAULT_TESTS`, after the backend connection suite. Actual hosted execution of
this entry must be read from the successor-head CI evidence; registration or a
generic green check alone is not claimed as focused-suite PASS.

The preserved PRICE_UPDATE_STATUS audit (SHA256
`75013b241a4418eb590d07db0bf14d6469f0da105b744289fe4baca7a0ba53cf`)
is historical metadata, not actual admitted rows. It records 78/80 through
Oct16, AVB Aug14, BLD failure, and no all-price-row byte verification. Without
supplied immutable IDs, feed/adjustment, original price bytes/clocks and complete
calendar bytes, those cases remain BLOCKED in the local trace. Cache file count
1047 versus target count400 cannot certify freshness or coverage.

Reusable lesson: a missing source/calendar prerequisite must not become a market
risk signal, zero/no-data, a fresh price, a new collector, or repeated full-history
fetch. Preserve original evidence and identify the specific missing connection.
Actual Source/PIT rights, present-day freshness and economic admission require
their existing independent evidence; fixture PASS does not establish them.
