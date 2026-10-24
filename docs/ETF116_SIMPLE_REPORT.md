# Lightweight ETF research report

User choice on 2026-10-23: rank general equity ETFs only, combining 1/3/5 years,
with returns most important. Preserve the frozen116 universe and equity seed.
This report is a research display, not a target portfolio or accepted EOD state.

## Method

Reuse `run_etf116_offline_research_h1.py` / `compute_horizons` upstream. The new
adapter reads the sealed existing output and does no TR/risk recomputation or
provider calls. Within qualified USD general equity ETFs, average-rank percentile
scores use 1Y CAGR20%, 3Y CAGR20%, 5Y CAGR20%, 3Y dated-RF Sharpe15%, 3Y MDD10%,
3Y volatility5%, annual expense ratio10%. Higher returns/Sharpe and smaller MDD
magnitude/volatility/fees are preferred. Ties have equal component percentiles;
final ties resolve by higher3Y CAGR, lower fee, then ticker. These fixed preferences
are not a demonstrated optimal strategy or expected future return.

Leveraged, inverse, option-overlay, single-stock, fund-of-funds, non-equity and
non-USD products are excluded. All116 require explicit dated classifications,
including excluded funds; missing metadata cannot silently shrink the cohort.
Missing1/3/5Y windows or dated RF excludes a fund with a reason, never a zero.
Fewer than five qualified funds refuses the report. Comparable basis and window
anchors are required. Report coverage means qualified inputs, not the whole ETF
market, licensed source admission or proven performance improvement.

Expenses are already reflected in fund TR. The fee component is a declared
preference and is never subtracted from returns again. Fees/classifications may
be reused up to45 calendar days; source clocks/hashes remain visible. Each selected
ETF requires ten distinct stock/class records, source rank1..10, one dated issuer
snapshot and publication clock, at most10 calendar days old. Holdings weight is
percentage points, expense/return/volatility decimal fractions. Cash/non-stock
positions must be excluded by the producer before ranking stock holdings. GOOG
and GOOGL stay distinct. Overlap is fund membership counts, not inferred portfolio
allocation. Missing/stale holdings blocks export; no invented current holdings.

## Input and output

`etf116-simple-report-input-v1` contains `decision_at`, `metrics_candidate`,
`fund_metadata` keyed by all116 tickers and `holdings` keyed by selected ETF.
Metadata fields: `asset_class`, boolean `leveraged`, `inverse`, `option_overlay`,
`single_stock`, `fund_of_funds`, `currency`, `fund_name`, decimal `expense_ratio`.
Metadata and holdings each carry `asof`, aware `published_at`, plain HTTPS
`source_url` without credential/query/fragment and immutable `source_sha256`.
Holdings additionally carry `rank`, `symbol`, `company_name`, `asset_class=EQUITY`,
`weight_pct`. References are producer declarations, not source authentication.
The CLI requires the exact bytes SHA256; source artifact/run identity is retained
in Actions. Future/stale decisions refuse against one trusted UTC clock.

```text
python tools/etf116_simple_report.py --input report-input.json \
  --input-sha256 EXACT_BYTES_SHA256 --output-dir UNIQUE_REPORT_ROOT
```

The small public Actions dependency `openpyxl==3.1.5` writes values-only XLSX;
the desktop artifact authoring runtime is not a deployable GitHub dependency.
Workbook tabs: `ETF TOP5`, `TOP10 HOLDINGS` (50 rows), `OVERLAP` (deduplicated
security/class). Output includes source/as-of, basis, coverage, method and hashes.
Names beginning with spreadsheet operators are literal strings, never formulas.
`report.json` and XLSX are content-addressed locally, with a final physical-hash
receipt. Deterministic XLSX bytes bind source decision time, not run time. Reuse
compares both files to a freshly rendered small display, preventing a rehashed
sidecar from certifying changed numbers; TR/risk is never recalculated. Conflicts refuse.
No existing successful file is overwritten. An incomplete output directory is
not success. There is no remote publication retry or cleanup in this module.

The already existing `free_data_daily_update.yml` gains a manual report-only mode
that skips its collection job, downloads a named artifact from one completed
successful same-repository run and checks the exact JSON bytes. It installs only
the small workbook dependency and produces an Actions artifact. The existing
cron is unchanged. The prior automatic ETF job remains literally disabled.
No new scheduler, fullrun, provider/holdings collector, source budget, portfolio,
target, paper ledger, broker, order or promotion path is added.

## Current execution limits

This implementation does not create an approved daily TR/issuer metadata/holdings
producer. Fixture outputs prove only native behavior. Existing H1 fields remain
`allowed_for_sheet_publisher=false`, source admission false and economic authority
false. This separately requested file display does not change those authorities.
Actual source rights/distribution/split QA, comparable series identity and RF/SPY,
and a real input/run binding must be established before a numerical report is
uploaded to Drive. No real ranking or automated Drive refresh has run here.

Drive automation requires a separately validated file publication path with exact
readback and an explicit unknown-write recovery contract; an Actions workbook is
not evidence of Drive success. User approval already exists; missing verifiable
inputs/binding, rather than another generic permission, is the remaining issue.
Old accepted-anchor/two-real-session/rotation gates remain required for the full
accepted daily service. A lightweight research file is never counted as accepted
ETF EOD, actual completed session, trading policy or activation of that service.

