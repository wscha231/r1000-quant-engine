# Mission v3: exact cache and bounded parallel compute

Status: RESEARCH_ONLY implementation candidate. Dependency: PR #460 at
`7310ce5d545d30cb9be3d57ee95c370d7356de7d`, itself based on master
`90b55fe92f25236c663a71cad7ab9138da497919`. This additive PR does not duplicate
or modify the M0 metric implementation, the news collector/cache in #459,
market APIs, strategies, accepted books, or daily schedules.

## Scope and actual connection

`compute_m0.precheck` calls the existing `mission_metrics.assess_pair` directly.
The generic runtime schedules registered pure Python operators with declared
input bytes, named predecessor dependencies, parameters and decision context.
This is an execution mechanism, NOT an 8-year backtester or a new alpha engine.
Each M0 input remains a WHOLE account/pair history; years of a single account
are not computed from fresh capital and concatenated.

Paths:
- `research_only/mission_v3/compute_runtime.py`: exact-cache DAG and profiling.
- `research_only/mission_v3/compute_m0.py`: fixed M0 consumer and bounded CLI.
- `tests/compute_runtime_test.py`: 38 unique regression methods.
- `tests/compute_benchmark.py`: synthetic benchmark using actual M0 code.
- `.github/workflows/mission_v3_compute_checks.yml`: read-only, no-secret,
  no-schedule Python 3.11/3.13 tests. It explicitly checks out and counts tests.

## Cache identity and invalidation

The key binds actual input byte hashes; task parameters; upstream keys AND
output hashes; aware cutoff and full universe identity; exact operator source,
registered transitive source files and the runtime source; Python/platform and
optimization mode. Worker count, task completion order and unrelated docs are
not mathematical inputs. Duplicate equivalent tasks can reuse the same key.
Source changes are checked in coordinator and worker before/after execution.
Source dependencies are declared by reviewed registrations, not automatically
proven by arbitrary Python dependency inference. Random seeds, fitted model,
training cutoff and third-party environment identity must be bound by a future
operator that uses them. A pure callback reading undeclared globals, credentials,
time, files or network is outside this contract and must NOT be registered.

Only an exact key is looked up. No approximate cache or restore-key fallback.
Output bytes and spec are verified on reuse. Same key/different output is a
conflict, not permission to overwrite. Corruption blocks the run. Failures are
not cached as successful outputs. Reusing an older success cannot hide a newer
failed prerequisite. Semantic output hashes exclude timing/PID/cache-hit telemetry.

## Atomicity, parallelism and bounds

One trusted local coordinator owns a private SQLite cache with transactional
per-task insert; process workers never write it. Whole-account transactions and
accepted Drive pointers are not cache jobs. It is not a distributed lock or a
hostile-code sandbox. No untrusted pickle or code is read from the cache; process
serialization contains trusted registered functions and admitted input bytes only.
Private local cache data must not be copied into a public Actions cache. Hashes
can detect damage but a local malicious writer can rewrite bytes and hashes;
independent restoration authentication belongs to M0-B, not this cache.

1-4 spawn workers compute independent ready tasks. A lone task executes in the
coordinator to avoid process startup. Dependency chains preserve order. Completion
order cannot change reducer input order. Each successful task is a restart point;
cooperative interruption reuses committed tasks, and an uncommitted SQLite write
rolls back. Hard-killed, unfinished tasks must recompute. Stateful mid-account
checkpoints, exchange-calendar correctness, external rate budgets and distributed
Drive publication remain separate work.

Limits: 4096 DAG tasks, 16 MiB input/output object, 128 MiB admitted plan input
and accumulated output budget, 128 CLI bundles, 4 workers. This first implementation
keeps bounded inputs/outputs in memory and serializes payloads to workers. It is
NOT yet a Parquet/Arrow zero-copy large-data executor. It intentionally refuses
oversized work rather than swapping or quietly dropping securities.

## Sharding is not stock selection

`shard_ids` uses stable SHA256 over exact IDs, default demonstration is 8 shards.
`join_shards` requires the entire expected unique ID set, rejects extra/missing/
duplicate members, and sorts globally. No per-shard percentile is treated as a
global rank. The tests' 1118 IDs are synthetic, not a fresh market-universe audit.
A real full-universe feature producer must be separately registered and validated.

## CLI, research output only

A plan lists exactly `schema_version`, `universe_ids`, `decision_cutoff`, `entries`
and `report_title`. Each entry specifies `id`, safe relative `path`, `sha256`.
Supply the plan SHA separately; actual plan/bundle bytes are checked before use.
The CLI accepts only the built-in M0 operations; no shell or arbitrary function
name can be supplied in JSON.

```
python -m research_only.mission_v3.compute_m0 plan.json \
  --plan-sha256 EXTERNALLY_PINNED_SHA256 \
  --cache-dir PRIVATE_LOCAL_CACHE --run-dir NEW_RESEARCH_RUN --workers 4
```

Each run directory must be new. An incomplete run gets an execution receipt, not
a success report. No accepted/latest pointer is advanced. Complete execution is
still `mission_status=NOT_PROVEN`; orders and promotion stay false. Authenticated
calendar, PIT, costs, real fills and financial accounting are not established.

## Validation and measurement interpretation

The first 32-test run had 31 passes/1 CLI-spawn failure: `-m` created `__main__`
callables whose identities changed in child processes. Registering canonical
imported module functions fixed it. Do not hide the first failure. Five further
boundary methods plus a cumulative-output budget case bring the final added
count to 38. Cold and warm cache paths enforce the same output memory budget. Repeat Python/-O runs are
not additional independent tests; parent #460's 47 methods remain separate.

Synthetic benchmarking measures the actual M0 function on 32 distinct paired
NAV bundles with 2088 supplied weekdays (not an authenticated exchange calendar).
It compares cold 1/2/4 workers, warm reuse, one changed bundle, a report-only edit,
and interrupted/resumed runs against fresh runs. Results and raw timing receipts
are stored outside source. Do not extrapolate this timing to market downloads,
whole-universe scoring, an 8-year strategy run, or long-term returns. Small
process jobs may be slower than serial; default stays one worker.

## Next integrations, not completed here

1. Review #460 and this exact change; keep separate from portfolio/alpha changes.
2. Use M0-B authenticated packs as inputs after its independent validation.
3. Register pure issuer/security feature producers with actual dependency hashes;
   reconcile full universe and then run global reducers. Reuse #459's existing
   raw-news capture/resume, do not add a competing network collector.
4. Register a whole-account M1 replay task; stateful chunks require explicit
   predecessor state, cash/positions/actions and exactly-once account tests.
5. Only after profiling, decide whether local 2/4 processes, job matrix shards,
   or a dedicated runner improve wall time within memory/cost limits.

## Shared operational lesson

Parallel execution is not automatically faster. First remove repeated parsing
and evaluation. A completed shard cannot certify global coverage. A cache hit
cannot certify data correctness. CI must both include and count the new tests;
#460's prior sparse checkout did not include this new test file.
