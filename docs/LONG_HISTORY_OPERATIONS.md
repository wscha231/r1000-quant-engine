# Long financial and macro history — operations

Tracking: #419. Scope: US-listed securities including ADRs; international macro
series describe their economic exposures, not an authorization to buy non-US stocks.
Current implementation is RESEARCH_ONLY. No targets, accounts, orders or model
promotion are changed. Full portfolio backtest has not run.

## Verified prior work

PR #413 source b6897123b9dfcde5d102cbc1b31800f50b3cc39c was rerun after the
user replaced Google OAuth credentials. Run 34644613851 attempt 2, job
103515382907 succeeded on 2026-09-12 at 07:04 UTC. It verified real Drive
publication, clean restore, reproduction of 336 comparisons, and a subsequent
complete collect/evaluate/store cycle. The final macro checkpoint was
81c81a347929d362f2426a26726d3f53680b9194acce85f7e4676386c6961a39;
manifest a29c5ae1c10202f4817a0faa0bffa058614450f5092d391635ffb767ea9b3368.
Artifact 10294141317, ZIP SHA256
6b089b2e81ef55504219f95964189d0783b35f66e149361eb47ddc1011c7b7a7.
This proves that small existing macro lifecycle, not the new expanded archive.

## Data contracts

| Data | Request | Preservation / interpretation |
|---|---|---|
| SEC companyfacts | Every mapped issuer in the existing 1,118-security cohort, period ends from 2016-01-01 | Original JSON, all available concepts in us-gaap/ifrs-full/dei, units, start/end, fiscal labels, filing dates, accessions and amendments. No latest-filing deduplication across versions. |
| FRED | All 30 registered series, from 1996-01-01 | Current/revised history; actual first and last nonmissing observation retained. Not historical release evidence. |
| ALFRED | 12 registered macro series, from 1996-01-01 | Every returned vintage interval, including withdrawals. Date-level availability after that New York date ends; not an intraday timestamp. |
| World Bank | US, China, Japan, Korea, euro area; annual GDP growth, inflation, population and age-65+ share | 20 country/indicator combinations, from 1996. Current vintage and annual frequency remain explicit. |
| Existing index study | Same 12 current inputs + 3 ALFRED series used by #413 | Recomputed from verified Drive bytes; original 336-comparison family, 1/5/10/21/63/126/252 sessions. Report-only, zero selector weight. |

SEC structured facts are not a complete copy of all financial statement notes,
segments, custom dimensions, historical estimates or filings. Presence in ten
calendar years does not prove forty complete quarters or three complete statements.
Quarterly flows and year-to-date flows must not be summed blindly. Currency and
ADR share units are preserved, not silently converted. Missing statements and
unmapped securities remain reported.

The initial cohort is the existing whole-universe result from run 34541821739,
artifact `us-research-results-34541821739-1`, source file SHA256
4e1eb090f8137395603228dbc55c35907307ad6d049ec778f2722d1cbb87f4b4.
It is a current 1,118-security research cohort, not every US listing and not a
historical Russell membership archive. Its original bytes are archived on the
first successful run; subsequent runs restore it from Drive, avoiding dependency
on expired Actions artifacts. Updating universe membership requires a new pinned
cohort version; the workflow does not silently replace it with a watchlist.

Provider references:
- https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- https://fred.stlouisfed.org/docs/api/fred/series_observations.html
- https://datahelpdesk.worldbank.org/knowledgebase/articles/898581-api-basic-call-structures

## Durable structure and recovery

Existing configured Drive base:
`r1000_top30_institutional/research/macro_technical_evidence/v1/scheduled/long-history-v1/`.
A configured root-folder ID omits the base folder name, following the existing
validated transport. This subtree is independent of PR413's small macro checkpoint,
paper_archive and accepted ledgers. Sharing permissions are preserved.

- `packs/<sha256>`: bounded immutable ZIP packs of gzip-compressed raw and
  normalized JSONL objects. Batch packing reduces Drive requests.
- `catalogs/<sha256>`: dataset coverage, retrieval metadata, source object/pack
  mapping, config hash, source commit, source status and missing reasons.
- `commits/<sha256>`: append-only parent/catalog chain. Forks, stale writers,
  corrupt catalogs or missing dependencies fail closed.
- `reports/<sha256>`: immutable quality, period-effect and engine-context JSON.
- `executions/<sha256>`: binds reports and actual consumer result to a catalog.

