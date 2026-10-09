# Shared Research Data V1 reader — #590

Task: `R1000-A1-H1-SHARED-RESEARCH-DATA-V2-20261008`.
Base: `37046b734eccba9176d091c0fcc2745f5050a8e3`.
Owner: the user-designated Source/Data implementation lane, with a separate
independent A6 reviewer. Initial scope: H1, research bytes only; Draft PR, no
merge. The 2026-10-09 approved pre-merge corrections affect the Reader, its
tests, this evidence note and a concise shared lesson; other implementation
lanes and the shared runner remain intact. The checked-in registry
has **zero admitted generations** and `source_manifest_complete=false`.

## Contract and reuse

`tools/research_data_access.py` is an additive read API. Existing collectors,
backtesters, `tools/build_data_catalog.py`, the freshness contract and Lake v1
remain intact. The logical registry maps `ds.us.prices.daily` to the existing
price inventory/producer. It is a discovery map, not a replacement catalog.

The generation ID is the SHA256 of the **exact manifest bytes**, including the
schema, identity, periods, file hashes, original clocks and source lineage.
There is no `latest` resolution. Restoring an old generation never selects a
newer generation. The archive paths below the already configured research
transport are:

- `shared-research-v1/generations/<generation-sha256>` — UTF-8 manifest;
- `shared-research-v1/objects/<file-sha256>` — exact file bytes.

These paths specify a future reviewed publication contract; this PR neither
publishes a generation nor creates a Drive folder. The Reader accepts an
already configured transport and invokes only `read`. It does not instantiate
`RcloneTransport`, whose legacy constructor may create missing directories.
No provider import, collection, refresh, cache search or fallback occurs.

The existing `Lake` still validates commit chains, catalogs, packs and linked
execution/quality reports. `pinned_lake()` restricts its read-only transport
view to the explicitly named commit's ancestors and receipt. No Lake source or
legacy latest-reader behavior changes. Lake-backed generation entries bind
each file to the selected dataset's normalized object, not an arbitrary pack.

## Minimal price schema

JSONL, existing Lake `gzip_jsonl`, and typed Parquet are supported. Parquet
requires pyarrow and an exact Arrow schema: string identity/date/availability
columns and float64 OHLCV columns. An unavailable engine refuses the read.
Raw legacy yfinance Parquet is not silently normalized by this Reader; a later
reviewed producer binding must provide this declared view.

The pinned generation shares a 256 MiB conservative decoded/retained-object
budget and 1,000,000-row ceiling across every partition and format. JSONL and
gzip JSONL charge expanded bytes plus retained Python objects, including
malformed nested rows; each line is capped at 64 KiB before JSON decoding.
Parquet charges actual Arrow buffers, retained rows and transfer bytes. Native
decoding uses a fresh Linux process with a 512 MiB address-space ceiling plus
CPU, wall-time and output limits; batch size alone is not a memory-safety claim.
Failed or unsupported workers return a finite refusal and no partial rows.
PyArrow 15-20 omit the newer extension keyword while retaining the mandatory
primitive schema and metadata limits; newer engines disable extensions explicitly.

Required columns: `instrument_id`, `ticker`, `session_date`, `available_from`,
`open`, `high`, `low`, `close`, `volume`. All columns are required. OHLC must
be finite, positive, non-boolean and consistent; volume may be genuine zero.
Each partition declares stable identity, market, MIC, timezone, calendar,
currency and adjustment basis. Rows must match that identity, be sorted and
have unique instrument/session keys across all partitions. Declared bytes,
rows, schema and exact date bounds are independently checked.

The API takes explicit dataset/generation, purpose, decision time, instrument
IDs, start/end and minimum row count. Optional `required_sessions` checks an
exact caller-supplied calendar window, including internal gaps. Without it,
the receipt reports `requested_session_coverage_verified=false`; date endpoints alone
are not a full exchange-session audit. Calendar provenance, historical universe,
lifecycle and adjustment-source admission remain A1 responsibilities. Matching
the caller's list is not authentication of a calendar source; every receipt
separately keeps `calendar_source_verified=false`.

All original timestamps require an explicit timezone with valid offset fields;
the unknown local offset `-00:00` is refused. Manifest/source/row
availability, collection and expiry are checked before slicing; future or
unknown clocks fail. Research/discovery can retain declared `PIT_PROXY`.
Training/backtest reads require declared verified PIT, real-source
classification and purpose/license permission. They also require an explicitly
supported NYSE/XNYS calendar, America/New_York timezone and XNYS/XNAS MIC.
For those identities, every daily bar must become available at or after its
actual session close, resolved through the existing offline NYSE holiday and
half-day schedule. Unknown calendars or schedule failures refuse training and
backtest; there is no weekday or fixed-hour fallback. Delayed publication
retains its original row/session clock. Research/discovery retain synthetic
calendar compatibility and no calendar-admission claim. These checks enforce a pinned
manifest's contract; they do not authenticate those declarations or approve
economics. Every success receipt has `eligible_for_economics=false` and
`eligible_for_selector=false`.

