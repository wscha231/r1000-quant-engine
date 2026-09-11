# Macro and technical historical evidence

Entry point for the work requested on 2026-09-11. This is an independent
RESEARCH_ONLY extension of current master `8ccbd478e05ff34c6dd70e410be0cae793c9863e`.
Read the exact PR head and latest pilot artifact before using any result. A
planned capability, a passing synthetic test, and measured provider evidence
are different states. No new portfolio CAGR or selector efficacy is claimed.

## Implemented first stage

- `docs/macro_indicator_registry.json`: 30 FRED series, units, native frequency,
  source/calendar locations, revision review scope and research boundary.
- `tools/macro_history_sources.py`: bounded current graph history or paginated
  ALFRED real-time intervals; immutable raw/normalized objects and collection
  receipts; hash verification; actual monthly gaps; source failures retained.
- Official FRED release-calendar retrieval and a due-work planner distinguish
  backfill, a new release, waiting and an unavailable calendar. A frequency is
  never converted into an invented first-Friday publication date.
- `tools/macro_technical_study.py`: 21 fixed technical hypotheses per index,
  seven future holding horizons, next-session-close entry, actual NYSE sessions,
  missing-path rejection, training-label maturity and expanding walk-forward
  comparison with a training-only historical-mean baseline.
- SMA20/50/100/200 distance and 20-session slope; above-SMA200 state;
  first 50/200 golden/death crossover; first 20/60-session breakout episode;
  momentum and relative strength at 20/60/120/240 sessions. RS is the difference
  between the index's price return and the named reference index's return.
- ALFRED macro changes enter once per new observation-period release, using
  revisions known then to construct the previous-period comparator. Missing
  adjacent months/quarters/weeks do not become ordinary period changes.
- HAC confidence intervals retain the original session grid. The complete
  current-run test family, including unavailable tests, receives the
  Benjamini-Yekutieli correction. Long overlapping labels and clustered rare
  events also require at least 20 nonoverlapping windows; events need 20 fires.
- Machine-readable period-specific effect estimates, uncertainty, event/state
  conditional means, OOS prediction error and direction accuracy versus baseline,
  sample counts, status, code/input/calendar hashes and a previous-report diff.

All results have `eligible_for_selector=false`. This first screening implements
single-feature predictive association. It does not establish causality,
multivariable incremental alpha, a calibrated trading probability, transaction
cost performance or an improved portfolio. A low correlation or negative first
screen does not permanently discard a variable: conditional, nonlinear and
interaction tests need separately registered hypotheses and retained failures.

## Historical truth and source boundaries

| Input | Stored truth | Permitted first-stage use |
|---|---|---|
| FRED current graph macro history | `current_only`; availability is retrieval time | Collection/coverage; blocked from historical release study |
| FRED current graph price indices | `current_only`, study explicitly `FREE_PROXY` | Exploratory technical history, with current corrections disclosed |
| ALFRED real-time intervals | `alfred_date_archive` | Date-level archival reconstruction after the vintage date ends in New York |
| Synthetic tests | Synthetic fixtures | Software invariants only |

ALFRED dates are not exact announcement timestamps or surprise-versus-consensus
data. The conservative next-local-day boundary handles daylight saving and
avoids same-day intraday assumptions. Archived macro inputs do not certify
current-vintage index prices, release latency, a stock universe, delistings,
fundamentals, dividends or investable execution. The combined report therefore
keeps `historical_pit_certified=false`.

SP500 and NASDAQCOM are **price indices**, excluding dividends and expenses.
NASDAQCOM means Nasdaq Composite; NASDAQ100 is separately registered and can
be collected explicitly. SP500's public FRED history is limited to ten years,
so a request beginning in 2000 does not create earlier S&P history. Each index
reports its actual range. Acquire licensed longer-history/total-return data
before making that comparison. Never splice an ETF and index without an
explicit return/availability contract.

WTREGEN and WRESBAL are **weekly averages**, not Wednesday point levels. WALCL
is a balance-sheet level and RRPONTSYD uses billions of dollars while WALCL
uses millions. No unconverted or differently timed "net liquidity" identity
is silently used. NFCI already contains market-related inputs; its future
association cannot by itself identify an independent macro cause.

## Run and reuse

Python 3.12; numpy, pandas, scipy; pandas_market_calendars for the real exchange
calendar. The workflow pins its analysis dependencies. Run directories must be
private research paths separate from accepted paper state. Output paths are
write-once; use a new destination for a new run.

```bash
python tests/macro_technical_evidence_smoke.py
python tools/macro_history_sources.py --store /private/macro-research \
  --start 2000-01-01 --through 2026-09-10 \
  --report /private/reports/collection-001.json
```