The current catalog references prior versions plus changes. Old catalog/pack
objects are never deleted or overwritten. Only new object bytes are uploaded;
SEC conditional GET is used where the provider supplies validators. Macro history
is re-polled to catch revisions, with content deduplication on storage. This is
incremental storage, not a claim that every provider offers incremental APIs.
SEC validators are reused only for the same extraction-code fingerprint and date
window. A parser/form/coverage change forces re-extraction. Current issuer metrics
use only the current CIK mapping. A prior official mapping may retain
historical collection identity with `lifecycle_review_required=true`, but it never
proves current eligibility. New catalogs name and hash the cohort and SEC mapping
source objects by role. The verified mapping source list persists across cycles;
the first migration checks prior catalogs in the hash-verified chain. Missing or
invalid persisted mapping objects stop collection before a replacement catalog
can be published. A current
CIK that differs from a prior CIK collects both issuer archives, records the
older one as history-retained, and requires lifecycle review. Multiple distinct
prior CIKs are retained for evidence even if the ticker later disappears from
the current mapping or the current mapping has multiple CIKs. Those cases
record an explicit ambiguous identity blocker;
none certify the ticker's historical identity. A legacy
positional mapping is admitted only for exact reviewed producer SHAs after both
source roles pass content validation. Workflow cohort restore uses the same reader.
FRED missing observations retain both counts and dates, including omitted `.` rows.

Every new pack is downloaded and hashed before catalog publication. The consumer
then starts with an empty local cache and reads the published catalog. It builds a
reproducible SQLite macro cache and reruns the existing study. Local cache loss is
recoverable. Access to a prior catalog is possible by its immutable hash. Pack
hashes are checked whenever consumed. Provider authenticity and permanent Drive
retention are not guaranteed by hashes.

A failed source is `BLOCKED` or `STALE_RETAINED`; the latter retains its prior bytes
but the standard consumer refuses it. A partial catalog may persist valid collected
sources to avoid losing them, but the workflow exits nonzero and diagnostics remain
PARTIAL. A committed catalog without an execution receipt proves storage only,
not completed analysis. Never label it a successful full data/analysis cycle.
If Companyfacts returns 404 for a verified CIK, the collector checks the same
official SEC submissions identity. Verified submissions bytes are archived as
`COVERAGE_GAP` with issuer-filing or entity-role classification, never as zero
facts. `PARTIAL_COVERAGE` also exits nonzero; neither gap nor history-retained
identity can make selector or historical-PIT evidence green.
Internal rolling-price recovery may read hash-verified normalized bytes from
`STALE_RETAINED`, but ordinary consumers still reject that state. A successful
provider response is required before the reconstructed dataset is `COLLECTED`.

## Execution

`long_history_research.yml` applies `durable-long-history-single-writer` only to
the producer job, with `cancel-in-progress: false`. There is no workflow-level
concurrency group: a skipped code push never joins the producer's pending queue.
The initial pilot used a temporary feature-branch trigger. The final workflow
runs with secrets only on master through schedule or workflow_dispatch. A
code push does not start provider collection or access Drive. Scheduled runs
are configured for 06:37 UTC Tuesday–Saturday (after US Monday–Friday closes).
A workflow_dispatch follows the same restore/compare/append path. It never reruns
paper-account processing. A schedule in an unmerged PR is not active operation.

The public history card queries the latest 30 schedule runs and latest 30 manual
runs separately, excludes explicit skipped conclusions, then uses the existing
trusted repository/master/workflow selector. Code pushes, including successful
workflows with a skipped producer, are not collection evidence and cannot crowd
out the first page of real producers. The latest actual failure, cancellation or
queued/running producer remains visible rather than falling back to old success.
A Pages refresh after a skipped workflow can still occur; it does not supply new
history evidence or authorize collection. A workflow success remains
`WORKFLOW_SUCCESS_DATA_UNVERIFIED`, never verified Drive/data completion.

Exact runtime dependencies and rclone binary checksum are pinned in the workflow.
Credentials exist only in temporary configuration, never source/pack/reports; the
config is removed even on failure. FRED uses its existing GitHub Secret. No new
paid provider is introduced. Resource cost and actual bytes are reported by runs.

Local API: `Lake(transport, workspace)`, `get_records(dataset_key)`,
`materialize(lake, sqlite_path, dataset_keys, cutoff)`. The SQL cache stores vintage
rows, not a magically PIT-safe feature panel. A historical cutoff against current
revised macro inputs is rejected. SEC filed-date filters remain uncertified PIT.
Engine consumers must pin catalog + execution hashes, read quality/freshness and
honor `eligible_for_selector=false` / zero weights.

## Remaining research scope

This data foundation does not complete conditional/nonlinear macro causality,
sector/company exposure models, total-return 30-year equity history, tax/Treasury
flow decomposition, exact release-time archives, surprise-vs-consensus histories,
forecast calibration at 6/12 months, or historical universe/lifecycle recovery.
These require distinct evidence and experiments. A frozen initial universe must
be refreshed under a versioned cohort contract to admit future listings.