The current-master reconstruction retains the previously reviewed H1/H2/H3
capabilities from PR646 f889ddba, including exact probe blob626041f5 and the typed
POST outcome correction. Only the three causal existing workflow/test patches
were strictly applied to current master71111d1b; unrelated SEC work10f62fb3 stays
on its own preserved branch. Existing PR646 is reused and remains Draft.

## Independent completion and later V7.1 connection (2026-10-24)

The human requested parallel ETF completion while V7.1 integration continues.
The independent research product is verified ETF inputs -> existing H1 metrics ->
small workbook -> private Drive file. It does not need the V7.1 portfolio/ER/paper
runtime. Later consumers read the same immutable JSON and physical-hash receipt.
No accepted portfolio session or target/order permission follows from ranking.

PR646's old head2fa03544/base71111d1b CI235/235 and A6 are historical after a
new change. This continuation re-queries master and rebases the same existing
PR. Borrow Main only after a clean/released handoff and restore it on release;
remote/read-only work may proceed in parallel, never two local Main writers.
No new checkout, PR, collector, schedule or common workflow edit is needed.

| Remaining work | Required evidence | V7.1 dependence |
|---|---|---|
| Comparable1/3/5Y daily TR | Actual manifest, rights/retention, dividend/split QA, identity and clocks | Reuse a future admitted Reader generation; no duplicate collector |
| Dated RF and matched-basis SPY | Same-period source and availability; no NAV/market splice | Shared immutable data, not portfolio runtime |
| Classification/fees for frozen116 | All exclusions explicit, dated issuer records <=45days | None |
| Selected top5 holdings | Ten stock/classes each, one issuer snapshot <=10days, hash/publication clock | None; intake after selection |
| Private file publication | Bound runner/code/parent/file, exact immutable readback, unknown-write GET-only recovery | Existing Drive owner transport; no Sheets mutation dependency |
| Bounded recurring operation | Existing trigger/gate, rights/budget, deduplication, visible stale/blocked state | Reuse shared session gate when integrated; no new scheduler |
| Later consumer | Exact JSON/receipt hashes, schema/method/basis/clocks and capability checks | Additive read adapter; no recomputation/writer in V7.1 |

Prior verified boundaries remain dailyTR0/116, anchor unconnected, accepted real
ETF sessions0/2, automation disabled. Update only from actual source/runtime
receipts. An OHLCV inventory is not dailyTR. The full accepted H3 service still
needs anchor binding, two real completed sessions and long rotation/capacity;
those do not prove this lightweight file has been published.

### Minimize transfers first

- Reuse verified history. After bootstrap, append new completed sessions only.
  Corporate-action corrections or changed method/identity invalidate affected
  windows; older adjusted values can change. This is a future producer contract,
  not a second incremental TR calculator implemented here.
- Reuse sealed H1 results; this adapter recalculates no TR/risk. It consumes
  only1/3/5Y returns and3Y risk. Preserve all other H1 consumers' defaults.
- Select using the complete classified cohort, then check only selected funds'
  top10 caches. Refresh missing/invalid/stale snapshots or existing-cadence due
  snapshots. Reuse fees/classifications until freshness expiry or source change.
- Drive receives the small XLSX plus JSON/receipt, not repeated price history.
  Retain raw/normalized data in the existing approved store.

Conditional counts, not measured production savings:116 -> at most5 holdings
fund targets is95.69% fewer targets. Fresh caches can reduce that to0; this is
not an HTTP/page bound. With116 eligible series and1,260 retained sessions,
146,160 repeated rows ->116 new-session rows is99.92% fewer transferred rows,
excluding bootstrap, corrections, gaps, provider page minima and SPY. No elapsed
time, credit or real data-coverage improvement is inferred. At this scale,
arithmetic should be profiled before adding incremental MDD structures or a
second engine. Full repository CI cost is development validation, not daily
report generation cost.

### Implemented two-stage read plan

`plan_inputs` and `build` share one cohort/selection function. Planning requires
sealed metrics and all116 dated classifications; holdings can be absent/partial.
It returns selected tickers, valid cache hashes and GET-only fetch reasons.
`funds_requiring_holdings` counts funds, not calls. Planning performs zero network
calls, renders no workbook, dispatches nothing and grants no publication rights.

```text
python tools/etf116_simple_report.py --input report-input.json \
  --input-sha256 EXACT_BYTES_SHA256 --plan-only
```

The existing cadence owner may add `--refresh-holdings` when due. After permitted
GET-only intake, rehash the new input and use existing `--output-dir` export.
Export revalidates original inputs. `report_input_ready` is only local shape/
freshness readiness, not source authentication or Drive success.

The later interface is existing `etf116-simple-report-v1` JSON + physical-hash
receipt: session/decision, input/metrics/report hashes, method/basis, coverage and
three display datasets. The consumer preserves all research/authority flags.
No mutable latest alias, target weight, broker or paper authority is inferred.

### Provider research boundary

[Official Alpaca bars API](https://docs.alpaca.markets/us/reference/stockbars)
supports multiple symbols, explicit adjustments and pagination. It defaults to
raw; the point limit is across symbols and a page can contain only one symbol.
The connected bars tool exposes neither adjustment nor page_token. Its output
cannot be relabeled complete dailyTR. A future approved producer must preserve
adjustment/feed/entity/pages, rights/retention and dividend/split methodology.
Connection alone grants no new116-name Source budget. No provider collection
was executed for this continuation. The Financial Datasets index-fund tool
declares SEC-filing/as-of holdings, not guaranteed fresh issuer-daily data or
publication evidence. Firecrawl was unavailable due to insufficient credits;
the official Alpaca page was read through the web fallback.
