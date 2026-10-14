# Finite private SIP campaign control

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
