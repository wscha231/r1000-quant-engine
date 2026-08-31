# Run287 Chameleon forward/PIT archive result — 2026-08-30

## Outcome

The next Chameleon data layer is implemented as an isolated, report-only,
append-only observation archive. It records exact source capture times, raw
response hashes, normalized-row hashes, code and contract identity, immutable
snapshot identity, and a chained archive index.

Official network captures are labelled FORWARD_PIT and can be used only from
their exact capture time. Fixture or supplied-file captures are always
FREE_PROXY. This collector never emits PIT_VERIFIED and does not authorize
historical A/B.

## Sources

- FRED/ALFRED uses the official series/observations API with explicit
  realtime_start and realtime_end. The API key is accepted only through the
  FRED_API_KEY environment variable and is never written to persisted request
  metadata, manifests, errors, or archive rows.
- VIX, VIX3M, and VVIX use the official Cboe history sources.
- Current equity and index put/call ratios are extracted separately from the
  official Cboe Daily Market Statistics response and cross-checked against
  their corresponding call, put, and total volume. The selected date must be
  no more than one holiday-aware completed NYSE session behind the capture.
- Cross-asset daily closes have a strict source-bundle schema but remain
  FREE_PROXY until a trusted network provider is registered.

Official references:

- https://fred.stlouisfed.org/docs/api/fred/series_observations.html
- https://fred.stlouisfed.org/docs/api/fred/series_vintagedates.html
- https://www.cboe.com/tradable_products/vix/vix_historical_data
- https://www.cboe.com/markets/us/options/market-statistics/daily
- https://www.cboe.com/us/options/market_statistics/historical_data/

## Important source correction

The initially inspected Cboe equity/index put-call archive endpoints ended in
2012 and therefore could not represent current options sentiment. The
collector does not use those legacy endpoints for the current signal. It uses
the Cboe Daily Market Statistics page, whose captured 2026-08-31 response
identified the completed 2026-08-28 session and exposed equity and index
ratios separately.

## Archive invariants

- Same collection time plus identical payload is idempotent and returns the
  original manifest and archive-index receipt hashes.
- Same collection time plus changed payload is blocked.
- Older collection times are blocked.
- Every raw and normalized object is content addressed by SHA-256.
- Existing snapshot, index-chain, or content-object tampering blocks the next
  collection before a new snapshot is created.
- One complete snapshot left unindexed by an interruption is revalidated down
  to its identity, safety envelope, source counters, and content objects before
  its missing index entry is recovered. Multiple or invalid orphans block.
- A present but invalid source blocks the complete snapshot. A missing source
  is recorded as missing and is never carried or imputed.
- Official responses are streamed through the 100 MiB bound, and every
  redirect hop must remain on the approved HTTPS origin. Only a query-free
  sanitized final URL is persisted.
- Cross-asset provenance URLs containing userinfo, query parameters, or
  fragments are rejected before any raw object is written.
- FRED response-level and row-level vintage dates must match the requested
  vintage date.
- Equity and index put-call components cannot substitute for one another.
- available_from equals the exact source capture timestamp. No observation
  may have a future source date.
- Fixture time injection is allowed only in explicit fixture mode. Normal
  network collection uses the runtime clock and preserves its microseconds.
- One OS-level advisory writer lock covers orphan recovery, capture, snapshot
  commit, and index commit so concurrent processes cannot fork the chain.
- A successful FRED response that contains the active API key, including its
  recursively percent-encoded or JSON-escaped form, is rejected before any raw
  object is persisted.
- Cboe and cross-asset text is decoded as strict UTF-8 with an optional BOM;
  malformed bytes, unterminated quotes, or bare quotes inside unquoted fields
  block the snapshot instead of being repaired.
- Every FRED observation must remain inside the inclusive requested window and
  arrive in the declared strictly ascending order.
- FRED JSON rejects duplicate keys and requires true non-boolean integers for
  count, limit, and offset metadata; every non-finite number is rejected.
