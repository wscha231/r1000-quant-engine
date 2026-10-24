# A1 Source to shared Reader: bounded research preparation

The original adapter was offline preparation based on master
`37809837bd2d67114fae7d4a1c4e2b8ad0344b07`, including merged #627. It does not
publish a generation, accept rights, admit a Source, integrate Draft #671,
or enable an updater.
Actual source bytes, consumer ACK and economic validation remain `NOT_RUN`.

## Reused boundary

`tools/prepare_a1_reader_generation.py` reuses the existing capture archive
verifier, canonical serializer and shared Reader's offline session schedule.
It does not construct OwnerDrive, collect prices, read credentials, scan storage,
alter the frozen seed/checkpoint/budget, or write a Registry.

`prepare` accepts only already-local original ZIP, normalized gzip, exact capture
receipt bytes and explicit binding evidence bytes. It verifies original-object
hashes and reconstructs normalized rows through `verify_archived_group` before
typing the nine columns required by `price-daily-v1`. Missing Open is refused;
there is no Close substitution, zero filling or synthetic price repair.

`CONTRACT_FIXTURE` requires explicit fixture rights/CA/lifecycle markers and
`CONTRACT_FIXTURE:` identities/run IDs. These remain synthetic expectations.
The separate `REAL_SOURCE` branch is implemented: it returns immutable prepared
research bytes only when independently reviewed input bindings and exact proof
bytes agree. Otherwise it returns `BLOCKED`, finite reasons and no partial bases.
Without a trusted binding the default remains blocked, even with `VERIFIED` claims.
All positive tests, including the real-code branch, use explicitly injected
synthetic trust/documents. They are not actual Source or rights acceptance.

## Bytes, clocks and adjustment basis

Prices are finite, positive Decimal strings converted only with exact decimal
round-trip through the typed float representation. Volume is nonnegative integral
and no greater than 2^53. Every raw/split session needs an explicit positive split
factor. Raw OHLC equals split OHLC times that factor; split volume equals raw
volume times it. Unsupported precision, missing factors and mismatched grids fail.
RAW and SPLIT_ADJUSTED have independent objects, manifests and generation hashes;
no TOTAL_RETURN or dividend-adjusted series is invented.

Row availability is the explicit `FIRST_OBSERVED_COMPLETE_READBACK` event binding
the ZIP, normalized gzip and capture receipt hashes. It is never copied from a bar
date or represented as original public availability. Unknown original publication
and provider collection clocks remain null/UNKNOWN in the derivation provenance.
Session close <= first observed <= generation creation <= decision <= reviewed
research freshness expiry. This expiry is not a supplier rights expiry; the latter
remains null. The output is PIT_PROXY and licensed only for fixture research and
discovery. Training/backtest and official economics remain blocked.

The hash DAG is original bytes/evidence -> typed view -> derivation receipt ->
manifest. The receipt binds the original code/seed/run separately from the
derivation run, actual adapter-file SHA256 and evidence SHA256.
Fixture code IDs are explicit synthetic contract identities, not Git commits.
The real branch binds actual original/derivation code and run pins supplied by
the trusted Source record, plus the loaded adapter-file byte hash. An immutable
storage/publication receipt would be a **later** object; it is not invented here
and cannot be embedded cyclically into its own manifest hash.

## Exact owner-reference reads

`OwnerReferenceReadTransport` accepts an already configured owner client and a
tuple of frozen `OwnerReference` values. Only exact content-addressed
`shared-research-v1/{generations,objects}/<sha256>` references are readable.
Constructor calls no authentication or API; `read` checks parent membership,
reads a bounded exact file ID and verifies size/hash. No list/search/latest,
directory creation, fallback or write exists. The private reference map must
stay private. Actual owner/OAuth/private-folder approval and transport accounting
remain duties of the existing Source lane before any real transport call.

Exact readback type/size failures raise the existing Reader `OBJECT_SIZE`
ContractError; a same-size hash mismatch raises `HASH_MISMATCH`. The Reader's
transport boundary preserves ContractError before its general availability
catch, so neither error can become an optional component refusal. Ordinary
OSError or plain ValueError from unavailable storage still becomes
`ARCHIVE_UNAVAILABLE`: optional archive components may be refused locally,
while required components fail. Standalone exact-reference reads retain these
integrity checks. Synthetic integrated tests compare normal RAW/SPLIT, optional
and required corruption, plain-transport hash parity and real unavailability.

