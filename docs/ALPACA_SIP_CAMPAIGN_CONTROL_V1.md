# Finite private SIP campaign control

## Separate external discovery input (same finite resource family)

`r1000-sip-external-cohort-authorization-v1` adds a bounded ticker-only CSV
to the existing collector/controller and existing workflow. It does not replace
`data_static/iwb_holdings_seed.csv`, weaken its900..1500 guard, append names to
the original1009 queue, or turn another supplier's holdings count into Alpaca
completion. The explicit CSV order is retained. Maximum500 names, maximum32
new names per price batch, with a boundary at each128 examined names.

The typed `external_cohort` contains `scope` (capture task, distinct namespace,
exact input SHA256), original `input_csv` bytes as UTF-8, intake manifest SHA256,
an actually verified owner-receipt dedupe report SHA256, the exact prior spent
authorization, zero or one prior external epoch, and an immutable OWNER consent
reference. A prior epoch must be complete and its input disjoint before the next
epoch. The controller also refuses the original144 already examined names.
Remaining same-window cache/receipt reconciliation is required before preparing
that consent; ticker lists, metadata or a caller-supplied hash alone do not prove
reusable prices. A later market-cap cohort requires actual dated ranking bytes,
ADR/common-share identity reconciliation, ETF exclusion and receipt dedupe;
there is no automatic universe discovery or ranking API call in this path.

`A1_SIP_EXTERNAL_COHORT_CONSENT` binds the exact authorization/input/source pins,
prior epoch identities, actual owner/key bindings, original checkpoint/event and
spent usage, and existing9GiB/12h cumulative amendment. It records the human's
personal historical capture request, **supplier_rights_verified:false** and
**budget_reset:false**. This is execution consent, not invented account terms,
historical SIP entitlement, PIT, commercial rights or investment admission.
It must truthfully refer to the actual human-authorized input and verified
dedupe report; agents may not fabricate owner evidence. Its entire comment body,
author, creation/update clocks and typed record are hash-bound in all new meters.
Editing it invalidates the next import/dispatch/worker. No legacy permission
record is relabelled as consent for additional names.

The SAME `r1000-993-20261015-` nonce prefix and workflow history floor are kept.
Every canonical original, discovery, metadata, price, failed and future epoch
run consumes the shared2000 provider GET /50000 Drive requests /9GiB transfer
reservation /1GiB storage /12h active /40 dispatch budget. The original first
canonical clock and48h expiry do not restart. Legacy v1/v2 controllers see the
new records and refuse auth/source drift rather than silently ignoring spending.
Each new allowance subtracts **all** prior family usage, not just its namespace.

The external host requires `--cohort-input`, `--budget-state-dir` and the existing
`--predispatch-recovery` bundle in addition to its own `--state-dir`. The latter
is fixed to `budget-state-dir`'s parent plus `external-cohort-<namespace>`.
The shared append-only reservation registry is fixed beneath that same parent
as `external-budget-<first16hex of original auth SHA>`; an authorization cannot
move it. Lock order is original global journal, shared registry, then cohort
journal; release is reversed even when a later acquisition fails. The original
17 events, progress and recovery receipt are read-only: no continuation event,
receipt regeneration or progress write occurs there. Missing/conflicting original
evidence refuses. External checkpoints/progress use their own chain. Every
reservation is written to the shared registry FIRST, then the cohort journal,
then dispatch; assignment is shared-first too. The entire family canonical
suffix must match the shared reservation set. An invisible/uncertain POST,
missing/partial registration, orphan or single-sided prefix rollback blocks
every later namespace without refund or a replacement nonce. Cohort SETTLED is
written FIRST, shared SETTLED second. A crash between those writes can finish
the latter only from the exact canonical auth/namespace/nonce/run/usage/receipt
hash. Registry costs are never added twice to the canonical meter sum. Missing
registration is not zero-POST proof and cannot create a fresh budget.