[PROJECT_HANDOFF]
- Basis: 2026-09-12; master e89e87e722c67b32e56c2dd86969502c8e952676.
- Fact: original PR413 real remote lifecycle recovered; 56 offline regressions
  (14 source, 16 checkpoint/cycle, 26 new history) pass locally.
- Local environment caveat: pandas_market_calendars is unavailable, so the
  registered integration suite must run in the pinned GitHub runtime.
- Change: scoped source reuse, partitioned long-history ingestion and consumer.
- New expanded real collection, remote result and scheduled liveness: inspect the
  linked current PR/run; code presence is not evidence of completion.
- Stop: source/hash/identity/chain failure; stale datasets cannot feed active signals.
- Decision: no alpha activation, live/paper order, ledger migration or fullrun.

Initial expanded catalog: `5e9d7db95c9fcf01e508d5d0f8179e498dd306c9f09de87842553fd9285a6722`,
commit `fc6d4b070b4f813a4b1fd03c55cdb556da06d15b7fd11249284eb8b0885e6415`.
Directly downloaded catalog SHA256 matches. Run34680321989 archived27 packs,
503,129,850bytes,15,173,078financial fact rows from1,104successful issuers;
962have observations in at least10calendar years. HOLX lacks a current CIK match;
CIKs1103838and1569650returned404; ALFRED/NFCI was blocked with a generic error.
This is PARTIAL coverage, not a complete10-year three-statement panel.30current
FRED series,11ALFRED archives and20World Bank combinations were collected.
SP500 begins2016-09-12; BAMLH0A0HYM2 begins2023-09-12 despite the1996request.
Storage commit is established; inspect execution receipts for consumer completion.
Transient FRED transport/429/5xx failures now retry at most3times; contract failures
do not retry. Fixed HTTP/transport codes never include credential-bearing URLs.

### Fixed transport error visibility (2026-10-30)

History error sanitization preserves the existing
`research_transport_failed:<verb>:exit_<status>:<category>` formatter output only
after strict validation against the formatter's shared verb/category definitions,
canonical signed/unsigned32-bit process status and the existing90-character bound.
Arbitrary colon-bearing messages, prefix/suffix lookalikes, paths, headers and
unbounded text still become `SOURCE_OR_CONTRACT_ERROR`. Existing HTTPError,
TimeoutError/OSError handling and the legacy alphanumeric contract-code fallback
are unchanged; that legacy fallback is not a general secret detector.

This corrects diagnostic category loss, not transport execution or recovery.
Classification precedence, calls, retry/backoff, timeouts and hash/readback checks
are unchanged. Run40883804681's earlier successful dependency restore and its
later separate-process restore failure are distinct observations. A later
generic failure does not prove permanent deletion/corruption, quota exhaustion
or the actual transport category. No new remote read or retry is authorized here.

## Proposed restore integrity hardening — 2026-09-12

Prepared as an offline review patch against PR420 cdc7be2ea5d4120d7c2c231d1b938560ebe1622c.
This note does not establish repository publication or a new successful Drive run.

Restore validates remote pack bytes and referenced member hashes for the union
of locations in every catalog in the chain. A valid tip cannot conceal loss of
superseded data. Each unique pack is read once per restore call; local disk and
memory caches do not substitute for a remote check. Publication repeats restore
checks, so a 304 response cannot authorize reuse after remote data disappears.

Push path filters cover all source, registry and test files in this workflow's
sparse checkout. The default-branch and global single-writer restrictions remain.

Cost: this conservative patch verifies the whole retained pack inventory on each
restore. The existing workflow has six restore calls per unchanged-data cycle
(cohort restore, collector construction, three publication checks and clean
consumer construction). At the measured 503,129,850-byte inventory that is about
3.02 GB of pack reads, before consumer reads and any new pack readbacks. This is
a calculation, not an observed network benchmark. Real runtime/bytes must be
measured before treating the scheduled design as sustainable. Do not optimize
this by allowing a warm local cache to conceal deleted or corrupt remote packs.

### Fresh verified pack batches — 2026-11-01

Pack dependency restores use fresh, disposable staging for at most four named
SHA256 packs per copy, with an 80 MiB transfer ceiling. The existing rclone
copy/files-from-raw/immutable/checksum path uses transfers=1, checkers=1 and the
unchanged TPS=2, timeout, retry and fixed error grammar. A fresh remote inventory
must contain every referenced pack before copying. The stage must contain exactly
the requested regular, nonempty files, each at most 20 MiB; pack SHA256, ZIP member
inventory, referenced-member CRC and member hashes still pass before acceptance.
Missing, extra, partial, symlink, oversized or corrupt results fail closed. A
failed copy never falls back to a cache or a second transfer path.