Bounds: original archives retain the existing verifier's limits; normalized
decoded bytes <=32MB, rows <=100,000, each view <=18MiB, manifest <=1MiB,
references <=258 and total declared references <=128MiB. Preparation returns
frozen dataclasses, byte strings and tuples; no real storage publication occurs.

## Validation and next integration dependency

Registered fixture suite `tests/a1_reader_generation_binding_smoke.py` is loaded
through the existing `tests/long_history_lake_smoke.py` Tier-1 entry. It tests
original/hash/clock/identity/split/numeric failures, exact-reference readback,
duplicate keys, two separate Reader consumers and repeatable immutable bytes.
The synthetic consumers prove contract compatibility only, not actual Feature/ER work
or a real consumer ACK. SPY absence remains missing; QQQ or AAPL cannot replace it.

The current protected master includes #627 `read_components`. The prepared
fixture generations are validated through both the original `read` and this
integrated API, including two independent consumers, optional SPY absence and
required SPY refusal. No benchmark is substituted and no Reader/schema gate is
changed. This is synthetic compatibility evidence, not an actual consumer ACK.
Actual reuse must separately bind owner rights, original receipts, decision window,
security/CA/lifecycle evidence, first-observed clock and exact protected producer
deployment; then issue separate storage/readback receipts and real consumer ACK.
Do not activate a schedule or claim the retained820/managed-refresh checkpoint
is already a Reader generation. #671 updates and actual Reader consumption remain
distinct reviewed integration dependencies.

## Strict REAL_SOURCE trust boundary

`prepare(..., trusted_source=TrustedSourceBinding(...), proof_objects=...)` has
two distinct inputs. The evidence packet is untrusted. The frozen trust object
must come from the existing Source owner's independently authenticated canonical
review/receipt, never be constructed from that packet or an uploaded JSON claim.
It pins the review reference/receipt bytes, exact evidence bytes, complete proof
hash set, existing non-secret credential binding, original run/attempt/source
and derivation run/code/loaded adapter SHA256. The module has no CLI, default trust
store or factory that converts a `reviewed: true` input into this authority.
Supplying the trusted argument is an explicit caller trust boundary, not proof
that this pure function authenticated GitHub, a human reviewer or legal terms.
Authenticating that record and its semantic acceptance remains the existing
Source controller's responsibility before calling; it is not run by this patch.

The review receipt retains its existing format. No new legal document, signature,
auth hash, account identifier or supplier expiry is generated or demanded.
Only actual retained reference/hash values may fill the real trust input.
The evidence packet is a bounded derivation configuration, not a new canonical
Registry, account ledger, rights attestation or source-admission receipt.

The branch validates these mutually bound existing inputs:

- Original capture ZIP/normalized gzip/receipt through the existing verifier.
  Receipt scope stays private research with original identity/PIT/admission false.
- A finalized successful non-preflight `a1-sip-campaign-meter-v1`, its exact
  run/attempt/source/account binding and final checkpoint hash. The corresponding
  original `alpaca-private-sip-history-v1` checkpoint binds either this selected
  final raw/split group or a bounded exact-hash metadata path to its selected
  ancestor group. The final anchor belongs to the original run, never a later
  cumulative campaign checkpoint or a fabricated execution record.
- Existing `a1-reviewed-account-rights-v1`, matching the original meter's existing
  credential binding, Alpaca historical SIP/private noncommercial retention scope
  and exact source-document bytes. An explicit reviewed capture scope binds the
  selected receipt/run/start/end to those rights. API success or the plan name
  supplies none of this. Original capture consent is not supplier-rights proof.
- Exact reviewed identity, CA and lifecycle proof references for the selected
  historical window, with the reviewed mapping/factors in the pinned packet.
  Raw document meaning is accepted by the external Source review; this function
  authenticates byte/reference equality and consistency, not PDF/legal semantics.
  Current asset support alone does not authenticate historical mappings.
- Actual first-observed complete readback and its reviewed source reference,
  exact three-original hashes, clocks, real identity scope, split factors and
  numeric policy. Unknown original public/provider clocks remain null/UNKNOWN.