The command prints the content-addressed receipt path. Use that exact file:

```bash
python tools/macro_technical_study.py --store /private/macro-research \
  --receipt /private/macro-research/receipts/EXACT_SHA256.json \
  --output /private/reports/evidence-001.json
```

`FRED_API_KEY` is needed only for the official API paths, never the public
pilot. It must be supplied through the approved execution environment; do not
paste its value in chat, source, URLs, logs or reports. Existing encrypted
GitHub secrets are not readable from this chat's process.

```bash
python tools/macro_history_sources.py --store /private/macro-research \
  --mode alfred --series UNRATE,PAYEMS,CPIAUCSL \
  --start 2000-01-01 --through 2026-09-10 \
  --report /private/reports/alfred-001.json
python tools/macro_technical_study.py --store /private/macro-research \
  --receipt /private/macro-research/receipts/PRICE_RECEIPT_SHA256.json \
  --macro-receipt /private/macro-research/receipts/ALFRED_RECEIPT_SHA256.json \
  --output /private/reports/evidence-002.json \
  --previous /private/reports/evidence-001.json
```

Release calendars are refreshed independently of observations. FRED's
date-only calendar yields a conservative end-of-date check, not a claimed
announcement time. A primary-source calendar with explicit timezone-aware
instants can also supply the `events` input.

```bash
python tools/macro_history_sources.py --action calendar \
  --series UNRATE,PAYEMS,CPIAUCSL --start 2026-09-01 --through 2026-12-31 \
  --report /private/reports/calendar-001.json
python tools/macro_history_sources.py --action plan \
  --store /private/macro-research --through 2026-09-10 \
  --previous-receipt /private/macro-research/receipts/EXACT_SHA256.json \
  --release-events /private/reports/calendar-001.json \
  --report /private/reports/update-plan-001.json
```

The due plan requests coverage checks; a retrieval after a release is not proof
that the provider already contains that release. Collection success, release
completeness, durable persistence, reevaluation success and consumer use must
be tracked separately. A changed report is not proof of a structural break.

## Pilot execution and persistence

`.github/workflows/macro_technical_evidence.yml` runs the public 12-series pilot
on relevant same-repository PR changes and supports manual dispatch after
publication. The temporary runner store is not uploaded; only aggregate
collection/evidence/summary JSON is retained for 30 days. The public lane requires no credential. A subsequent isolated step uses only
the existing `FRED_API_KEY` for UNRATE/PAYEMS/CPIAUCSL archival retrieval and
their release calendars. If that key is absent it records an explicit block.
The same-repository guard excludes fork PRs; dependency installation occurs
before the key is supplied. No raw index history, ledger, portfolio target,
Drive credential or broker connection is published.
An incomplete collection remains a failed pilot even if partial reports exist.

The objects/receipts format preserves attempts and raw bytes locally. It is
not a second accepted data platform. PR #411's research lifecycle remains an
unmerged proposal with a more complete version/attempt database. Integration
must map these source/observation/availability/evidence records into that
reviewed database and retain raw hashes. Do not merge or recreate its draft
implementation without reviewing its current status.

Before installing recurring collection: publish a checkpoint to the configured
private research storage, verify remote hashes, restore it into a clean store,
and verify identical receipts and study results. Expiring Actions artifacts
and caches cannot be the sole database. Provider redistribution rights must
be resolved before public sharing of raw data. The default-branch paper-state
Drive contract is separate and untouched.

## Next gates and other-chat handoff

1. Read this document, the exact PR diff/checks and the latest pilot's aggregate
   artifact. Use actual coverage; do not infer success from a workflow's existence.
2. Run the official ALFRED/calendar adapters in an authorized credential-bearing
   environment and authenticate historical availability. Their offline tests
   alone do not prove provider pagination/entitlement or historical coverage.
3. Obtain longer S&P/total-return prices and missing gold/silver, crypto, tax and
   age-distribution adapters. Preserve all starts, gaps and source truth classes.
4. Integrate the reviewed lifecycle and prove private persistence/restore, then
   install per-release collection and revision rechecks. Data refresh, fixed-model
   forecast, matured-label reevaluation and model replacement are distinct jobs.
5. Extend to matched-state/event-study controls, nonlinear conditional effects,
   sector/theme/security panels and cost-aware macro/technical/both ablations.
   Keep monthly macro event counts independent of the number of stocks.
6. Preserve the canonical experiment population and previously inspected
   periods. Repeated historical screening is not fresh OOS. Promotion requires
   the existing separate review and preflight contracts.

## Primary source contracts