All six restore boundaries remain independent, including publication rechecks
and the clean consumer. Staging is removed on success, failure and cancellation;
cleanup errors cannot replace the original cancellation. No dependency batch
seeds the consumer cache. get_bytes/get_records/verified_execution, retained
generation chains, SEC extraction identity, the scheduler and 120-minute workflow
limit are unchanged. Custom transports without the batch capability retain the
existing sequential verification path.

PACK_BATCH_READ phase observations distinguish the full reserved ceiling, actual
Python subprocess attempts and local staged bytes, including partial failure.
Staged bytes are a bounded lower bound if inspection is incomplete; they are
neither socket transfer nor billable Drive requests. Backend request and wire-byte
costs remain unknown, rclone internal retries are not new Python attempts, and
failure never makes an attempted transfer free or refunds a campaign budget.
This changes process grouping, not the bytes that integrity verification requires.
Offline regressions are not evidence of measured speedup, reduced network bytes,
a completed history execution, or a guarantee that a real run fits 120 minutes.


## Prepared phase diagnostics — 2026-10-29 (not deployed)

This separate H1 proposal adds LONG_HISTORY_PHASE progress around the existing
restore, per-object hash read, publication checkpoints and post-publication
consumer/study/report/execution steps. BEGIN/END share a process-local phase ID;
ERROR records an interrupted operation without copying exception text. A final
BEGIN with no terminal record means outcome unknown, never completed. Monotonic
elapsed milliseconds and allowlisted nonnegative integer counts are observations;
application_bytes counts returned/written application bodies, not measured socket
transfer, Drive billable requests, or a numeric execution budget.

Only fixed stage names, counts and syntactically verified commit/catalog hashes
are emitted. Paths, object IDs, provider URLs, credentials and exception bodies
are excluded. Existing PACK_VERIFIED and final LONG_HISTORY_SUMMARY remain.
Progress never substitutes for hash verification, a durable execution receipt,
matching generation, consumer readback, quality or Source/PIT admission.

The three observed history jobs reached the unchanged 120-minute limit. g29's
commit creation clock was 183.599 seconds before its origin job cancellation;
that is not measured remote-write/ACK completion. The precise slow inner call
is unproven. This patch does not reduce the six restores, skip any remote check,
increase timeout, retry a job, collect data, or recover/publish a receipt.
Retain BEGIN/END/error evidence in existing Actions logs and the existing always
diagnostic upload route; no new accepted ledger or scheduler is introduced.
Actual exact-g29 recovery remains a separate bounded, independently reviewed
execution contract with distinct recovery provenance and original failure kept.


V1 prospective QA found that logger BEGIN/END failure could stop the original
operation and ERROR logger ValueError could replace its original exception.
Preserve V1 and its actual counterexample receipts. V2 disables progress for
that phase after an exact ordinary diagnostic build/serialization/output error;
no missing END is interpreted as success. Progress is never an authorization
gate. BaseException cancellation, TimeoutError/InterruptedError and custom
subclasses such as the existing Refused deadline propagate unchanged. Unknown
non-allowlisted logger failures also propagate; no generic deadline suppression
or continuation past cancellation is introduced. Existing operation/hash/receipt
logic and every actual read/write remain unchanged. The synthetic commit-END
broken-pipe counterexample now completes original post-commit verification.
Actual POSIX signal delivery and product CI remain future deployment checks.

For the fixed g29 chain, Root's 2026-10-29 metadata-only inventory declares
57 packs /4,246 members and864,629,649 logical pack bytes. Six identical full
restores project5,187,777,894 pack bytes. This replaces neither the dated
503MB observation above nor a measured current network cost. Pack content/CRC
was not read by that inventory; exact consumer/runtime and failed-retry cost
remain separate evidence. Inventory SHA256:
`b7410ead0691c3bbc99686e5811298e051780a6ecc4f311e152094259ca8a635`.
The product regression includes real POSIX timer delivery from inside a fake
log sink; current-head Linux CI must execute it. Native Windows retains an
explicit platform skip and never certifies that POSIX execution itself.

The main study boundary separately rethrows the existing Refused cancellation
class and TimeoutError/InterruptedError before its ordinary partial-study error
handler. Helper-only cancellation proof does not cover a surrounding handler
that catches those base classes. main-level probes verify that cancellation at
STUDY or LOCAL_STUDY_REPORTS stops before report/execution publication, while
ordinary study failures retain their prior partial-receipt behavior. Actual
POSIX timers in both phase sinks are a distinct Linux regression requirement.
This is an explicit cancellation behavior correction; ordinary collection,
hash/restore, successful publication and non-cancellation partial-study I/O
remain unchanged. The already-declared sparse checkout contains the existing
Refused module and its dependencies; no new collector or dependency is added.
