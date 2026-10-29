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

A same-logical-run collector exception before mutation can leave a prior
accepted transaction fully hash-valid. The workflow therefore also requires
collector-step success when collection is required; transaction validity alone
cannot waive a failed prerequisite. A verified no-collection plan intentionally
skips the collector. This is separate from the retained transaction's validity.

Revision boundaries choose the latest available observation within the current
provider before comparing fiscal/security identity. Other providers cannot hide
valid same-provider history. Latest same-provider null/identity conflicts and
time ties still fail closed; damaged rows from any provider block the archive.
These are source admission and publication corrections, not economic acceptance.

## Whole-archive and immutable Drive generation correction (2026-10-03)

Authenticated review5401049108 of16eadf6b found two remaining publication gaps.
Independent frozen-source probes reproduced corrupted/unreadable older snapshots
passing a real no-op while collection correctly blocked, and four partial Drive
uploads reporting success before a mixed generation failed restore admission.
Earlier targeted CLEAN and Linux232/232 evidence are preserved but cannot approve
these newly identified paths. Source correction continues under the owner's
direct continuation; no runtime repair, migration or Drive operation is granted.

Every no-op publication validates all estimates_*.parquet files with the same
positive V2 content/schema and complete legacy admission used by the collector.
Unreadable, unknown, empty or damaged snapshots block. A bound planner applies
this guard before rewriting canonical universe/checkpoint/queue state. Missing
V2 fields cannot silently downgrade a damaged row into legacy compatibility.

Bound Drive source publication uses SHA-addressed immutable generations under
research_state/earnings_estimate_generations/<generation_id>. Payloads contain
the complete archive, signals and earnings daily outputs. A canonical file
census binds every relative path, size and SHA256; missing/extra members, unsafe
paths, symlinks, stale publication bindings and invalid transactions block.
The staged generation is freshly downloaded and validated before generation.json
is exposed as its commit marker. That manifest is read back too. Only then is
research_state/earnings_estimates_generation_head.json written and read back.
Transfer errors propagate. Payload failures leave the prior accepted head intact;
unreferenced partial generations remain outside accepted authority and may be
completed only with identical content. A post-head readback failure is reported
as failure even when the remote pointer already identifies a complete generation.

Restore downloads the selected complete generation into temporary storage and
checks its full census, semantic archive and current/parent transaction before
replacing the three owned local source components. A failed local installation
blocks the step; a later restore rereads the complete remote generation. Flat
Drive layout is a compatibility input only when head absence is confirmed.
Malformed heads, failed listings/transfers and invalid generations cannot fall
back to stale flat Drive or local cache. Existing workflow concurrency serializes
earnings writers. Auxiliary research/paper copies are outside this source
generation and are not certified by source success. Existing consumers must
restore through this generation contract; old flat paths are not a current head.

Independent native-rclone correction QA also rejected state-dependent no-op
admission: an accepted selected queue was incorrectly allowed when only the
publication's collection_required/run_id hints were changed. Every false
collection-required value now requires the full verified no-collection plan,
regardless of reader state. True requires accepted collection and matching
producer. A declared no-op cannot waive its proof or move the remote head.

The accepted generation authority is outside data_pit/events because the
independent free-data daily workflow restores and uploads that entire tree.
A stale validation upload cannot overwrite the newer earnings head or immutable
payloads. Flat event paths remain legacy compatibility inputs; coverage readers
using those paths do not certify the current accepted generation. The regression
preserves a validation view, publishes a second generation, uploads that stale
event tree and verifies the second head and restored producer remain current.

Unknown-publication invalidation follows the exact issuer/security/metric/fiscal
identity across ticker changes. A renamed security's current/newer pre-event
unknown vintage blocks an older exact consensus. Known-ticker unresolved or
conflicting identities remain conservative blockers. Older superseded vintages,
post-event collection, another provider and unrelated identities on a new ticker
do not invalidate the requested consensus; exact renamed observations still work.

## Explicit legacy baseline preparation (2026-10-28)