- Official network collection requires the executed builder bytes to equal the
  exact tracked builder blob at the recorded Git head.
- An official Cboe index row newer than the latest completed NYSE session is
  rejected rather than being labelled a close.
- Once the snapshot/index commit revalidates, a failed mutable last-attempt
  receipt is reported as receipt failure without relabelling the commit blocked.
- Percent-decoding scans every decoded depth including the final pass and
  rejects excessive nesting; abandoned exact local staging directories are
  removed only while the single-writer lock is held.
- Staging cleanup rejects mount points before traversal, provenance URLs reject
  whitespace and controls before component parsing, and every Cboe index
  history must contain a close no more than one completed NYSE session old.
- Orphan recovery requires the exact canonical source set and definitions;
  only NYSE-session Cboe closes are normalized while raw non-session rows are
  retained and counted, future fixture timestamps are rejected, and official
  network bodies are accepted only with HTTP 200.
- Redirects are issued manually only after each next Location is validated as
  same-origin HTTPS; cross-asset provenance rejects whitespace mutation,
  localhost/non-global IPs, and Unicode controls in CSV evidence.
- Recovery reparses canonical normalized JSONL and verifies row count, source,
  truth class, raw hash, capture timestamps, bounds, and excluded-session
  separation before a snapshot can be indexed.
- Recovery also replays each source's exact schema: FRED series and vintage,
  Cboe instrument/value/volume fields, and cross-asset ticker, price basis, and
  public provenance. The complete downstream handoff must still equal the
  report-only contract, so an orphan cannot enable backtests or portfolio use.
- When no orphan exists, the recovery path reuses the index entries it just
  fully validated instead of rereading every historical object a second time.
- Orphan recovery re-runs the source normalizer against every content-addressed
  raw object and requires an exact match with the archived normalized rows.
  Recovered FRED rows also retain strict order, unique dates, and the exact
  seven-year window ending on capture; recovered Cboe data must remain fresh.
- Both orphan and already-indexed manifests must keep
  `pit_verified_emitted=false`; this forward-only collector cannot be upgraded
  to PIT_VERIFIED by recomputing local hashes.
- Indexed snapshots reuse the same complete manifest, source-state, counter,
  object, and snapshot-identity verification as orphan recovery. Archive-index
  and manifest JSON reject duplicate keys.
- Raw replay enforces the configured size cap before reading and scans with the
  currently active FRED key, so recovery cannot authorize oversized or
  credential-bearing evidence that normal capture would reject.
- Every captured raw source, including Cboe and cross-asset fixtures, is scanned
  for the active FRED key before any content object is written. Indexed source
  bytes are re-normalized, and index coverage counters must equal the verified
  manifest.
- The canonical contract uses duplicate-key-rejecting JSON. Archive roots and
  durable subdirectories reject both symlinks and Windows junctions, while
  official-network snapshots must resolve the recorded collector blob from the
  recorded Git commit and match its SHA-256.
- Individual snapshot directories also reject junctions. Manifest fixture mode
  must agree with every present source mode before any builder exemption, and
  recovered collection/source capture times must remain at or after launch and
  in causal order.
- Recovery scans every raw source type for the active key before normalization,
  matching the common pre-persistence secret boundary.
- Recovery also rejects collection or source capture timestamps later than its
  runtime clock, and scans both raw manifest bytes and recursively decoded
  manifest values for the active key before accepting any snapshot authority.
- Recovered object references are role-bound: raw digests must remain under
  `objects/raw` and normalized digests under `objects/normalized`.
- Every recovered source audit record must match its exact status-dependent
  schema. Cboe and cross-asset request metadata and missing-value counters must
  retain their canonical values, and unknown top-level manifest fields are
  rejected so a recomputed hash cannot invent new authority.
- Raw secret scanning recursively percent-decodes every source before initial
  persistence and during recovery, and also decodes JSON Unicode escapes, so
  encoded active keys cannot hide in an otherwise unused Cboe or cross-asset
  field.
