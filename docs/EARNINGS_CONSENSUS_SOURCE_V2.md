# Earnings / consensus H1 source admission V2

Task: `R1000-H1-EARNINGS-CONSENSUS-SOURCE-ADMISSION-V2-20260928`.
Original base: `3d76ee345a3fda8c242435d70aae07f6475c8221`.
Current-master reconstruction base: `e97a8509982335ffd8731b5faa38df89bb4f1cf1`.
Refs #450 / #448.
#453 (`55661460228674e56f1e15bb277179a1e64acd6f`) is design reference
only; its Layer-B/replay work is not ported. #533 is read-only and unchanged.

## Runtime source contract

`tools/collect_earnings_estimates_finnhub.py` calls `earnings_consensus_h1`
for every fixture/live snapshot and recomputes source-only revision diagnostics.
The contract ID is `earnings-consensus-source-v2`.

- Economic identity: issuer_id + security_id + metric + fiscal_period_end +
  period_type + accounting_basis + currency + share_or_ADR_unit. FY1/FY2 are
  sorted dated annual periods ending on/after collection, never identity.
  Historical/quarterly/undated records remain canonical observations but do not
  masquerade as forward annual views. A year-only label is not a fiscal end.
- Provider metadata is preserved through normalization. Missing identity fields
  are null/UNKNOWN_IDENTITY; no ticker-to-security/ADR mapping, USD, accounting
  basis, fiscal end or period type is invented. **Current vendor responses may
  lack this metadata; observed levels are archived but revisions stay null.**
- Missing estimate, no record/coverage, unsupported access and fetch failure are
  distinct per-metric statuses derived from the relevant estimate endpoint.
  Recommendation endpoint failures cannot relabel estimate coverage. Explicit
  zero is a value. Nonfinite, boolean and malformed
  numerics are null. Recommendation counts require complete nonnegative counts.
- `analyst_recommendation_balance` is separate from
  `est_eps_revision_breadth`; the latter stays null with
  UNKNOWN_NO_ANALYST_REVISION_SOURCE. Aggregate consensus change is not breadth.
- EPS 30/90-calendar-day and revenue 30-calendar-day changes use the latest
  available vintage at/before each boundary, exact identity and same provider.
  Prior FY2 may match current FY1 by identity. A pure roll, conflicting vintage,
  missing identity/value or zero denominator yields null, never a zero revision.
  Provider corrections are new available versions, not retroactive edits.
- Availability is the maximum of exact timezone-aware observed_at, first_seen_at,
  collected_at, strategy_available_at and provider_published_at when supplied.
  A missing provider publication time stays null; date-only publication is not
  upgraded to midnight knowledge. Explicit date-only/malformed publication
  metadata is retained as raw evidence, marked UNKNOWN_PUBLICATION_PRECISION,
  and blocks timestamp admission; it is not treated as absent metadata. Date-only decision cutoffs mean UTC start of
  day conservatively. Exchange execution/calendar decisions remain out of scope.
- `--fetch-date` must equal the actual UTC collection day, including fixtures
  (tests freeze the clock). It cannot backdate availability. Same-day versions
  are retained, exact snapshot-version duplicates are idempotent, and corrupt
  archives fail rather than overwriting accepted bytes. Legacy date-only rows
  remain archived but are excluded from the regenerated V2 signal artifact.
- Source summary includes observation ranges, identity statuses, normalized
  consensus-content SHA256 and snapshot-version IDs. The existing archive
  manifest binds summary/files to workflow run/source SHA; no new scheduler.
- Current provider surprise is unverified diagnostic metadata. Canonical surprise
  and streak remain null. `frozen_pre_event_consensus()` selects an exact identity
  and provider strictly before announcement (equality is excluded), returns the
  selected version/hash, and rejects ambiguous same-time values. The latest
  missing/absent vintage invalidates older consensus. Both current and prior
  same-time conflicts are quarantined without input-order dependence.
  `earnings_surprise()` requires that frozen identity and cutoff. Nothing infers
  announcement time from a fiscal-period date or uses a revised post-event average.
- `causal_event_id()` identifies one issuer/period/exact announcement. Verified
  linked surprise/revision/rating/target-price/news reactions group into one
  independent event via `dedupe_causal_events()`. Unlinked reactions are not
  counted; the collector leaves causal identity UNKNOWN without an event source.
- Attempted uncovered securities stay in diagnostic snapshots and the existing
  canonical universe/queue. Provider failures are not security removal signals.

## H1 / H2 isolation

V2 diagnostics have `h2_eligible=false`. Existing confirmation and overlay
readers reject V2 at source admission. Confirmation flags remain false and the
compatibility multiplier is 1 (no score effect); nullable source metrics are not
neutral-value imputations. No selector/ranking formula, RS 20/30/30/20, weights,
ER, target, paper ledger or broker code is changed. No workflow is dispatched.
Separate H2 admission must deliberately connect an approved source consumer.