- [FRED observations and real-time output types](https://fred.stlouisfed.org/docs/api/fred/series_observations.html)
- [ALFRED real-time periods](https://fred.stlouisfed.org/docs/api/fred/realtime_period.html)
- [Official release-calendar API](https://fred.stlouisfed.org/docs/api/fred/release_dates.html)
- [S&P 500 source, history limit and return basis](https://fred.stlouisfed.org/series/SP500)
- [TGA weekly average](https://fred.stlouisfed.org/series/WTREGEN)
- [Reserve balances weekly average](https://fred.stlouisfed.org/series/WRESBAL)

Local starting evidence: 12 offline regressions passed. This environment's
direct FRED request did not complete because network approval was cancelled;
it is not evidence of a FRED outage. Real provider results and PR/CI evidence
are recorded below after the GitHub pilot runs.


## First real-source result (retained baseline)

[PR #413](https://github.com/wscha231/r1000-quant-engine/pull/413), source
`0281936c95e924901a8fc9738d8eac9ce80c48cd`,
[run 34558079749](https://github.com/wscha231/r1000-quant-engine/actions/runs/34558079749),
job `103134935159`, artifact `10183311335` completed the public pilot.
`docs/macro_evidence_runs/20260911_public_pilot.json` preserves the aggregate
job-log evidence and artifact identity beyond artifact expiry.

- 12/12 sources collected, 31,759 source observation rows.
- S&P 500: 2,513 NYSE observations, 2016-09-12 through 2026-09-10.
- Nasdaq Composite: 6,711 NYSE observations, 2000-01-03 through 2026-09-09.
  The provider returned 6,712 rows; the follow-up adds explicit reporting of
  the source date outside the NYSE calendar and the unfilled latest session.
- 294 declared technical feature/horizon/index comparisons: 218 did not meet
  the combined incremental-prediction/inference criterion; 76 lacked sufficient
  independent evidence. No candidate passed this screen. This does not prove
  zero effect, test nonlinear combinations or establish portfolio performance.
- UNRATE and CPIAUCSL each have an internal missing October 2025 observation.
  The values were not imputed. All ten current-vintage macro inputs remained
  blocked from historical release evaluation.
- Initial 12 tests passed on the runner; the follow-up adds a thirteenth
  official-calendar/date-precision regression and a future-label perturbation.
- The provider artifact exists with verified GitHub metadata, but this
  workspace's download returned HTTP failure; full bytes were not locally
  verified. Subsequent runs emit a bounded derived readpack for direct review.
- Ordinary local git push lacked credentials. The connected Git data API
  published the locally committed/validated tree with exact tree-hash parity;
  the local checkout was then aligned to that published commit.
- A pre-existing invalid `alphaops_replay_sidecars_manual.yml` workflow also
  reports a failed push event on unrelated branches (separate PR #408).
  This is distinct from the successful research pilot and its own source checks.

No thresholds are changed to make this first negative result pass. Historical
sample reuse remains recorded when the archive/combined study is added.


## Archival adapter and calendar proof

[Run 34558604870](https://github.com/wscha231/r1000-quant-engine/actions/runs/34558604870),
head `30072f780edb2110d016e65b6263509f5122f45b`, job `103136489097`,
artifact `10183499791` successfully used the existing FRED key without exposing
it. Official ALFRED collection returned 596 UNRATE, 4,114 PAYEMS and 1,586
CPIAUCSL vintage rows (6,296 total) for the requested 2000-onward periods.
The official calendar returned 13 date-level entries across those three series,
including the shared labor release. Historical macro changes added 42 tests to
the 294 technical tests; correction for the combined study uses all 336 tests.
No combined-study macro candidate passed: 30 had no incremental evidence under
this screen and 12 lacked independent evidence. The first technical screen and
combined screen are distinct families; do not merge their q-values.

The bounded public readpack is retained at
`docs/macro_evidence_runs/20260911_archive_pilot_v1.json`. Its macro output is
superseded by the following correctness fix, not by a tuned threshold. The
Nasdaq source date excluded from the actual NYSE session grid is 2019-04-19;
2026-09-10 remains an unfilled trailing observation for that provider series.

Source review found an interval-boundary issue: if a revision is admitted only
after its date ends, the previous value must expire at that same delayed
boundary. Comparing its raw realtime_end date with the decision date could
prematurely drop a valid first-release sample. A regression perturbs a revision
not available until the next day and requires the still-valid previous value.
The adapter now maps both interval ends consistently and reports missing
ALFRED values as missing rather than a zero missing-value count. Fourteen
local regressions pass; thresholds and the previously inspected sample remain
unchanged. A new source-hash-bound pilot verifies this correction.