- Fixture files are size-checked before bounded reading. The exact
  `pandas_market_calendars==5.3.2` NYSE engine is pinned and included in the
  snapshot identity, and cross-asset close dates must be completed NYSE
  sessions at capture time.
- Cross-asset provider provenance rejects leading/trailing whitespace and all
  Unicode control, format, and surrogate characters before any immutable
  object or index entry is committed.
- A recorded 40-hex `git_head` must resolve to a Git commit object before the
  collector blob at that revision can establish builder identity; a tree or
  other Git object is not accepted as a commit, including in fixture recovery.
- A nonempty malformed `FRED_API_KEY` blocks the run instead of becoming an
  empty scanner key, and persisted collection/capture UTC fields reject
  leading or trailing whitespace before exact RFC3339 parsing.
- Missing-source audits retain only their canonical zero/empty exclusion and
  object metadata, with a reason compatible with the source family and
  fixture/network mode.
- Every bounded raw source is secret-scanned before parsing can derive a
  durable blocker, and a present directory, link, junction, or other
  non-regular fixture entry blocks instead of being recorded as missing.
- Every fixture ancestor must be an ordinary directory and its resolved leaf
  must remain beneath the selected bundle root. Recovered official-network
  `resolved_url` values must already equal their query/fragment-free canonical
  form, and special-use/private DNS suffixes are rejected as non-public.
- Both consumed-input rechecks also revalidate the selected root and reuse the
  original per-source size cap, so a swapped root or oversized replacement
  cannot obtain a new allowance from mutable filesystem state.
- Public provenance rejects every domain and descendant in the IANA
  Special-Use Domain Names registry frozen at 2026-05-22, including the
  example.com/net/org and registered ARPA subtrees.
- Same-time idempotent reuse runs the complete snapshot verifier after source
  collection and constructs its receipt only from the verified in-memory
  manifest, so a concurrent manifest mutation cannot inject authority.
- Snapshot manifests are file-synced before the staging directory is synced
  and durably renamed. The snapshots directory is then synced before the
  atomically replaced and parent-synced archive index becomes authoritative;
  Windows uses write-through replacements for the equivalent boundary.
- A fresh archive creates each layout directory through a durable rename and
  syncs both the directory and its parent, so `objects/raw` and
  `objects/normalized` cannot disappear behind an already durable index.
- Same-time reuse performs one final consumed-input and builder-identity check
  after full snapshot verification and before writing the idempotent receipt.
- Recovered raw objects are stat-bounded by the contract before their first
  complete hash pass, preventing oversized corruption from monopolizing the
  archive-wide writer lock.

## Local official-network proof

At 2026-08-31T15:01:03.407090Z, a local report-only network proof archived four
official Cboe sources and 18,585 normalized NYSE-session rows:

- cboe.daily_put_call: two rows for 2026-08-28.
- cboe.vix: 9,228 rows, latest 2026-08-28; 33 provider-supplied
  non-session rows remained in raw evidence and were excluded from normalized
  observations.
- cboe.vix3m: 4,262 rows, latest 2026-08-28.
- cboe.vvix: 5,093 rows, latest 2026-08-28.

Snapshot ID:
20260831T150103Z-cf380d58f2ba2fc2

Snapshot manifest SHA-256:
87cfda1aec83a17fcaef60a9b2ad3276f6dda4e2bdc4238953a23760484d1d91

This proof is local and is not a canonical durable publication. Thirteen
FRED/ALFRED series remained missing because no FRED_API_KEY was present.
Cross-asset closes remained missing because no trusted network provider is
registered. Missing inputs were not synthesized.

## Validation

The dedicated smoke covers:

