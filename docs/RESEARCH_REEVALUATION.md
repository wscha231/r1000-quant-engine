# Research updates and reevaluation

This is the shared entry point for the fresh research process requested on
2026-09-10. Start from current master and inspect the exact PR/run evidence.
The user permits a new baseline without reproducing old performance. Old
results become reference evidence; failed attempts and previously inspected
periods remain in the research history. A fresh name never creates fresh OOS.

## Fixed investment question

Start with USD 100,000 and replay 7–8 years through the last completed market
session, using only information available at each decision. Select actual
securities, buy/sell, carry shares and cash, and adjust exposure chronologically.
The primary objective is after-cost USD CAGR, subject to the declared risk
constraints (currently maximum drawdown magnitude 25%). Report final wealth,
CAGR, MDD, Sharpe, Sortino, Calmar, annual/monthly and rolling returns, recovery
duration, benchmark-relative performance, turnover, cash exposure, transaction
costs and market/sector/security/FX attribution. Specify the risk-free series
used for excess-return Sharpe and the tax treatment. Do not select new rules
by repeatedly maximizing full-history CAGR and then call that history OOS.

The continuous fund engine proposal in PR #409 is a separate, unmerged
capability. This PR adds input versioning, reevaluation planning and attempt
records on current master. It does not yet bind those records to verified
fund-result artifacts or implement the complete real-data backtest.

## Three independent input lanes

| Lane | New collection contract | Historical requirement |
|---|---|---|
| Prices, corporate actions, FX and benchmarks | Update by market/security/session, retain raw source bytes and corrections; verify the exact completed close and held-security coverage | Raw tradable prices, split/dividend/merger/delisting events, historical listings and currency conversion; never silently turn missing prices into cash |
| Fundamentals and candidate selection | SEC publication-timed facts, exchange/listing evidence, then recompute features and candidates at each decision | Historical universe including exits, publication timestamps, revision-aware statements, lagged relative strength and estimates only where vintage evidence exists |
| Macro and qualitative research | Retain public publication/vintage time separately from retrieval/recording time; quality claims include sources, counterevidence and invalidation conditions | ALFRED/public release vintages or dated primary evidence. Current FRED graphs and today's qualitative judgment cannot be backdated |

These lanes do not restore an accepted paper-account head. A broken legacy
ledger must not prevent a new research collection. A newly assembled dataset
has its own content hash; the old frozen macro hash is required only when
reproducing that old baseline. A price-only or partial-factor study must be
labeled as such and cannot establish performance of the full proposed system.

## Implemented lifecycle

`tools/research_lifecycle.py` is a standalone Python 3.12 standard-library tool.
Each observation identifies source, kind, entity, field, effective time,
available time, value and evidence class. Each batch also records retrieval
time, the store's actual recording time, public source URI and raw-byte hash.
The recorder's clock is a local audit clock, not a trusted external attestation.
Labeling a row `public_archive` does not authenticate its claimed publication.
Source-specific adapters and replay preflight must still verify that claim.

- Immutable objects are addressed by SHA-256. Month/entity/source partitions
  bound preprocessing updates; prior snapshot contents stay readable.
- SQLite serializes dataset-head changes. A stale expected head or conflicting
  same-time revision fails before publication. Later revisions are retained.
- Repeating unchanged data preserves the snapshot and retains the collection
  receipt. Repeated current values preserve their first observation; a changed
  value followed by a reversal creates two revisions.
- `ARCHIVED_RECONSTRUCTION` applies verified public availability and excludes
  every `current_only` record. `FORWARD_RECORDED` additionally requires an actual
  qualifying local receipt by the decision cutoff. Importing history today
  cannot invent our own past observation. The `as_of` helper is a correctness
  reference; a full-universe replay adapter must build an indexed chronological
  event stream once, not rescan every snapshot on every trading decision.
- Dataset, strategy, code, environment and window identify an evaluation.
  Begin the attempt before execution; retain failures, blocks and unfinished
  attempts. A declared completion plus result hash is not verified performance.
- The history ID must continue the existing canonical experiment population.
  This tool preserves new attempts; migration of all old experiment identities
  and multiple-testing accounting is still required before any promotion.

| Update | Plan |
|---|---|
| No usable input change and no window extension | Verify the prior result and its provenance before reuse |
| New observations / historical correction | Find the earliest availability affected and reuse earlier preprocessing only where valid |
| Longer evaluation window | Process the newly completed sessions in order |
| Strategy, code, costs, universe, calendar, benchmark or evidence-mode change | Rerun the full window; distinguish an environment sensitivity study from a strategy study |