Run37100587799 at30915e05c1ffe3cecd2c46b229af20844e514f3d predates the
collector transaction marker. Its successful Actions conclusion is not a
current transaction receipt. Artifact11266510471 is4478824 bytes with SHA256
314f3560b512bd5f8762d049a3781251d1ecb5099df155a3422dd3e201503a91.
The independently retained Drive comparison matched seven key files, but did
not establish the current live Source head or authorize an overwrite.

The existing generation helper offers an explicit local preparation operation:

```text
python tools/earnings_estimate_drive_generation.py prepare-legacy --legacy-archive <held-original.zip> --output-dir <new-local-directory>
```

Only that pinned artifact is supported. The operation validates all63 snapshot
files and checkpoint/queue consistency, preserves the993-row queue and70 Source
files byte for byte, and excludes unrelated paper/price outputs. It requires a
new directory and refuses arbitrary ZIPs, unsafe paths, duplicate members,
transaction markers, damaged snapshots and split acknowledgements. Its receipt
is a prepared handoff, not a Source publication. Failed preparation has no valid
receipt; preserve diagnostic files and use a new output directory on retry.

No collector marker is manufactured, and no original Source clocks, checkpoint
counters, manifest or summary are rewritten. The original partial coverage
(10 of60 attempted tickers with forward estimates) and historical admission
limits remain. The normal current-state guard continues to return
missing_collector_transaction_marker; publish/restore and daily planning do not
consume this preparation as an accepted generation. No network or provider call
is performed by preparation.

The next Source owner must separately verify the live accepted generation/flat
base, full archive inventory and retained queue, plus provider purpose/rights,
cohort and budget. A bounded genuine forward collector transaction under that
explicit recovery contract may then establish new current transaction evidence
through the existing writer. Publication requires the unchanged manifest and
immutable-generation readback gates. This preparation neither dispatches that
collection nor closes the automatic-recovery, current-data or A3/A8 admission
requirements. Never blindly rerun the failed daily workflow against this copy.

### Opt-in forward transition through the existing collector

Native preflight confirmed that ordinary manual planning also returns
missing_collector_transaction_marker on the preserved legacy baseline. No
existing manual flag bypasses that refusal. The collector therefore accepts
an explicit --legacy-baseline-receipt only together with manual planning,
nonempty attempt identity, current UTC date and1-5 retained queue tickers.
Fixture-directory collection is forbidden in this entry. Scheduled workflow
inputs and the default planner are unchanged; they do not opt in automatically.

The receipt must bind the exact prepared directory/component paths and current
helper code. The verifier revalidates the pinned original ZIP, all63 snapshots,
and the candidate's entire70-file inventory before any planning write. Changed,
relocated, already consumed, extra-member or forged candidates fail before
provider calls. The local plan preserves original checkpoint counters/clocks
and selects only the explicit cohort; it is not a current accepted transaction.

After a real forward response the existing collector stages the new snapshot,
signals, checkpoint, queue and summary. Only its normal pending-to-committed
transaction creates a new collector marker. The new summary retains the old
artifact, inventory/checkpoint/queue/summary hashes and blocked legacy status
under legacy_baseline_handoff. Older snapshot bytes and clocks are unchanged.
Existing data quality, PIT, immutable-publication and consumer gates still
apply; scoped source completion is not full-universe coverage or ER admission.

The explicit receipt is single-use for entry: after planning/collection its
bytes no longer match that pristine baseline. A failure leaves an unpublished,
unaccepted candidate and must be diagnosed before another bounded attempt.
Pending/rolled-back markers retain the existing repair requirement. A completed
new transaction uses ordinary current-state verification/publication, never the
legacy entry again. The old ZIP remains the immutable original in every case.

This code path has isolated provider-double transaction tests; actual provider
collection and publication remain NOT_RUN until the live-base, rights, cohort,
budget and writer authorization in the recovery contract have been verified.

### Read-only inspection with the actual Actions connection

PR691's protected integration does not prove that a Native Drive connection
and the configured Actions connection address the same Source. Native provider
keys are absent; replaying the whole daily workflow would also involve paper
paths. Do not use an intentionally invalid collection date to probe that job.