The original authorization's raw owner ID may remain null: the actual owner SHA
already established in the verified five-run prefix is mandatory in the consent
and meter, checked against every metered OAuth/Drive owner observation. No raw
owner ID, account binding, credential validity or supplier right is invented.

An empty external chain has local examined=0 and a logical genesis commitment
derived from task/namespace/input SHA/date/feed/bases. This is not the original
16-name checkpoint or a physical Drive object. Its first workflow resume ID and
SHA are **both empty**; its first physical checkpoint has previous=null. Later
checkpoints require exact namespace/input/task and verified raw/split prefix.
`--max-batches 1` can stop at the first verified boundary for an early metadata
handoff without enabling a scheduler or discarding cumulative state.

Before price requests, each selected name gets a separately metered, scoped
`GET https://paper-api.alpaca.markets/v2/assets/{symbol}`. This is part of the
price batch, **not** `preflight_only` (which still requires provider GET0).
Only the selected32 names are allowed; no account/orders/positions or all-assets
endpoint is admitted. Official reference:
<https://docs.alpaca.markets/us/reference/get-v2-assets-symbol_or_asset_id>.
Actual200 reference bytes/hash/collection time/current UUID/exchange are retained
privately in the raw pack manifest. These establish current provider reference,
not historical security identity, MIC certification or licensed historical access.
404 and actual inactive asset references become `HELD_PROVIDER_ASSET`, distinct
from verified empty bars or numerical `HELD_BAR_VALUE`. Supported names around
an unsupported name still advance in contiguous groups. Asset401/403/429, network,
price404 and every unapproved error remain terminal and retain the debit.
No credential-bearing or vendor original bytes enter public GitHub reports.

All external-cohort runtime failures stop that epoch, including asset-network
and generic price HTTP failures. This minimal path accepts no `--recovery-run`
and never turns NETWORK/HTTP_ERROR into permission for another dispatch. A
finalized failed receipt can still be read, accounted and settled after expiry;
new reservations remain forbidden. Any later recovery needs a distinct A0
reviewed contract and explicit authorization preserving all spent bytes/counters.
Legacy fixed-seed recovery behavior is unchanged.

Task: `R1000-A1-993-SIP-BOUNDED-CAMPAIGN-20261015`.
This is Source collection control, not a new price collector, reader admission,
historical Russell membership certificate, scheduler, broker or portfolio path.
The original16 objects and gen24 are not rewritten or recollected.

## Activation and immutable authorization

Deploy only after exact-head CI, independent Source A6/review and explicit
protected merge approval. PR checks have no capture credentials. The Work host
uses the existing checkout and authenticated GitHub CLI; workers use the
existing repository secrets. No paid plan, account rotation or new service is
created. Run `python -m tools.alpaca_sip_campaign --help` without side effects.

The private local authorization JSON contains:

- `schema: r1000-sip-campaign-authorization-v1`, `task_key`,
  `scope_approved: true`, `private_noncommercial: true` and an actual
  `approval_reference` to the user's finite993 instruction.
- `start: 2016-01-04`, `end: 2026-10-14` (exclusive), seed SHA256
  `333668b35a6264ad9c3bbe635212a5b95db21ba57855666dca2ee5311ea160cc`.
- Original checkpoint SHA256
  `9a8e0d12d0acb065ce0b5a44963b6b152646127c521bf0e592119526d889fd6a`
  and its existing private file ID; existing private root/child IDs.
- `expected_master`: actual protected merge/master SHA at activation, not the
  author branch SHA. `code_pins` maps every path in `PINS` to its exact deployed
  Git-LF SHA256. Native CRLF is a different context and is not a deployed pin.
- `workflow_run_floor`: one plus the latest workflow run number before the
  first campaign dispatch. All subsequent workflow run numbers must be present
  in canonical history, including intervening PR/other runs. More than100
  history rows fails closed instead of silently accepting a partial listing.