**Fund execution still requires a full chronological replay.** The current
engine cannot resume a certified checkpoint containing all positions, cash,
pending orders and corporate-action rights. The planner therefore never
stitches partial NAV segments. Resume is a later optimization, acceptable only
after resumed and full replays match in positions, orders, costs and NAV.
Paired strategy comparisons must run both rules on the same data, window,
costs, universe and benchmarks; reducing assumed costs is not evidence of alpha.

## Runnable commands

Use a private research directory distinct from accepted paper state. The
observation and request schemas are shown in the module and synthetic tests.
Synthetic tests establish mechanics only, never historical performance.

```bash
python tools/research_lifecycle.py --store /private/research/v1 ingest \
  --batch /private/inputs/batch.json
# On update, --expected-head must be the exact previously inspected snapshot.
python tools/research_lifecycle.py --store /private/research/v1 plan \
  --request /private/requests/new.json --previous /private/requests/previous.json
python tools/research_lifecycle.py --store /private/research/v1 begin \
  --attempt-id fresh-baseline-001 --request /private/requests/new.json
# Run preflight and the separately reviewed replay; record a block if incomplete.
python tools/research_lifecycle.py --store /private/research/v1 finish \
  --attempt-id fresh-baseline-001 --status BLOCKED --reason historical_source_gap
python tools/research_lifecycle.py --store /private/research/v1 attempts
python tools/research_lifecycle.py --store /private/research/v1 backup \
  --destination /private/backups/research-v1-checkpoint-001
```

`backup` takes a consistent SQLite backup, copies and verifies immutable
objects, validates all catalog references and publishes to a new local path.
It will not overwrite an existing checkpoint. Reopen that path with `--store`
to use the checkpoint. Local success does not establish remote persistence.
Before scheduling durable updates, transfer checkpoints to the configured
private research storage, verify remote bytes, restore in a clean location and
confirm identical heads and attempt history. Do not use expiring GitHub
artifacts or Actions caches as the sole research database. Keep raw provider
payloads private and respect the source's redistribution terms.

## Real-source pilot and remaining integration

```bash
python tools/collect_research_macro_versions.py \
  --store /private/research/macro-pilot --start 2018-09-10 --through 2026-09-09 \
  --report /private/reports/macro-pilot.json
```

The collector independently requests DGS2, DGS10 and UNRATE from public FRED
graph CSV. It retains raw bytes and records the current vintage as
`current_only`, then replays the same batch once to verify idempotency. This
second ingestion is not a second provider fetch. Missing values remain missing.
Failures use controlled status labels; successful series survive another
series' failure. Public graph access is neither a provider-entitlement probe
nor proof of complete historical vintages.

The PR workflow `research_data_lifecycle.yml` runs this bounded pilot without
secrets, ledger restoration or trading dependencies. It uploads only aggregate
diagnostics. Its temporary store is intentionally not the durable service;
no recurring schedule is installed. A current-vintage collection, even with
eight years of observation dates, does not make an eight-year PIT backtest ready.

The first real pilot (run `34463287454`, head
`2fa40cb2ce2da369eae3f977e2dc130b6b9b58b2`) failed with HTTP 404 for all three
series because the new collector used an incorrect CSV route. No dataset head
was created. The path was corrected to `/graph/fredgraph.csv`, matching the
existing repository's FRED adapters, with a regression on the requested URL.
That failed run remains part of the implementation evidence; it is not evidence
that the series are unavailable. Inspect the subsequent exact-head pilot for
actual collection success and dates.

Next integration gates:

1. Connect independent historical price/lifecycle/FX, SEC and macro-vintage
   adapters; verify per-period coverage through each market's completed close.
2. Freeze one candidate strategy/configuration before evaluation. Derive
   candidate selection at each historical decision from the eligible universe.
   Missing qualitative history remains an explicitly missing component.
3. Bind each lifecycle attempt to the reviewed fund engine, exact inputs,
   daily accounting and verified result manifest. Never infer CAGR from a
   collection report or a completed job status.
4. Run same-environment comparisons, costs/slippage and regime sensitivity,
   walk-forward validation and the canonical multiple-testing gate. Show
   sample-period reuse honestly and retain rejected candidates.
5. Install recurring collection only after private checkpoint persistence and
   restore are proven. Future genuinely unobserved sessions supply prospective
   evaluation; updates produce challenger proposals, not automatic promotion.

Official source contracts: [SEC APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces),
[FRED vintage parameters](https://fred.stlouisfed.org/docs/api/fred/series_observations.html).
Related work: [fund replay PR #409](https://github.com/wscha231/r1000-quant-engine/pull/409),
[legacy source audit PR #410](https://github.com/wscha231/r1000-quant-engine/pull/410).
