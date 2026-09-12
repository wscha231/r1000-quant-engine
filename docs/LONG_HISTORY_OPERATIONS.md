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

## Execution

`long_history_research.yml` has one global writer lock and no cancel-in-progress.
The initial branch push runs a scoped data-only pilot. After merge, scheduled runs
are configured for 06:37 UTC Tuesday–Saturday (after US Monday–Friday closes).
A workflow_dispatch follows the same restore/compare/append path. It never reruns
paper-account processing. A schedule in an unmerged PR is not active operation.

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
- Fact: original PR413 real remote lifecycle recovered; 44 offline regressions
  (14 source, 16 checkpoint/cycle, 14 new history) pass locally.
- Local environment caveat: pandas_market_calendars is unavailable, so the
  registered integration suite must run in the pinned GitHub runtime.
- Change: scoped source reuse, partitioned long-history ingestion and consumer.
- New expanded real collection, remote result and scheduled liveness: inspect the
  linked current PR/run; code presence is not evidence of completion.
- Stop: source/hash/identity/chain failure; stale datasets cannot feed active signals.
- Decision: no alpha activation, live/paper order, ledger migration or fullrun.