- `limits`: exactly `provider_gets:2000`, `drive_requests:50000`,
  `drive_bytes:8589934592`, `storage_bytes:1073741824`.
- `transfer_definition`:
  `HTTP_BODIES_PLUS_65536_RESERVED_OVERHEAD_PER_GOOGLE_REQUEST`.
- `owner_permission_id`, `credential_binding` and
  `account_permission_reference`: actual evidence, or null for metadata-only
  preflight. The credential binding is SHA256(key + NUL + secret), never the
  credentials themselves. Do not invent an account agreement/reference.

The authorization hash remains unchanged across jobs. The first canonical
workflow creation time starts the48h validity, conservatively including queue
delay; preparation does not start it. Source/master/code/date/root/seed drift
requires stopping, not resetting the campaign identity or accumulated usage.

## Metadata preflight without circular identity assumptions

With null owner/key bindings the host dispatches one controlled metadata-only
preflight. It reads actual OAuth owner/private root+child and storage quota,
records only owner/key hashes and available bytes, and requires free>=2GiB.
It does not query Alpaca or store prices, and cannot certify SIP entitlement or
market-data rights. Those observed bindings become mandatory in subsequent
canonical receipts. The actual account permission reference remains a separate
price-capture prerequisite; `--account-permission-reference` can supply the
reviewed record without modifying the immutable authorization.

That reference is an actual Issue448 owner/member/collaborator User comment
containing one `A1_SIP_ACCOUNT_PERMISSION ` JSON line. Required record fields:
`task_key`, `auth_sha256`, actual `bindings` (owner/key hashes),
`agreement_reviewed`, `account_eligible`, `historical_sip_allowed`,
`private_retention_allowed`, `private_noncommercial`, `evidence_reference`,
`expires_at_utc`. The five eligibility fields must be explicitly true on actual
evidence, not inferred from a successful request. The comment/source/expiry and
scope are checked before price collection. An agent must not invent or post
this attestation without actual human authorization/evidence. This is an account
eligibility record, not a fresh approval for each batch.

Metered OAuth uses a valid existing access token, or refreshes with the existing
explicit custom client ID/secret at the fixed Google token endpoint. An expired
token relying on opaque rclone built-in refresh refuses with
`CAMPAIGN_OAUTH_CLIENT_REQUIRED`. It never runs unmetered rclone, guesses a
public OAuth secret, opens a browser, creates an application or switches an
account. Whether the current secret configuration supports this remains a
runtime fact; offline proofs do not establish it.

## Budget semantics and failure accounting

Every provider attempt is debited before opening the request. Google requests
include OAuth, quota/privacy metadata, lookups, uploads, full-prefix restore,
independent readback and reused-object reads. Multipart request bodies count.
The meter reserves response limit+1, request body and65536 overhead bytes before
I/O. A complete known response releases only its unused response reservation.
Partial/error/oversize/credential-echo/timeout/unknown POST replies retain the
whole reservation. Storage is charged before upload; confirmed storage is
reported separately. An accepted upload with lost acknowledgement can be an
orphan and is never silently refunded.

The transfer counter is explicitly an HTTP-body-plus-overhead accounting cap,
not a measurement or guarantee of encrypted wire/TLS bytes. If the accepted
budget requires exact wire accounting, this implementation is ineligible until
that transport is supplied. Observed complete body bytes and conservative
charges are distinct receipt fields. The previous4.58GB estimate excluded this
per-request overhead; it must not be reported as new observed consumption.

Live workers require Linux/main-thread POSIX process alarms. The alarm covers
TLS/header parsing, uploads, reads, OAuth and CPU normalization/readback, with
remaining-time socket clamps and bounded `read1`. Windows supports the Work host
and offline normal/-O tests; its POSIX live-alarm test is explicitly skipped.
Each dispatch requires enough remaining active allowance for the existing
offline10min + capture120min worst case (7800seconds). Completed job timestamps
reconcile actual active time against8h. Unknown/incomplete run results cannot
release the outstanding reservation.