Proof objects are an immutable tuple of exact `(sha256, bytes)` pairs: at most32,
4MiB each and16MiB total. Every supplied proof must be reviewed, referenced and
hash/size exact. No listing, download, fallback, approval lookup or credentials
are performed. Missing proofs, foreign account/source/run, substitute evidence,
unknown window statuses, fixture markers and code/config mismatches refuse.

The output is `REAL_SOURCE_PREPARED_UNADMITTED`, never accepted publication.
RAW and SPLIT remain separate PIT_PROXY research/discovery generations under
the unchanged Reader gates. Actual historical-PIT/training/backtest use remains
blocked. A supplied supplier expiry is checked separately; absent expiry stays
unknown and is not replaced by the declared research freshness review window.
The Reader-facing expiry is the earlier applicable deadline, preserving both
original clocks separately in provenance so later reads cannot outlive rights.
Corrupt gzip/DEFLATE data is a finite refusal with no partial prepared bases.
Immutable publication/readback and real consumer ACK are later authorized
existing-Source operations. This patch performs none of them.

The owner has confirmed that applicable account-rights evidence is still absent.
That is an evidence dependency for real execution, not a reason to stop code
implementation or to repeat the820/174-symbol capture audit. Rights/clock/window
proof is reused from its exact source when available; green synthetic tests do
not manufacture it.

## Bounded original-run ancestor groups

Omitting `original_checkpoint_path` retains the existing final-group contract.
For an ancestor, supply that reviewed list of exact `{file_id, sha256, bytes}`
checkpoint references, in order from the original final checkpoint's previous
link through the selected group. Every byte object remains in the same reviewed
proof tuple; no I/O, discovery, fallback or new trust construction is performed.

The finalized original meter must bind the same account/run/attempt/source and
cohort, a strict integer `examined_before/after` range of at most32 additions,
the final checkpoint hash and its original parent hash. Intermediate checkpoints
must preserve source/seed/cohort/window and all private/unadmitted flags, exact
examined/completed/held prefixes and per-group suffixes. Wrong links, missing
nodes, duplicate hashes/IDs, cycles, shortcuts, cross-run boundaries and partition
changes refuse. Selected collected/no-data/held state and original trio must
match the supplied capture receipt; held/no-data cannot become priced rows.
The original parent ID cannot alias a final/path ID or an unread intermediate
previous reference with different bytes. An exact selected previous==parent at
the original run boundary remains valid.

When `examined_before > 0`, `original_parent_checkpoint` is an additional exact
reviewed proof, matching the original meter parent, count and final prefix. This
first bounded contract requires its original source pin to match the selected
run; a source-revision bridge is not inferred. For an initial external cohort,
there is no stored empty parent: reuse the existing pure `external_genesis`
helper and its frozen2016-01-04/2026-10-14 contract. Do not invent an empty Drive
checkpoint. Stop at the selected group; never restore the full campaign.

`MAX_PROOFS=32`, each proof at most4MiB and all proofs at most16MiB remain
unchanged. Path/parent metadata use those existing slots. Their decode is bounded
to1MiB each. Only the selected ZIP/normalized/capture receipt use the original
archive verifier. No sibling raw/normalized/held-marker payload is read or claimed
freshly verified. Sibling held/no-data handling here is metadata membership only.
Do not call `resume_state`, `settle_run` or dispatch to validate this path.

Derivation provenance retains final/selected/path hashes, original run bounds,
parent anchor and zero unselected price reads. This adds lineage support, not
rights, identity, CA, public clocks, publication, a real consumer ACK or admission.
All positive unit trust/terms/price bytes remain explicit synthetic fixtures.

Existing metadata inspection located MU and NVDA as5/7-link ancestors of their
own run39083896869 final checkpoint; it did not re-download price bytes. AAPL's
initial16 chain has no original finalized execution binding in that packet, and
SPY's declared cache differs from the located historical Parquet. This extension
does not manufacture those missing edges or admit that fixed cohort.

## Explicit private view and consumer metadata

This addition is prepared on protected master
`070e2579349c9af1dd6e9c346f1b00ca9a005911`, after #673. It reuses the current
`ds.us.prices.daily` / `price-daily-v1` entry without changing the Registry.
The original full-span behavior, receipt role and refusal remain the default.
Opt in through the independently reviewed evidence:

```json
{"private_view":{"start":"2024-03-01","end":"2026-10-13","selection_reason":"SOURCE_EXACT_COMPATIBILITY"}}
```