## Audit and data limits

CURRENT_STATUS operational snapshot is still dated 2026-08-23; its later
architecture addendum is not current holdings or data evidence. Issue #450 is
open. #453 is open/draft and did not replace the live collector.

Guidance remains `CLOSED_SOURCE_PRECISION_OR_RECALL_GATE`: precision 81.25%
vs required 90%, recall 92.86%. See shared lessons and do-not-repeat registry;
no heuristic, threshold or known-failure special case is changed.

Drive readback on 2026-09-28 KST:
- Run `36318688815`, job `108618187308`, conclusion FAILURE in collection step.
- Latest listed execution: `history-36318688815-1`.
- Execution bytes SHA256:
  `10880eb916cd463ec4246f1f7aeb6d2384c40df632a30b4fca148e7aa6c09914` (verified).
- Linked quality bytes SHA256:
  `1c323ff5f765f237bee115c18aee7883a4fcdf1941abef1071c1f5848699863b` (verified).
- Receipt catalog reference:
  `ce0d64e6066018ce04869850c479d2eb944b2864bf16f97788f5e2166dd42530`.
- Receipt commit reference:
  `d2583562f21c56ff939aac235412e5a0dba7102e36360e6ee78e0ab55c82c371`.
- `PARTIAL_COVERAGE`, eligible_for_selector=false, historical_pit_certified=false.
  Catalog/pack bytes are not recertified by this H1 task. No newer verified G0
  PASS was established. A8_RS_SPCR20_V1 and economic experiments remain BLOCKED.

## Verification

Use the existing runner with `--only` (not `--include`, which appends to all
registered tests). `tests/earnings_consensus_h1_smoke.py` exercises the semantic
cases using synthetic deterministic fixtures; the already-registered estimate-revision smoke invokes it in Tier-1 CI.
The protected runner is unchanged from master.
Existing collector, revision, confirmation, neutrality, queue, archive manifest,
workflow and overlay smoke tests are run alongside it. These tests certify source
semantics only; vendor metadata completeness and economic value are unproven.

No vendor HTTP smoke, fullrun, A/B, ledger mutation or H2 dispatch was performed.
Exact-head A6, GitHub CI and final Codex review remain separate evidence gates;
this source document does not self-attest DONE.

## Independent A6 correction evidence

A6 READ_ONLY review of `c46e03e9f79c47f7012f68a42ffab26dbda940e1`
found four P2 defects: frozen-consensus null fallback, current-vintage tie
ambiguity, historical/canonical-only FY view selection, and endpoint-state
conflation. All four received executable regressions and corrections before
requesting the single final Codex review. Date-only publication provenance
was also preserved with fail-closed admission. New head review is required;
the initial A6 result was CORRECTION_REQUIRED, not an approval.

A6 re-review of `bcaf0ee43ed5fe3e4838fd63126c223346e65a63` found
an all-failed live refresh lost provider attribution and could bypass frozen
latest-null invalidation. Failed rows now retain actual attempted estimate
providers from endpoint evidence, so a failed same-security provider observation
invalidates its older consensus without pretending that the fetch succeeded.

CI on the initial head passed 232/233 tests; its sole failure was
`post_publication_protected_delta:tools/run_pr_validation.py`. The protected
runner was restored byte-for-byte to master. The existing registered revision
smoke now runs all 33 H1 cases, preserving CI coverage without changing the
protected verifier, frozen publication, hashes, registry, or review gate.

## Final Codex correction evidence

The single requested Codex review of `40937587e4e40bef34e2807144010e7c104a5571`
reported four P2 findings. Corrections now canonicalize issuer/period before
causal hashing, recompute consensus-content hashes on admission (both revision
sides and frozen consensus), abort collection on UTC day rollover before
archive/checkpoint publication, and require every known availability clock to
precede the announcement before an unknown-publication row invalidates older
consensus. Four focused regressions cover these cases. Existing fixture clocks
are explicit; no vendor calls or economic runs were added.

This correction changed the reviewed head. A6 and CI must verify the new head;
the earlier Codex review is not final-head approval. L0 subsequently authorized
one additional exact-head Codex review after current-master reconstruction,
current-head CI success, A6 CLEAN and resolution of the four threads with
new-head evidence. A new finding stops the task without an automatic review
loop. Draft and the repository merge gate remain blocked until those conditions
are met; no old-head evidence or gate is reused.

## Current-master integration and planning-parent correction (2026-10-03)

The current-master integration preserves the source/H2 boundary and resolves
only the shared lesson-ledger merge conflict. Planning must retain the actual
accepted checkpoint bytes, verify their SHA-256 against the committed collector
transaction, and preserve its acknowledgement and per-ticker selection count
and time. New tickers begin with zero selections and no collection timestamp;
retired tickers may leave the current universe. Copied parent hashes alone are
not evidence. Repeated planning retains the same accepted generation, while a
new collector acknowledgement drops the old embedded planning parent to avoid
recursive checkpoint growth.

