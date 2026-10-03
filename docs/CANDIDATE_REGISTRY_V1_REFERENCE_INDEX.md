# Candidate Registry V1 — I0.1 reference adapter

Owner: existing issue #516. Classification: H1 reference/integrity plumbing.
This document describes a proposed code slice, not an accepted runtime.

## Scope

`research/candidate_registry_v1.py:build_reference_index` links a caller-supplied
A3 packet and the saved result of the **existing**
`a3_candidate_packet_v1.evaluate_packet`. It resolves actual bytes, verifies raw
SHA-256, replays the existing deterministic A3 validator, and compares the
entire saved result to the replay. It never repeats Methodology/Moat research,
clinical review, source collection, or expected-return modeling.

There is exactly one supplied row per asset/security. Duplicate asset IDs
(including identical duplicate rows) reject the whole invocation. Different
securities of one issuer remain different rows. This module does not determine
which candidate revision is current: that selection must be authenticated by
A0 against the existing approved artifact/receipt machinery. It neither writes
a current pointer nor replaces a persisted registry.

## Callable API

```python
from research.candidate_registry_v1 import build_reference_index

proposal = build_reference_index(
    entries, cutoff="2026-09-29T07:00:00Z", artifact_resolver=trusted_resolver
)
```

Each entry has exactly:

```text
asset_id
issuer_id
a3_packet_ref
a3_result_ref
```

Both references have exactly:

```text
artifact_id      # opaque immutable ID, not an instruction to fetch a URL
sha256           # lowercase, exact raw-byte SHA-256
available_at     # timezone-aware ISO-8601 timestamp
collected_at     # timezone-aware ISO-8601 timestamp
expires_at       # explicit aware timestamp, or explicit null = unknown
```

The caller supplies `trusted_resolver(artifact_id, sha256) -> bytes`. Reuse the
existing A0/Drive/GitHub-approved artifact resolution boundary. This module
performs no network access or filesystem writes. An injected callback must
itself be read-only; this function is not a security sandbox for callbacks.
Do not grant it credentials, write capabilities, or unchecked arbitrary URLs.

`available_at <= collected_at <= cutoff` is mandatory. Packet availability
must not precede its recorded review, and result availability must not precede
packet collection. No publication/collection time is filled from today's date.
An expiry before collection is invalid; `expires_at <= cutoff` is expired.
An explicit null expiry stays UNKNOWN. These descriptors must still be
independently authenticated by the caller. They cannot manufacture freshness.

## What is verified and what is not

A valid row has `reference_status=A3_REFERENCE_REPLAY_VERIFIED`. This proves
only internal byte/identity/contract consistency in the supplied reference
set. A coherent forged set can be internally consistent: hash matching and
`REVIEWED` strings are not proof of an independent review. Accordingly:

```text
authority                         = PROPOSAL_NOT_CANONICAL
scope                             = SUPPLIED_REFERENCE_SET_ONLY
review_authentication_status      = NOT_VERIFIED
current_selection_status          = NOT_VERIFIED
domain_admission_status           = NOT_VERIFIED
research_freshness_state          = NOT_CERTIFIED
A5_eligible_input                 = false
reuse_authorized                 = false
selector/target/ledger/order/production authority = false
```

`declared_expiry_state=UNEXPIRED` is NOT `research_freshness_state=CURRENT`.
Expiry, due catalysts, source collection failures, corrections/retractions,
market completion, and outcome maturity still require I0.2/current A0 evidence.
This module never emits SKIP_UNCHANGED. Deterministic equal outputs alone do
not authorize reuse or a DONE transition.

The output references upstream artifacts and their raw byte hashes; it does
not copy reports, scenario returns, ER values, portfolio weights or rankings.
Missing validated ER stays `validated_er_ref=null`. Even when the old A3 result
declares `VALIDATED_ER_LINKED`, that immutable ER reference needs separate
#510/#503 economic/domain/freshness admission. The saved A3 result's horizon
map omits the raw drawdown/downside fields; it cannot replace the original
ER/risk artifact at the A5 boundary.

The packet raw-byte SHA-256 and its existing A3 `packet_sha256` are different
identities: the latter is a canonical semantic JSON hash. Reformatting packet
bytes may change the former without changing the latter. Both are retained.
Canonical comparison also distinguishes false from numeric zero, unlike normal
Python object equality.

## Rejection and resource limits

Unknown/malformed security identities, duplicate security rows, an immutable
artifact ID mapped to conflicting hashes, and shared-budget exhaustion reject
the entire call with `ReferenceIndexError`.

An identifiable security with missing/corrupt/future/malformed evidence remains
in `records` as BLOCKED, with a bounded reason code and closed authority. It is
not silently removed from the cohort. The top-level state becomes
REFERENCE_ERRORS_PRESENT. An empty list yields EMPTY_INPUT, never readiness.

Structured packet/result/dependency JSON rejects duplicate keys, non-finite
numbers (including exponent overflow), excessive depth and excessive nodes.
Raw source documents remain arbitrary hash-checked bytes as required by A3.
Provider exception text is not copied into results because it may contain
credentials. Limits: 10,000 entries, 64 MiB per blob, 128 MiB resolved bytes per
invocation, depth 64 and 100,000 decoded JSON value nodes per object. Limits are
engineering bounds, not investment-universe coverage claims.

Each exact ID/hash is resolved once per invocation, including provider, type,
empty, oversize and hash failures. Every returned byte buffer is charged before
per-blob rejection; failure reasons retain neither provider text nor traceback.
A fresh invocation retries rather than reusing an earlier failed snapshot.