The local Work journal is append-only, fsynced and exclusively locked. Before
dispatch it reserves all remaining resource allowance. A killed Work leaves
that reservation; an old valid local prefix is rejected against canonical runs.
Duplicate nonces, reruns and missing run-number history are refused before
OAuth/provider I/O. A completed trusted run can settle an interrupted Work's
reservation; a missing/unfinalized meter cannot. Do not delete a stale lock
until the actual local writer is known to have stopped.

Only a separately inspected `NETWORK`/`HTTP_ERROR` failure with a complete,
bound conservative receipt can use `--recovery-run`. It starts a fresh nonce
from the last independently verified checkpoint; never a GitHub rerun. Auth,
quota, privacy, hash, missing-meter and unknown outcomes remain terminal.

## Per-batch data verification and calibration

Normal scope is31 batches32 plus the final1. The initial16 checkpoint/prefix is
mandatory. After partial failure, a shorter batch aligns the next128-new-name
calibration checkpoint. The40-dispatch cap includes failures/preflight.

The original collector's full historical resume verification remains. A fresh
group independently rereads checkpoint, raw ZIP, normalized gzip and receipt,
then reconstructs raw/split grids with the existing semantic verifier. Only
then does its private checkpoint reference get flushed to the existing Actions
log surface and its SHA/progress enter the metadata meter. Original price bytes
never enter GitHub logs or artifacts. Valid/no-data/held counts are separate;
all admission/PIT/historical-identity/commercial/economic flags stay false.

At128-new-name intervals the host and worker reforecast from actual canonical
receipts, excluding metadata-only preflight from the price-job slope. The
forecast retains full-prefix resume costs and a25% margin. It stops if remaining
work no longer fits current budgets. Forecasts never override per-request caps
or certify future completion. Clean batches need no new Work, PR or AI review.

Short recovery batches are normalized to32-name byte/time equivalents; the
largest observed equivalent and positive prefix-growth rate bound the forecast.
A small final recovery total cannot replace the cost of a future full batch.
The first campaign dispatch must equal the authorized workflow run floor;
before any dispatch the floor must be the next observed workflow number.

Account permission must remain valid through the worker's fixed deadline.
The meter binds both its comment URL and a canonical record/immutable author
identity hash, including the exact full comment-body hash. Editing the same
comment stops subsequent capture; do not edit an active campaign's attestation.
Metadata-only preflight carries no verified account-permission hash.

The only Actions artifact is typed `campaign_meter.json`, retained7days: hashes,
counts, conservative charges, observed body/storage totals and bindings. It
contains no raw prices, private file IDs, credentials or arbitrary error text.
Private refs remain in the original Actions checkpoint log/local journal;
exclude those journal fields from public handoff packages.

## Validation and proof closure

Registered route: unchanged `api_credentials_check_smoke.load_tests` -> existing
Alpaca suite -> new campaign suite. Preserve the protected PR runner/workflow.
Run the affected registered credential/capture suites in normal and optimized
Python. The tests use generated in-memory servers and explicit canonical LF
seed fixtures, never the archived16 vendor bars.

Independent exact-head Source proof must pin this module, the collector,
Twelve helper, config/history helpers, workflow, new/existing capture tests,
registration entrypoint, transitive cohort/preflight helpers/workflows and seed
actually consumed. A broad Main proof is a separate contract: the current
`manual_foundation.A6_FIXED_PROOF_PROGRAMS` inventory must be checked for the
new executable paths. Do not edit Main protected code from this Source lane
or claim that a Source-only proof automatically closes that Main inventory.

Required counterexamples include duplicate/rerun, valid-old-prefix rollback,
missing/unfinalized/mismatched receipts, every budget boundary, failed/partial
HTTP and POST, stale/expired authority, bootstrap/OAuth, slow header/body/CPU,
checkpoint loss, mixed basis, held/no-data status, privacy/rights drift and
128 calibration. CI/hash/A6 are code evidence, not data or investment approval.