Source lineage includes provider/license/access policy, raw source hashes,
source receipt hash, producer code/config hashes and source_run_id. Source
receipt hashes are references, not new admission receipts. `RESEARCH_BYTES_ONLY`
is the sole supported admission state. Unknown material identity/PIT/license
fields and unsupported storage refuse the read.

## API

```python
from tools.research_data_access import ResearchDataReader

# transport is already authenticated/configured outside this module.
reader = ResearchDataReader(transport)
result = reader.read(
    "ds.us.prices.daily", exact_generation_sha256,
    decision_time=original_aware_decision_time,
    purpose="research", instrument_ids=verified_instrument_ids,
    required_start=first_session, required_end=last_session,
    minimum_rows=required_observations, required_sessions=frozen_sessions,
    consumer_id="feature_builder", restore_to=isolated_research_directory,
)
# result.files contains exact SHA256/bytes, result.rows the selected records,
# and result.receipt the generation, source and row-set identities.
```

The archive is re-read and re-hashed for each consumer. Optional local restore
uses the existing immutable-write helper and freshness file-hash helper.
Restored files and `cache_prices` are convenience copies. A missing or changed
archive object blocks even if an intact local copy exists.

## Validation and reusable lessons

`tests/research_data_access_smoke.py` exercises two separate consumer instances
(feature calculation and coverage audit), restores into separate directories,
and compares generation/hash/eligible row-set/byte identity. All prices,
identities, source receipts and calendars in these tests are synthetic contract
fixtures. They are not real-source admission evidence.

The existing registered `tests/long_history_lake_smoke.py` loads this suite;
the shared validation runner requires no change. Run both scripts in normal
Python and `python -O`.
The Parquet case explicitly checks dependency refusal when pyarrow is absent;
with repository CI dependencies it performs a real typed Parquet round-trip.

Historical initial minimal-environment evidence was Python 3.12.10,
40 Reader + 51 Lake = 91 unique methods, normal/-O, without native Parquet.
The correction at `31f7e0e11b65981401cc6dcb9192253306c6f7b8` increased this to
53 Reader + 51 Lake = 104 methods, independently executed with PyArrow 23.0.1.
The subsequent formal-review corrections add seven Reader methods:
**60 Reader + 51 Lake = 111 unique methods**. Local native Python 3.12.14
verification uses PyArrow 23.0.1; the supported older 15.0.2 and 20.0.0 engines
also execute all 60 Reader methods. The exact-head GitHub receipts distinguish
author runs, separate A6 executions and native CI. Repeated runs, optimized
variants and subcases do not increase the unique-method count. Native tests
prove synthetic contract compatibility and refusal, never real-source admission.

One author verification command incorrectly used the runner's additive
`--include` option. It started the full suite, observed dependency/import
failures in the minimal local environment, and was interrupted. This is not a
full-suite PASS. The bounded runner command is
`python tools/run_pr_validation.py --only long_history_lake_smoke`.

Independent A6 identified invalid timezone offsets normalized by the legacy
parser and oversized JSON integers leaking a raw numeric overflow. Both now
produce finite contract refusals, with source/row-clock and OHLCV regressions
in normal and optimized Python. Valid explicit offsets retain their meaning.

Lessons: a latest catalog cannot reproduce an earlier generation; restrict the
legacy reader's transport view without changing its validators. A verified
cache cannot substitute for unreadable source bytes. Preserve timestamp
awareness before calling a legacy date parser. Distinguish byte integrity from
source approval and endpoint coverage from complete exchange-session coverage.

## Remaining dependencies

- A1 real-source normalized generation, immutable restore/readback and admission;
- FINAL_REQUIRED universe and row-level calendar/lifecycle/corporate-action audit;
- accepted source receipts, availability and licensing evidence;
- P1-B separate causal PR binding all source groups, candidate-input stability,
  resolved_session_date, target identity and independently rebuilt runtime
  source identity; no Stage A/B workflow changes here;
- normal/-O native tests, new exact-head required CI and independent A6;
- explicit future economic/Fullrun approval. July R0 and R1 remain blocked.

G0 PASS, Source Manifest COMPLETE, 7Y economic validation, portfolio/paper/broker
changes and production/publication approval are not claimed or enabled.