The regression probe admitted an advanced selection count (1 -> 99) on the prior
head; the corrected reader rejects it before collection. Tests also cover reset
counts, changed clocks/acknowledgements, duplicate identities, boolean counts,
missing/tampered parent bytes, fresh ticker admission and actual repeated plans.
Staged file fsync uses a writable descriptor on Windows as well as Linux.
Windows synthetic tests use immediate process exit without Python cleanup and
mock POSIX directory fsync; Linux CI uses real SIGKILL and directory fsync. Native
test success does not certify Windows power-loss durability or live vendor,
Drive, historical PIT, H2, paper, broker or economic acceptance.

Independent integration probes also reproduced publication acceptance after
downgrading the transaction schema and removing its final marker, omission of
all binding hashes with corrupted signals, and an incomplete cache-only restore.
Publication now requires the supported V2 transaction and its matching committed
marker. Snapshot/signals hashes are mandatory; acknowledged collection also
requires checkpoint/queue hashes. The restart reader applies the same mandatory
hash contract. Both cache save and restore retain the bound summary and queue;
an offline test copies only the actual workflow cache paths and runs the planner
against that restored transaction. Older incomplete cache evidence stays blocked.

## Rollback restart correction (2026-10-03)

Hosted Codex review of `8c5ab3187a8fa290e59abe635ddfe36632096fb1`
identified one P2 rollback-admission defect. The owner's subsequent continuation
authorizes this source correction and completion of the current review gates.
It does not authorize runtime state repair or an unlimited hosted review loop.

The shared collector entry guard rejects a retained `rolled_back` marker before
the planner rewrites state, the collector makes vendor calls (with or without
a checkpoint), or the acknowledgement utility advances counts. A rollback
manifest stays non-publishable. Actual injected signal/summary replacement
failures exercise repeated attempts and byte preservation. A hash-matching
generation with a rollback marker still blocks; changing its label cannot waive
a corrupted payload. Only restored, fully bound accepted evidence can pass.
New-head independent QA, CI and authenticated review remain required.

The acknowledgement utility requires an explicit archive root because supported
checkpoint paths may reside elsewhere. Both archive and checkpoint-parent
markers are checked before state preparation or writes. Independent correction
QA reproduced the split-directory count advancement; the actual rollback test
now exercises this layout rather than only colocated state.

## Workflow and provider-boundary corrections (2026-10-03)

Authenticated review `5400604765` of
`9de5aedebfef7a446861544ac0ebbee33fbef3fa` found four additional defects.
Separate exact-head probes reproduced all four; earlier rollback-only CLEAN
and Linux 232/232 evidence do not approve these newly identified paths.
The owner's direct instruction to continue autonomously authorizes completing
the source correction and required review gates. Runtime repair, vendor calls,
Drive writes, portfolio certification and protected dispatch remain separate.

A no-collection run keeps the accepted collector producer identity and summary.
Its manifest separately records the current run and verifies the current
zero-selection plan: matching run IDs, checkpoint/queue output hashes, complete
unselected queue identities/counts/clocks, and the actual hash-bound accepted
parent bytes. Status/count hints cannot waive transaction, marker, snapshot,
signals, acknowledgement or parent checks. A stale or due plan blocks.

Independent correction QA of `c1781a3f` also reproduced a truncated no-op:
removing the same ticker from checkpoint and queue passed their mutual equality
while the canonical CSV still named it. No-op publication now binds the actual
current canonical CSV hash and its complete ticker set to both planning records
and queue state. All declared counts must match the trusted expected universe
count (993 in the workflow). Rebinding a smaller universe cannot downgrade that
contract. A real current-universe replacement is allowed; accepted parent
membership is not forced onto the current queue.

Manual collection explicitly plans only its resolved request tickers before
calling the vendor. Fresh requests create checkpoint/queue state; later requests
preserve all previously acknowledged counters and clocks. Canonical planning
also carries verified manual state even before canonical-universe metadata
exists, rather than resetting that accepted collection history.

Configured Drive restoration synchronizes only into the local archive with
checksums, removing cache-only members. A missing/unavailable configured archive
or a failed bound component copy blocks the restore step. Manifest publication
requires successful restore and ticker resolution; forward paper prerequisites
require manifest success. No configured Drive keeps the supported cache-only
path. Configured Drive requires its authoritative archive to exist.

Revision boundaries choose the latest available observation within the current
provider before comparing fiscal/security identity. Other providers cannot hide
valid same-provider history. Latest same-provider null/identity conflicts and
time ties still fail closed; damaged rows from any provider block the archive.
These are source admission and publication corrections, not economic acceptance.
