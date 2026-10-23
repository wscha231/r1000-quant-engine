# ETF116 dated research history and private view

TASK_KEY: R1000-ETF116-FINAL-INTEGRATION-20261018. RESEARCH_ONLY.
Stacked Draft646 reuses the reviewed H1 calculator and H2 private connection.
Accepted master0b02c6a is included through H1becad287; Source files are unchanged.

## Date and calculation contract

`tools/etf116_dated_history_h3.py` consumes the existing offline input contract
and invokes `run_etf116_offline_research_h1.run` on the exact consumed bytes.
There is no second calculation engine, provider call or scheduler. Each dated
snapshot has116 tickers ×8 horizons (1/3/6/12/24/36/60/120months), the current
consecutive-session daily return, and the existing CAGR/Sharpe/Sortino/MDD/
volatility/SPY results and refusal reasons. Full daily return histories are not
duplicated in every dated summary. Existing RF release-date and NAV/market basis
rules remain in the calculator. Missing values remain null, never zero.

The history directory contains immutable `YYYY-MM-DD.json` snapshots linked
by the prior snapshot hash and `objects/<SHA256>.json` exact source-input bytes.
Hashes bind input, calculator files, candidate receipt, frozen116 identity and
computed UTC clock. Calculator identity also binds the unchanged Reader/legacy
NYSE helper files and Python/pandas/pandas_market_calendars versions; a calendar
dependency change cannot silently reuse the same-day candidate. The source input
is materialized from approved Reader data;
it is not a substitute for the Reader's original provider objects/manifest.
Computed time is distinct from source/session/publication time. Session must
not follow the decision's UTC date, and decision must not follow computed time;
stored clocks are rechecked against the original input before reuse. A same-session
identical input/code is GET-only local reuse, retaining its original clock.
A changed same-session input/code conflicts; a new session must immediately
follow the latest stored date in the caller's verified NYSE calendar.
This does not independently certify the caller's calendar or source rights.

Files use bounded regular-file reads, duplicate/nonfinite JSON refusal, a local
advisory writer lock and exclusive atomic publication. A foreign writer that
ignores the lock can cause refusal but cannot be silently overwritten. Existing
snapshots and their input objects are hash-checked before append/reuse. No latest
pointer, mutable accepted catalog or trading account is written.
The existing H1 shared-metadata preflight also runs before creating a history
directory/date. Even an empty all-blocked pre-close packet refuses; it cannot
reserve the date and conflict with a later post-close input. Reuse/publication
revalidates the original shared schema/session/decision/actual NYSE grid.
Reads open nonblocking before fstat so named pipes cannot wait for a writer.
Recursive JSON becomes a stable input refusal without raising the recursion
limit. Both CLIs return a sanitized refusal; private-view local parsing precedes
exclusive output reservation so malformed input cannot leave an empty receipt.

```bash
python tools/etf116_dated_history_h3.py --input INPUT.json \
  --frozen research/etf116_v1/frozen_tickers.txt --history-dir PRIVATE_LOCAL_HISTORY
python tools/etf116_private_history_view_h3.py \
  --snapshot PRIVATE_LOCAL_HISTORY/2026-10-16.json --output UNIQUE_VIEW_PLAN.json
```

The second command is local plan preparation only and needs no OAuth. Its929
literal rows include one header plus116×8 period rows, explicit session,
window anchor, RF/benchmark refusal status, snapshot hash and
`RESEARCH_CANDIDATE_NO_AUTHORITY`. Inputs/snapshots are bounded
to128MB locally. Source input bytes are archived losslessly in a deterministic
single-member ZIP; the receipt separately binds original bytes/hash and stored
ZIP bytes/hash/codec. Fixed ZIP metadata is not a source/publication clock.
Existing OwnerDrive's16MB stored-object limit still applies and blocks oversized
archives. The capacity fixture verifies a26.1MB byte roundtrip, not actual116×10y
source coverage, numerical E2E completion or production capacity.

## Private archive/view connection

The optional `--publish-private` path also requires `--source-input`,
`--probe-receipt` and `--private-history-folder`. It requires explicit
`ETF116_PRIVATE_METRICS_AUTHORIZED=true`, the existing exact-HEAD Actions manual
binding, and existing OwnerDrive OAuth. It never falls back to another principal.
It is not connected to an enabled Actions job in this Draft.
Only the existing serialized manual gdrive_smoke_test.yml private-probe job is
an allowed execution origin. Workflow ref/SHA/job and exact committed/local YAML
bytes plus fixed concurrency(group=etf116-private-sheet-probe,cancel=false) are
verified. Any tracked worktree difference from that HEAD refuses, including the
imported history/clock/calendar validators. A RUNNER_TEMP fixed-sheet flock covers the entire metadata/archive/view
sequence, preventing overlapping processes inside the same job. Different runners
are serialized by that existing Actions group; other workflow origins refuse.