## Explicit human capture request without supplier-rights attestation

The original account-attestation record remains accepted unchanged. An actual
owner/member/collaborator User may instead record one `A1_SIP_CAPTURE_DIRECTIVE `
JSON line for the existing private noncommercial historical campaign after an
explicit human request to waive the internal evidence-document procedure.
It is execution consent, not certification of supplier licensing or eligibility.

Required exact fields: `task_key`, `auth_sha256`, actual `bindings`,
`mode: DIRECT_HUMAN_CAPTURE_REQUEST`, `plan: Trading Basic`,
`personal_historical_capture_requested: true`, `private_noncommercial: true`,
`evidence_procedure_waived: true`, `supplier_rights_verified: false`,
`approval_reference` (the actual Issue448 human-directive coordination reference),
and `expires_at_utc`. Expiry is the finite operational approval limit, not an
invented license expiry. Do not add agreement-reviewed/account-eligible or
retention-rights assertions to this record. Record only actual human consent;
never manufacture supplier assertions or actual owner/key bindings.

The same verifier checks real comment/author identity, exact campaign/auth and
metadata-observed bindings, the entire fixed worker deadline and immutable
comment-body/author hash. Existing account_permission_* meter fields retain
compatibility as execution-authority reference/record hashes; the referenced
record's explicit mode determines whether it is account attestation or consent.
Mixed/duplicate records refuse. All existing counters, authorization bytes,
canonical history, reservation/settlement, checkpoint, seed, provider/OAuth errors,
Drive privacy/quota, deadlines and fail-closed outcomes remain unchanged.

The cited approval URL is fetched and must resolve to an actual Issue448 OWNER
User comment containing one bounded `A1_SIP_CAPTURE_APPROVAL ` JSON line. Its
exact fields are `task_key`, `plan`, `personal_historical_capture_requested`,
`private_noncommercial`, `evidence_procedure_waived`, `supplier_rights_verified`,
`start`, `end`, `seed_sha256`, `initial_checkpoint_sha256`. The values preserve
the same Trading Basic/personal/noncommercial/direct-request/false-supplier
semantics and exact original campaign scope. It records the already-given human
request, not new supplier evidence or a repeated approval question. The owner
approval's creation AND last-update clocks must precede the bound directive's
creation; both clocks, its actual author and entire body hash enter the execution
record digest. A previously created comment edited after the directive refuses.
Missing, unrelated, altered
or synthetic provenance cannot authorize capture. Do not edit either comment
after activation. A directive may reference its own verified OWNER comment if
that same comment contains the exact approval line.

If no canonical campaign has started, finalize and approve deployed source
before creating the first immutable activation authorization and metadata-only
run. Compute the actual next workflow floor at activation; never hardcode an
old observed floor or reset an existing authorization/journal. The metadata-only
run measures actual credentials/OAuth/private owner/free>=2GiB, debits its costs
and starts the existing48h clock. Bind the direct request to those actual hashes,
then resume the same authorization/journal at the original16 checkpoint.
Provider403 or another entitlement failure remains terminal; do not switch feed,
account or subscription to evade it. Source/PIT/commercial flags remain false.


## Named pre-dispatch local rejection recovery

The installed GitHub CLI 2.91 requires every outer `workflow run --json`
input to be a string. Serialize consent inputs as `"true"` and the batch size
as `str(...)`; the nested campaign-control/authorization JSON keeps its real
boolean and integer types. This changes transport representation only.

The only new recovery is the independently reproduced first local rejection
whose original authorization, reservation and progress hashes are pinned in
`LOCAL_REJECT`. It is not recovery for an arbitrary unknown dispatch, a
provider/Drive failure, a completed/assigned run or a changed budget/scope.
The original stdout status is known; its discarded gh stderr is not recovered.
Root's separately executed installed-CLI loopback proof establishes the typed
input parse failure before POST; synthetic POSTs are not actual Actions runs.