Both endpoints must be actual NYSE sessions inside the original capture window
and available by the supplied observed readback and decision. Every collected
member must contain the complete selected session grid in both bases. No
automatic shortening, ticker omission, missing-Open repair, price rewriting or
numeric tolerance exists. The unchanged literal Decimal factor predicate runs
on each selected row. Original archive/hash/reconstruction, complete inventory, duplicate detection,
row schema and date/calendar checks still run before selection. Invalid excluded
bytes or unknown original tickers cannot disappear into the view. Identity,
lifecycle, CA and exact factor eligibility apply only to the selected grid.
Excluded typed identity/factor facts need not be supplied, parsed or certified;
they remain nonconsumed original-byte observations. The full-span factor
relationship and historical eligibility are not claimed for excluded rows.

The requested original4 private scope is MU/WMT/JPM/XOM, each657 selected
sessions, with original2016-01-04..2026-10-13 envelopes retained. This is
preregistered Source compatibility, not an economic result or optimization.
Provenance records original/selected/excluded counts, ranges, normalized-subset
and session hashes by member/basis, original symbols/normalized count, typed
objects and explicit OBV anchor. A2024-03-01 anchor is not a2016 lifetime anchor.
The four-company positive fixture is synthetic, not actual original4 bytes.

Explicit views require REAL_SOURCE's independently supplied trust/proof tuple.
technical_metadata maps every collected ticker to identity_evidence and
status_evidence exact hash/byte references in that same reviewed tuple. Each
typed document is at most64KiB, with bounded nonempty original-source references
inside the unchanged32-proof/4MiB-each/16MiB-total limits.

The identity document uses the existing Main schema
ohlcv-security-identity-evidence-v1. It supplies actual instrument/provider IDs,
ticker, asset class, market, MIC, calendar, timezone, currency, effective interval
and aware availability/collection/expiry clocks. Its source_documents include
the reviewed original identity document. It must cover the selected effective
window and match provider/original capture receipt. Ticker is not a
provider ID. UNKNOWN, fixture markers, missing/unreviewed hashes, naive clocks
and conflicts refuse. This pure code verifies consistency with externally
reviewed bytes, not independent issuer/provider authenticity or legal meaning.

The separate a1-ohlcv-status-volume-evidence-v1 document binds the same IDs,
ticker/provider/capture receipt, effective interval and aware clocks. It requires
halt_coverage=COMPLETE_FOR_WINDOW, an explicit sorted unique halted_sessions
list, volume_basis={raw:RAW,split:SPLIT_ADJUSTED}, and nonempty
halt_source_documents and volume_source_documents. UNKNOWN halts never become
an empty list; equal prices/factor1 do not establish volume semantics. Only an
explicitly proved empty list is empty. Reader expiry is capped by the earliest
supplied technical-proof, research-freshness or actual supplier expiry. No
clock, account binding, permission or expiry is created from an absence.

In this opt-in contract source_receipt_role=ORIGINAL_VERIFIED_CAPTURE_RECEIPT,
source_receipt_sha256 addresses the actual original capture receipt bytes, and
manifest source_run_id is its reviewed original run. RAW/SPLIT share that real
origin and the same actual raw_source_sha256 set. Each distinct
basis_derivation_receipt_sha256 and derivation_run_id is preserved separately.
Both basis receipts, typed identity/status bytes, their original proof documents
and the capture receipt are returned as bounded content-addressed objects.
No basis digest is forced equal or renamed as another receipt. The default
full-span source_receipt_sha256 continues to address its own basis provenance.

Instrument metadata serializes validated asset_class/provider_security_id,
identity_evidence_sha256, explicit halted_sessions and the actual volume_basis.
Cross-edge QA must execute actual Reader.read_components and the unchanged
current Main Feature function's metadata, RAW pairing and anchor logic, pinning
consumer/helper bytes, AST and loaded provenance. Heavy Main imports stay out
of Source's sparse dependency closure. Fixture execution is not actual consumer
ACK, accepted publication, Source/PIT admission, economics or activation.
Actual missing rights/identity/clocks/status/trust still block real preparation.
Existing point asset responses are raw identity facts, not full historical
identity/lifecycle/halts/volume proof; their existence is not denied because a
typed consumer document has yet to be prepared.