Before any archive/view write, a successful Actions CREATE_AND_READBACK probe
receipt must match the current owner and fixed private Sheet. Its actual27
literal cells must still match via independent GET-only reconciliation. A
missing marker cannot trigger a new probe write. A blocked receipt cannot pass.
This verifies private research-view access only, never source/PIT/economic rights.

The destination folder must already be a private owner-only child of the fixed
ETF root. Exact hash-name objects are reused only after complete bounded listing,
owner/parent checks and byte readback. Multiple matches, incomplete/paginated
inventory or uncertain POST fail; no retry or cleanup is performed. New objects
reuse OwnerDrive.write and its readback. Original input bytes and dated snapshot
receive separate archive receipts. Original provider-byte retention remains the
approved Reader/Source responsibility.
Before any archive or Sheet request, source schema/scope/session/decision/hash
must match the dated snapshot. Rehashing a changed snapshot date cannot relabel
the original input's date or collection/decision clock.
Before publication the current declared calculator/runtime fingerprint must also
match. The existing H1 calculator rederives the candidate from the exact source
bytes; both candidate receipt hash and the shared daily/horizon projection must
equal the snapshot. Editing CAGR and recomputing only a self-hash cannot pass.
This offline verification adds no provider collection. Older calculator identity
requires separate revalidation and cannot be silently published as current.
Local view plans alone verify shape/self-integrity and grant no publication.

Because Drive names are not unique, every new archive CREATE first obtains a
permanent atomic3x3 Sheet reservation keyed by its stored content hash. Only a
fresh reservation may CREATE. A previously reserved but absent object is a
manual-reconciliation blocker even on another run; no second CREATE follows an
uncertain/late-applied POST. A confirmed unique exact object can be GET-reconciled
and reused. Existing source/snapshot bytes remain independently verified. All
approved publisher invocations follow the protocol; uncoordinated external owner
clients cannot be made unique by Drive names and duplicate inventory refuses.

This fixed copy is a bounded preview: at most16 dated views,32 archive claims and
1,000,000 allocated cells. Actual metadata and the new view+claims allocation are
checked under the same lock before any archive CREATE. Existing exact view
reconciliation consumes no new budget and may not repair missing archives by
writing. Capacity exhaustion returns PRIVATE_VIEW_ROTATION_REQUIRED before
archiving. No user tab is deleted/cleared. Long-running daily deployment needs
separately reviewed approved rotation/reused-view policy and activation; the
bounded private preview is not claimed as that deployment.

The Sheet view reuses H2's atomic addSheet+updateCells path. A date/snapshot hash
derives a new explicit tab name/ID in the fixed private copy. Existing exact
tabs allow readback only. Foreign ID/name collisions fail the entire batch;
no existing tab update/clear path exists. The original research Sheet and
connector proof tab are never writable. An ambiguous applied result is a manual
reconciliation blocker, not automatic retry authority.

## Actual execution and remaining gates

One user-approved existing-workflow probe ran at exact6cdf6e3:
run39191210516/attempt1, job117864228518. Local probe contracts passed15/15 in
normal/-O inside Actions. The actual access step refused with
`OWNER_OAUTH_ACCESS_BLOCKED`; artifact12160610537 is a BLOCKED receipt, ZIP digest
4d3b29caca91893178e0ebbe70397e517e44c20f099d4a065d99b805a5375ab6.
That historical code suppresses detailed access exceptions, so the underlying
OAuth/quota/private-parent failure is not established. No successful write or
readback is claimed. It was not rerun. The new probe diagnostic records a fixed
failed stage and allowlisted category, never credentials or HTTP/error text.
Any next real invocation needs reviewed exact-head evidence and separate scope.

The original Sheet has106/116 existing research horizon rows; accepted automated
daily TR remains0/116. Existing72 raw SIP bars and175 issuer SPMO NAV references
cannot fill that TR gap. No original Sheet metrics were edited. New date tests
are synthetic; two positive real-session TR trials remain NOT_RUN.

The existing free-data cron remains23:30UTC weekdays (08:30KST Tue–Sat). Its
isolated ETF job stays literal-false and its source guard remains terminal.
Weekly top10 cadence remains the existing planner. Once upstream receipts,
private Actions readback, real-session trials and exact-head review gates pass,
that existing job can call these CLIs in chronological session order under a
separately reviewed activation change. No new cron, fullrun, target, paper,
broker, protected merge or automatic-refresh activation is included here.

Stored computed time must not exceed a trusted evaluation instant. History append uses its captured current/replay clock; local plans and private publication default to UTC now. Publication captures it once for plan and rederive checks and retains it in the receipt. JSON and environment clock claims cannot override it. Only a caller-owned aware API argument supports offline replay/tests; the CLI exposes no override. Source decision<=computed<=evaluation also blocks a rehashed future decision.

The captured evaluation clock also reaches shared source metadata validation and calculate_candidate→H1 run. Explicit replay does not accidentally fall back to current time in a nested runner; CLI input cannot choose this clock. Evaluation time stays outside the deterministic H1 candidate hash.