Use the SAME existing state directory. Preserve the original authorization and
entry1 byte-for-byte and copy the original progress bytes to an immutable
snapshot. A new, separately saved authorization changes only actual deployed
master/six code pins/next workflow floor. All other fields, private identities,
original16 checkpoint, date/seed/limits and task key must be exactly equal.
Do not replace the old authorization or create a fresh journal.

`--predispatch-recovery <private-bundle.json>` accepts exactly four strings:
`prior_authorization`, `prior_progress_snapshot`, `proof_reference`,
`receipt_path`. The reference is a real Issue448 OWNER User comment with one
bounded `A1_SIP_LOCAL_REJECT_RECOVERY ` JSON line. Its exact schema/fields are
validated by `local_reject_recovery`: old/new auth and scope/code-pin hashes,
the named old reservation/progress/nonce, the actually observed CLI binary and
independent transport-proof hashes, POST=false, canonical_runs=0, actual usage
strict integer zeros and a finite operational expiry. This is an agent-prepared
record of the authorized recovery and observed evidence, not a supplier-rights
attestation or a claim that a human read the code. Final Source exact-head CI,
independent QA, hosted review and protected deployment remain mandatory.

Before appending, canonical bounded history must contain no campaign run and
the floor must be the actual next workflow number. Live master, deployed six
pins and native Git-LF-equivalent code must agree. Any hidden/delayed original
nonce or earlier canonical run fails closed; an existing first clock, active
cost or dispatch can never be treated as zero through this named path.

Append entry2 `LOCAL_REJECT_RECOVERED` under the new authorization, with entry1's
hash as its predecessor, the actual proof author/body hash, old/new scope/pin
bindings and verified zero usage. Never fabricate RUN_ASSIGNED, a meter or
SETTLED. Preserve the original RESERVED bytes: the typed event closes only that
one proved-untransmitted nonce. Every other reservation still reconciles exactly
against canonical runs. The immutable recovery receipt links both auths and the
journal event; it is exclusively created/fsynced and identical on restart.
A crash before receipt creation can finish that same receipt without adding a
second closure; partial/conflicting receipt bytes stop instead of overwriting.

Supply the same recovery bundle on subsequent host resumes so the old/new
journal prefix and immutable proof remain checked. Existing canonical history
still governs all Provider/Drive/storage/transfer counters, 40 dispatches, 8h
active time and the first actual canonical run's48h window. The original local
rejection had no such run or active use; recovery does not reset an existing
clock. Resume metadata-only, then bind the actual observed owner/key hashes to
the existing direct capture-consent record and continue original seed17..48.
Worker, provider/Drive behavior, deadline, entitlement, privacy and source/PIT
fail-closed policies are unchanged.

Recovery also hashes the original authorization's raw bytes. Its receipt must
resolve outside the journal and be disjoint from the bundle/prior inputs; an
existing receipt before the closure refuses before any append. Reconcile fresh
full canonical history immediately before dispatch, during nonce discovery and
after watching before settlement. A delayed original nonce always stops; a
closed local reservation is excluded from the progress report's pending set.
The persisted pre-dispatch bundle can accompany a later legitimate network
recovery only when its requested run is the actual latest bound BLOCKED
NETWORK/HTTP_ERROR receipt. An arbitrary recovery ID on the first dispatch
cannot manufacture a relationship.

Both pending-run resume and postwatch settlement recheck the full canonical set
after receipt/checkpoint-log reads, immediately before the common SETTLED append.

The immutable prior-progress snapshot must resolve outside the entire state
folder and cannot be a symlink to live progress. Recheck canonical emptiness
after all deployed-pin reads immediately before closure. Proof expiry permits
only the initial closure: bind its expiry and require the actual event timestamp
to be inside its approval window before append. Later resumes verify that same
canonical event, body/author hash and immutable receipt even after proof expiry;
this never extends the actual campaign48h/8h clock or permits expired dispatch.
Event2 must retain its canonical raw bytes, and the receipt anchors the actual
stored event bytes rather than reserializing an unanchored equivalent object.

