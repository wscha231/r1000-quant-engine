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