- complete fixture capture and safety envelope;
- fixture FREE_PROXY versus network FORWARD_PIT;
- secret exclusion;
- idempotent retry and same-time conflict;
- out-of-order capture rejection;
- FRED vintage and duplicate-date rejection;
- Cboe equity/index separation;
- missing cross-asset neutrality;
- existing-object tamper detection;
- credential-bearing provenance, oversized response, redirect-origin, empty
  response, stale options session, and interrupted-index recovery guards;
- runtime capture-time microsecond preservation, concurrent-writer rejection,
  FRED response secret-echo rejection, and idempotent receipt preservation;
- malformed UTF-8 rejection and per-row FRED request-window/order enforcement;
- strict CSV quoting, duplicate-key and exact-integer JSON checks, decoded JSON
  secret scanning, and builder-to-Git-head byte binding;
- recursive percent-decoding, non-finite JSON rejection, bare-quote detection,
  dirty-fixture orphan recovery, completed-session close enforcement, and
  post-commit receipt-failure semantics;
- final percent-decode inspection and locked abandoned-staging recovery;
- mount-boundary cleanup rejection, provenance URL whitespace/control
  rejection, and completed-session freshness for Cboe index histories;
- canonical orphan-source topology, counted non-session row exclusion,
  future-fixture rejection, and exact HTTP-200 transport completeness;
- preflight redirect validation, public-host provenance, Unicode-control
  rejection, and normalized-object semantic recovery validation;
- source-specific normalized-row replay, exact downstream-handoff recovery
  validation, and single-pass no-orphan index reuse;
- exact raw-to-normalized recovery replay, duplicate/ordered/canonical-window
  FRED recovery, Cboe recovery freshness, and indexed PIT-upgrade rejection;
- active-key and raw-size recovery guards, duplicate-key archive-index parsing,
  and shared full identity/source-state validation for indexed snapshots;
- all-source pre-persistence secret scanning, indexed raw replay and coverage
  binding, strict contract JSON, junction rejection, and recorded Git-blob
  verification;
- per-snapshot junction rejection, fixture/source-mode alignment, launch and
  capture chronology replay, and all-source recovery secret scanning;
- recovery-time future bounds and raw/decoded manifest secret scanning;
- raw/normalized namespace role binding, exact source-audit schemas,
  canonical non-FRED audit metadata, and unknown manifest-field rejection;
- recursively decoded all-source secret scans, fixture pre-read size bounds,
  pinned calendar identity, and completed-session cross-asset close checks;
- pre-persistence provider-control rejection and recorded Git commit-object
  verification;
- fixture commit-object verification, malformed-key fail-closed behavior, and
  canonical unpadded persisted UTC parsing;
- all-source JSON Unicode-escape secret rejection and canonical missing-source
  zero/empty metadata plus source/mode-compatible failure reasons;
- pre-parser secret rejection that keeps encoded raw values out of failure
  receipts, plus fail-closed present non-regular fixture entries;
- linked fixture-ancestor/root containment, canonical persisted resolved URLs,
  and reserved/private DNS-suffix rejection;
- repeated bundle-root validation and reuse of the original fixture-size cap
  during consumed-input checks;
- complete IANA special-use subtree rejection, post-collection same-time
  manifest re-verification, and staged snapshot/index durability ordering;
- durable creation of every fresh archive-layout ancestor, final fixture
  recheck on same-time reuse, and pre-hash recovered-raw size rejection;
- pre-launch and caller-injected network time rejection.

The dedicated smoke and Python compilation passed. The official Cboe network
proof also passed after the stale legacy options endpoint was removed.

## Remaining boundary and next causal change

This change does not feed the macro engine automatically. The next isolated
change should materialize only hash-verified archive observations into the
existing report-only macro normalizer, while preserving available_from and
missing-source semantics. Durable scheduling requires a separately approved
publication destination and repository secret configuration; no workflow was
dispatched here.

Historical backtest, market-state portfolio routing, fear/greed allocation,
holding exits, target/order generation, accepted-head mutation, production,
live trading, and automatic promotion all remain blocked.