Top-level identities are registered without resolving future references.
Packets whose packet/result collection clocks are eligible are then decoded;
all syntactically valid nested ID/hash pairs are registered before row-local
asset, issuer, review or dependency validation. Eligible structured dependencies
are independently decoded in this preflight so an earlier failing dependency
cannot conceal later raw-source or market-source identity conflicts. Raw source
documents remain arbitrary bytes, never JSON-decoded by this adapter.

Registry and its A3 replay share A3's private verified-artifact cache. The cache
accepts only resolver bytes, verifies raw hashes and strict JSON resource/type
limits, and accepts no caller-provided decoded dictionary or decoder. A3's
default three-argument API preserves its existing behavior. Explicit optional
cache reuse still validates every row's kind, clocks, asset/issuer identity and
economic authority; cache hits preserve the row's raw-reference read tracking.

Full packet and dependency preflight attempts are memoized by exact ID/hash
within each invocation. Nested descriptors are traversed once per decoded
identity, including shared packet/dependency roles; no repeated packet is
appended to the dependency phase. All syntactically valid packet descriptors
are registered before clock gating, but nested bytes/cache access requires
available_at <= packet as_of <= cutoff. A future context does not mark the
dependency attempted, so another eligible packet can still inspect it.

The optional verified cache seals decoded dictionaries and arrays once into
read-only JSON views. Every nested container is sealed; cached objects cannot
be changed through returned views. Explicit JSON export creates ordinary mutable
copies without altering retained evidence. Cache hits return the same sealed
view with no copy, decode, sealing traversal or raw rehash per row. A3 accepts
these private internal views while preserving ordinary dict/list API results,
rejecting ordinary tuple packet fields, and checking raw byte/hash gates.

## BIO/CLEAN and cross-market boundary

No sector-specific score, sleeve cap, or BUY/SELL rule exists here. US/KR BIO and
CLEAN synthetic fixtures exercise the same reference route. Country, currency,
benchmark and asset class are copied from the validated packet/market artifact,
not inferred from a ticker prefix or converted through the US Theme/ETF bridge.

These fixture labels do NOT certify actual KR prices, market adjustment basis,
clinical evidence, project economics, domain profiles or historical PIT. A3's
existing rules remain unchanged; this slice neither weakens them nor expands
their real-data approval scope. Actual domain adapters are still separate work.

## Verification and remaining work

Run:

```text
python tests/candidate_registry_v1_smoke.py -v
python tests/a3_candidate_packet_v1_smoke.py -v
python -O tests/a3_candidate_packet_v1_smoke.py -v
```

The existing A3 smoke entrypoint loads the new RegistryTests through unittest's
load_tests hook. The current `tests/smoke_test.py` structural A3 test calls that
entrypoint and `tools/run_pr_validation.py` already includes smoke_test.py.
No protected validation runner, workflow, safety gate or source evaluator is
modified. Full-repository execution and CI are still required at integration;
a scoped source staging run is not full CI or an independent A6 review.

Not implemented here: persistent one-current-record materialization; A0 task
wiring; full source/profile admission; delta planner; authenticated review and
freshness; A5 input consumption/sizing; collectors; scheduling; durable Drive
writes; retention/deletion; live/paper/target mutations. Progress to I0.2/I0.3
only through separately scoped work under the same #516 ownership.

## Operational lesson

### 2026-10-03 cross-phase review corrections

The subsequent hosted review of `dbaa7ebfbf2e105386b6011ef0a51cb85b7a5234`
found repeated nested scans, future nested access before A3's clock rejection,
and mutation of retained decoded dictionaries. Bounded before/after probes
measure actual traversal and resolver access, and reproduce the mutation
attack. The full-size synthetic regression uses one 100,000-node packet across
10,000 invalid asset rows and guards against a second large traversal. It
requires one packet scan, 100,000 node visits, 100,001 sealing visits including
the shared empty result, two JSON decodes and two provider reads. Additional
cases cover shared large dependencies, fresh invocation scope, every nested
role/clock boundary, warm-cache future contexts and descriptor conflicts.

The exact-head hosted review on `bc49b983916fb89fc6cd8ac7df0b32e2f2d227e4`
found four gaps across byte accounting, failed reads, nested identity preflight
and A3's downstream JSON parsing. These corrections cover the whole invocation
with rejection-phase matrices, both input orders, fresh-invocation retry,
actual JSON/hash call instrumentation and an exact-budget positive control.
Synthetic fixtures establish plumbing invariants only. They grant no source,
domain, economic, reuse, A5 or portfolio authority.

### 2026-10-02 current-master integration

PR #560 source head `51fca95deb2e9b7a8a139807b0466cb467f16bcf` was integrated
with master `30915e05c1ffe3cecd2c46b229af20844e514f3d`. The only conflict was
the shared lessons ledger; both sides' entries were retained. The registry,
A3 test hook and registry tests were already corrected at the source head and
were preserved byte-for-byte. No evaluator or protected workflow is changed
relative to current master.

Local Python 3.12 validation: 50 registry cases and 65 cases in the integrated
A3 entrypoint passed; the latter also passed with `-O`. The registry cases are
included in the 65 integrated cases. A scoped PR validation run passed
`smoke_test.py`, `agent_shared_lessons_contract_smoke.py` and
`run287_agent_github_operating_standard_smoke.py` using Python 3.14.
These local results do not replace current-head required CI, independent
review or review-complete. The PR stays Draft pending those gates.

Byte-valid stored research must be replay-bound to its packet and source
references before indexing, but replay does not authenticate a reviewer or
current pointer. Do not map a local reference pass to A5 readiness. Preserve
expired/unknown and rejected records, and keep raw hashes separate from
semantic packet hashes. Reuse the existing A3 smoke route rather than modifying
protected runner/economic gates to accommodate a plumbing change.
