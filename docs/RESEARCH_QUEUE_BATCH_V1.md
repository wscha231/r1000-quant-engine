# Local incremental research queue V1

`tools/run_research_queue_batch.py` is a bounded local wrapper around the
unchanged `run_research_backend_connection.run_bundle`. It connects supplied
original bytes to the existing C research/Registry/A8 adapter and D risk adapter.
No provider, Drive, collection, AI, scheduler or investment mutation is added.
Useful partial research can advance even when another independent case is missing.
Research success remains distinct from Source/PIT, ER, A5 or production admission.

## Explicit queue manifest

The queue JSON has exactly `schema`, `queue_id`, `as_of`, `cases`, `authority`.
Schema is `research-local-queue-v1`; authority has exactly the existing backend
authority keys, all exact JSON false. Queue as-of is timezone aware and cannot
be future dated. Input root and new output directory are separate explicit
API/CLI arguments, outside the code tree and each other. There is no latest-file
discovery. Output leaf starts `research-queue-` and its parent must exist.

Each case has exactly these fields:

| Field | Contract |
| --- | --- |
| `case_id` | Stable allowed ASCII ID, unique in this batch |
| `bundle_path` | Relative original backend manifest under trusted input root |
| `bundle_sha256` | Exact original manifest SHA256 |
| `as_of` | Exact backend cutoff, no later than queue as-of |
| `identifiers` | Exact security_id, issuer_id, benchmark_id matching bundle |
| `valid_through` | Explicit current case expiry, separate from source clocks |
| `review_due_at` | Explicit aware review clock or null |
| `correction`, `source_failure`, `outcome_due` | Exact booleans, always reviewed when true |

Original backend input schema, descriptor byte hashes, supplied clocks, code
pins and identity contracts are still checked by `run_bundle`. Every present
bundle's paths are security scanned before any case is invoked. Traversal,
links/junctions, escaping roots, duplicate IDs or open authority refuse the
batch. An ordinary unavailable bundle, missing input or hash mismatch blocks
that case and permits independent valid cases to proceed.

| Case status | Meaning |
| --- | --- |
| `INPUT_BLOCKED` | Missing/invalid bytes, metadata or exhausted input/attempt budget |
| `RAN_LOCAL_RESEARCH` | Actual C and D calls returned, exact local acceptance and readback observed; inner result may remain BLOCKED |
| `SKIP_UNCHANGED` | Issuing live process retains actual accepted return and current bytes/identity/dependencies still match |
| `REVIEW_DUE` | Expired, corrected, source failed, outcome due, tampered accepted bytes or unresolved previous intent |

`RAN_LOCAL_RESEARCH` does not mean a complete Thesis, usable market risk signal,
eligible Registry selection or admitted ER. The full returned backend result
remains in the case's physical output; its stage refusals are not erased.

## Live reuse and restart boundary

The existing backend deliberately writes only UNACCEPTED/PREPARED_ONLY disk
receipts. Acceptance is returned after identity/hash readback. This queue never
reconstructs that acceptance from disk, a result status or a hash.

`QueueSession` retains actual return proofs privately in the issuing process,
only after the queue's progress record also passes atomic publication/readback.
Repeated `session.run(manifest_path)` can reuse unchanged results. Current case
and descriptor expiry, correction/source-failure/outcome flags, exact bundle,
actual descriptor hashes, repository Python/config bytes and loaded repository
module identities are rechecked. A changed input/config/code/dependency creates
a distinct bounded intent, rather than relabeling an old result as a new PASS.
Repository Python/config hashing is conservative; even an unrelated included
file change invalidates reuse. This is not authenticated remote HEAD evidence
or a complete interpreter/native-library closure.

The session cannot be serialized. A new process/CLI refuses an existing queue
root: explicit owner recovery is required. There is **no automatic durable
cross-process resume or skip** in V1. Do not create another root automatically
to bypass exhausted budgets or ambiguous outcomes. That requires a separately
reviewed continuation contract with retained actual acceptance, not another
hash-based success marker. Existing disk results are evidence for inspection,
never a restored capability.

## Bounds, intents and publication

Caller limits can only lower defaults: 16 cases per batch, 16 total attempts,
64 MiB reserved original case input bytes, 60 seconds session lifetime and
32 progress records. Each original case is also bounded by the backend's
32 MiB input/4 MiB per-file and 16 MiB output limits. These are local research
limits, not collection campaign quotas. Input reservation counts original
case bytes, not all local filesystem I/O: wrapper preflight and backend reads
are separate; code/config inventory additionally has a fixed 64 MiB/8192-file
bound per scan. Progress JSON is at most 4 MiB. Backend physical output uses its
unchanged separately bounded three-file publication protocol.

The lifetime check is cooperative before/after a synchronous backend call;
V1 does not provide OS preemption of a slow call. A late return is refused,
leaving its intent/output for inspection rather than claiming timely success.

Only one process exclusively creates a new queue root. The session also has a
nonblocking owner lock and checks root/owner-record physical identity/readback.
Before each backend call it reserves input/attempt budget in memory and
publishes a unique immutable intent. It never refunds a failed reservation.
Outputs use deterministic case+fingerprint names. No existing destination is
overwritten. Queue intent/progress records stage unique bounded JSON, fsync,
read back, atomically rename without replacement, then recheck identity/bytes.
No path-based recursive cleanup is attempted. Interrupted or ambiguous writes
poison the session; retained artifacts require owner inspection. A lost return
within a live session makes its existing intent REVIEW_DUE, never a blind retry.
No mutable latest alias, reset counter or automatically reconstructed completion
ledger is used. Local fsync/readback is not Drive durability or power-loss proof.

```python
from pathlib import Path
from tools.run_research_queue_batch import QueueSession, LIMITS

session = QueueSession(Path("C:/research-input"),
                       Path("C:/research-output/research-queue-explicit-001"),
                       "LOCAL:001", LIMITS)
first = session.run(Path("C:/research-input/queue.json"))
second = session.run(Path("C:/research-input/queue.json"))
```

```text
python -B tools/run_research_queue_batch.py --manifest C:/research-input/queue.json --input-root C:/research-input --output-dir C:/research-output/research-queue-explicit-001 --queue-id LOCAL:001
python -B tests/research_queue_batch_smoke.py -v
python -B -O tests/research_queue_batch_smoke.py -v
```

CLI is one bounded invocation. Exit 0 means every case ran locally or was reused;
exit 2 means refusal or at least one blocked/due case. Neither grants economic
authority. This new focused smoke remains standalone: protected common smoke
registration/fixed inventories/publication pins were not changed in this scope.
Required repository CI and this focused normal/-O suite are separate evidence.

## Actual research inputs and reusable lesson

Source-derived STRL notes and new numerical/macro research receipts may be
retained as raw evidence with exact hashes. They do not automatically satisfy
the backend identities/events/A3/Registry contracts. Do not invent a provider
clock, current price, official A3 packet or missing generation43 component to
make a real case pass. SEC availability quarantine and incomplete Source
generation remain explicit. A fixture PASS cannot promote them.

Reusable lesson: persisted bytes plus self-consistent hashes do not recreate a
lost returned acceptance. Fail closed at process restart, keep failed intents
charged and preserve bounded ambiguous outputs. Fix a future durable capability
handoff explicitly rather than silently teaching a cache to certify itself.