The existing daily workflow has an explicit manual read_only_source_preflight
input, default false. True runs only source_preflight; the entire archive job
is skipped. Normal scheduled/manual defaults retain their previous archive
behavior and global writer concurrency. The preflight job loads only the
existing Drive read credentials, never provider keys, and downloads the exact
retained Actions artifact11266510471. Its download blocks if the artifact is
expired/missing; preparation rejects changed bytes. There is no alternative
artifact/cache fallback in this diagnostic job.

The operator supplies expected_archive_folder_id from an independently grounded
connected Drive read. preflight-legacy compares it with the actual folder ID
resolved through the Actions Source connection. It refuses a current generation
head rather than falling back to flat history. With confirmed head absence
in that configured view, it checks the exact flat archive inventory and bounded
component sizes, reads Source bytes only into a new absolute local directory,
and compares all70 Source files to the pinned original. Archive metadata and
head absence are checked again after the read. No cache, consumer restore,
collection, marker creation, publication or Paper consumer/restore/mutation is
performed. Whole-ZIP CRC validation may visit unrelated archived members; only
Source files are extracted, and archived Paper bytes are not consumed as state.

The job uses at most15 minutes, remote-to-local copies with existing checksums,
one transfer/checker, a16MiB archive read cap and2MiB component caps. These are
diagnostic I/O bounds, not a provider collection budget. The diagnostic receipt
retains the actual repository/code/run/attempt, folder binding, Source hashes
and original clocks/status. Failure diagnostics are preserved with always();
only small JSON receipts are uploaded, not another raw Source/Paper archive.

LEGACY_SOURCE_BYTES_VERIFIED_READ_ONLY means that this configured connection
observed matching legacy bytes. It is not an atomic snapshot, publication lock,
current provider entitlement/freshness, Source/PIT admission or recovery grant.
Actual provider rights, budget, current parent and named forward attempt remain
separate prerequisites and must be reconciled again before mutation. Existing
collector/publication/consumer checks are unchanged.


### Bounded MU Source-only forward mode (2026-10-28)

The existing workflow has an explicit source_only_forward option, default false.
It excludes the entire archive job, including Paper, cache restore/save, legacy
flat sync and market/session processing. The original schedule and ordinary
manual mode are unchanged, as is the global durable-writer concurrency group.
The read-only option remains read-only; selecting both special modes fails
before credentials or Source I/O. No new collector, scheduler, approval Registry
or repository enablement variable is introduced.

The existing helper's check-forward-contract checks fixed single-execution
information and its exact --contract-sha256. This byte hash is an integrity pin,
not an approval mechanism or a supplier-rights certificate. Actual execution
remains the existing A0/owner decision under the named recovery scope. No live
execution information, account evidence, budget grant or validity window is
issued by this code change.

The closed earnings-source-bounded-forward-contract-v1 information names MU
only, FMP only, one explicit FMP_API_KEY or FMP_API_KEY2 selection, the existing
repository/master SHA, all four workflow/helper/collector/manifest code pins,
the original archive folder and full legacy inventory SHA, absent current head,
private noncommercial purpose, original account/entitlement/budget references,
and explicit UTC issued/expires times (at most24h). References must be grounded
by the execution owner; their presence is not account binding or licensing proof.
Missing/wrong code pins, null/ambiguous budget, another symbol/provider/key,
expired information, non-master context or a GitHub rerun attempt stops before
provider/Drive access. The workflow also checks the selected key name; there is
no automatic account fallback. The real account, entitlement, remaining quota
and approved window are currently NOT_RUN/UNCONFIRMED prerequisites.

The budget fields are provider_gets, provider_response_bytes, drive_processes,
transfer_reservation_bytes and active_seconds. Their code ceilings are1 GET,
2MiB response,64 rclone attempt reservations,128MiB transfer reservation and600s;
the enclosing job stays15min. These are refusal ceilings, not newly granted
allowances. A smaller approved value wins. Failed/uncertain transfer bounds are
retained rather than reset. drive_processes counts conservative reserved process
attempts, not backend HTTP requests; drive_http_requests stays null. Do not claim
actual Drive API-cost reconciliation from this meter. Unresolved actual account
or campaign cost scope must be settled before dispatch, not inferred from caps.