## Approved continuation of the measured128-name stop

The owner approved the concrete continuation request
`e602411e37b3e6e544a46e7fc78b1a320acfbde891ead7b7268efe79ebca8eec`;
coordination: Issue448 comment6229153314. This authorizes only cumulative
transfer9GiB and active12h for this existing campaign. Provider2000, Drive50000,
storage1GiB, dispatch40, fixed seed/date/adjustments, original16 and the original
first canonical48h window do not change. An account switch cannot reset any
counter and is outside this continuation. Supplier-rights flags stay false.

The default v1 authorization remains exactly8GiB/8h. A v2 authorization adds
one portable `continuation` object with `prior_authorization` (the full unchanged
b5f25d1b v1 authorization) and `proof_reference` (an actual Issue448 OWNER User
comment). All other authorization fields except schema, transfer cap, deployed
master and code pins remain identical, including the original workflow floor.
The only accepted prior boundary is hard-pinned: five exact runs/meters,
128new names,144examined,872active seconds, checkpoint032dac34,17journal events,
and first canonical2026-10-17T02:08:51Z. The validity still ends
2026-10-19T02:08:51Z. A late/missing/rerun/altered old run refuses.

The OWNER comment contains exactly one `A1_SIP_BOUNDED_CONTINUATION ` JSON line,
with the closed schema/fields checked by `continuation_proof`: old/new auth,
spent prefix/checkpoint/progress, all prior usage/time/run IDs, unchanged first
clock, concrete request hash, exact9GiB/12h/40 limits, preserved seed, no account
rotation, actual deployed master/pin digest and the original48h expiry. The same
completed comment carries the new auth-bound capture directive, retaining the
actual metadata-observed owner/key hashes and the original human capture
approval reference. Compute proof and permission digests only after the full
comment is frozen: do not put its own body-derived hash back inside that body.
The bridge binds old and new permission-record hashes; no general RIGHTS_DRIFT
exception or supplier attestation is added. Do not edit activated comments.
The host supplies the frozen portable `continuation_binding` with each worker
control. Workers compare it to freshly verified evidence before any external
data I/O, and every new meter carries its `continuation_proof_sha256`.
History and common settlement require the same hash, including the first new
dispatch; an edited comment cannot become a silent new first-suffix authority.

Keep all three authorization eras: entry1=f67185f7, entries2..17=b5f25d1b on
master5a762256 with8GiB/8h, and entry18/new suffix=new auth/source with9GiB/12h.
Each original meter allowance is checked against its original cap minus all
earlier spent usage; new meters use the new cumulative cap minus that SAME
usage. Active time, dispatch count and first creation time include all five old
runs. Preserve the old local-reject event/receipt rather than reissue them.

Use the SAME journal and old pre-dispatch recovery bundle, plus
`--continuation-receipt <external-private-path>`. The host selects the embedded
proof URL as capture permission. No redundant
`--account-permission-reference` is needed; a conflicting explicit URL refuses
before taking the campaign writer lock or writing the bridge.
Before the initial append,
verify native/deployed code pins, actual master, unchanged progress bytes and
fresh full canonical history. Append only typed entry18 `BUDGET_CONTINUED`, then
exclusively create/fsync its immutable receipt outside the journal and disjoint
from inputs. This is no fake price run, settlement or refund. A receipt-create
interruption may finish that same receipt; changed/partial bytes refuse.
On restart, revalidate the exact bridge body/author/time/hash and old prefix.
Resume only at the existing checkpoint032dac34, seed145 onward, with the
existing32-name batches,128 calibration and fail-closed provider/Drive policies.
New source must pass exact-head Native/Linux/A6/review/protected deployment
before any actual continuation. This contract change alone is not capture,
PIT admission, historical universe certification or investment approval.
