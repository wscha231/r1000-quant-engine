# Earnings / consensus H1 source admission V2

Task: `R1000-H1-EARNINGS-CONSENSUS-SOURCE-ADMISSION-V2-20260928`.
Base: `3d76ee345a3fda8c242435d70aae07f6475c8221`. Refs #450 / #448.
#453 (`55661460228674e56f1e15bb277179a1e64acd6f`) is design reference
only; its Layer-B/replay work is not ported. #533 is read-only and unchanged.

## Runtime source contract

`tools/collect_earnings_estimates_finnhub.py` calls `earnings_consensus_h1`
for every fixture/live snapshot and recomputes source-only revision diagnostics.
The contract ID is `earnings-consensus-source-v2`.

- Economic identity: issuer_id + security_id + metric + fiscal_period_end +
  period_type + accounting_basis + currency + share_or_ADR_unit. FY1/FY2 are
  sorted provider views, never identity. A year-only label is not a fiscal end.
- Provider metadata is preserved through normalization. Missing identity fields
  are null/UNKNOWN_IDENTITY; no ticker-to-security/ADR mapping, USD, accounting
  basis, fiscal end or period type is invented. **Current vendor responses may
  lack this metadata; observed levels are archived but revisions stay null.**
- Missing estimate, no record/coverage, unsupported access and fetch failure are
  distinct statuses. Explicit zero is a value. Nonfinite, boolean and malformed
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
  upgraded to midnight knowledge. Date-only decision cutoffs mean UTC start of
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
  selected version/hash, and rejects ambiguous same-time values.
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
cases using synthetic deterministic fixtures; it is registered in Tier-1 CI.
Existing collector, revision, confirmation, neutrality, queue, archive manifest,
workflow and overlay smoke tests are run alongside it. These tests certify source
semantics only; vendor metadata completeness and economic value are unproven.

No vendor HTTP smoke, fullrun, A/B, ledger mutation or H2 dispatch was performed.
Exact-head A6, GitHub CI and final Codex review remain separate evidence gates;
this source document does not self-attest DONE.