forward-legacy freshly reuses preflight-legacy to check the namespace, head
absence and all70 original files. Its existing prepared candidate is handed to
the unchanged collector with --legacy-baseline-receipt and manual MU planning.
Only the selected FMP estimate endpoint can be called, once; optional Finnhub,
Alpha Vantage, redirects, paging, automatic retries and other ticker/provider
paths are excluded in this finite wrapper. The existing parser, positive archive
validation, genuine pending-to-committed transaction, queue acknowledgement,
quality and archive-manifest checks remain authoritative. Vendor failure,
missing estimates, errors or incomplete quality cannot publish, even where the
ordinary collector's diagnostic exit code is0. Old63 snapshots and the original
Oct3 partial status/clocks are preserved; no historical marker is invented.

The exact old Source is checked again before payload publication and immediately
before head publication through the existing publisher. This is not an atomic
remote snapshot or a new CAS protocol: global single-writer operation remains
required, and any foreign writer or changed Source/head stops execution. New
payloads and generation markers still require complete fresh readback before
head advancement. Partial payload writes are unaccepted. Failure at/after the
head write reports PUBLICATION_OUTCOME_UNCERTAIN_STOP rather than pretending the
old head is necessarily unchanged. Diagnose it; never blindly rerun the job.

Every local attempt directory must be new. A consumed candidate cannot reenter
legacy preparation, and workflow run_attempt must be1. A separately authorized
new attempt must reconcile the actual prior outcome, head, source and cumulative
cost first; this code does not create a cross-dispatch authorization ledger or
allow a failed grant to reset costs. Successful publication means a complete
research Source generation only; Source/PIT admission, current A3/ER, economics,
Paper and portfolio authority remain false/separate.

Only forward_result.json and attempt_meter.json enter the diagnostic artifact.
Provider response bytes and collector logs remain private local attempt material;
original data, credentials and account references are excluded from that upload.
This change is T2 implementation/synthetic verification only. Actual provider,
Drive write, collector dispatch, Source publication and Paper remain NOT_RUN.


### Exact-head review correction: provider stream bounds

Hosted Codex review of706ebca identified two P2 defects. A Requests timeout is
an inactivity timeout; slow delivery can keep a65536-byte read blocked past the
total window. Also, Session.send constructs response._next even with redirects
disabled, consuming a redirect body before a later status check can meter it.
Both old-head findings remain evidence; that head is not final approval.

The bounded Source provider call now uses an independent main-thread POSIX
ITIMER_REAL deadline spanning headers and the complete body. It refuses a foreign
active alarm and always clears its own timer/restores the previous handler.
Actual execution is Linux/POSIX only. Windows Native integration doubles replace
this guard explicitly and test unsupported-host refusal; they do not prove POSIX
interruption. Linux CI additionally exercises a genuinely blocked body, existing
alarm preservation and an optimized child with non-removable checks. Preparation
I/O uses a controlled monotonic fixture, so it cannot consume the short provider
timer before the tested phase.

A first response hook rejects/closes every non2xx response before Requests can
read a redirect body. HTTP failures retain their actual status for the unchanged
collector's entitlement/error classification. Tests use the real Session.send
and redirect machinery with only HTTPAdapter.send doubled. A3MiB redirect raw
body must never be read. Known partial streams keep the full approved response
cap reserved; observed yielded body bytes are not a wire-byte measurement.
Actual provider/Drive collection/publication remains NOT_RUN.

Observed yielded body bytes are persisted before refusal, including an over-cap
chunk: a64-byte cap/65-byte first chunk reports65, exceeded=true and complete=false.
The full cap reservation remains. Zero observed bytes on an incomplete stream
is not evidence of zero wire cost; no new wire-cost guarantee is claimed.

The MU wrapper checks every explicit response symbol/ticker before normalization:
AAPL or conflicting/nontext declarations are refused, even at a MU request URL.
Absent declarations remain REQUEST_TICKER_ONLY_UNVERIFIED. An explicit MU match
is ticker evidence only, not issuer/security identity certification; the result
keeps provider_response_security_identity_verified=false and admission=false.
