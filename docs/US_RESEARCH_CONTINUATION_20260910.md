# US research continuation

The user requested all-candidate short, medium and long relative strength and
a USD100,000 chronological stock fund from 2019-06-03 through 2026-09-09.
The mandate is US-listed equities, including foreign issuers, plus USD cash.

## Implemented connection

- Analyze every current source candidate over 5, 10, 20, 60, 120, 240 and 504
  trading sessions against SPY on identical dates. Keep missing/IPO windows
  missing. Report relative return, market percentile, comparable IWB sector
  percentile, 20-session change in 20-session strength and 200-session trend.
  These are discovery measurements; no unvalidated alpha weights were added.
- Current H1/H2 and chronological fund replay share a checked-in core with
  the US_LISTED_USD_V1 profile. The USD-only runner rejects KR holdings and
  unnecessary currency conversion. Legacy 5+2 behavior remains supported.
- Separate late retrieval from original public availability for explicitly
  versioned factual archives. This does not certify historical PIT evidence
  or permit backdating today's quality judgments or revised financials.
- Normalize reviewed official interim observations for TSM and ASML through
  Q2 2026. Native currency, parent profit, gross PPE purchases and reporting
  periods remain explicit. Four contiguous quarters are required. The registry
  is observed now, uses some later comparative disclosures, and is prohibited
  from historical decisions. It is not a complete approved valuation packet.
- Restore exact immutable research captures and rebuild price/rate series from
  receipt-bound raw bytes. Check candidate membership against original IWB,
  SEC exchange and seed identity. Repair overwritten IWB sector labels during
  reconstruction. Do not recollect unchanged sources on each PR update.

## Execution and interpretation

`research_us_continue.yml` runs registered regression tests, restores verified
private inputs and publishes derived results. Manual source collection remains
available in `research_source_connection.yml` for a new dated snapshot.

```bash
python tools/continue_us_research.py --current CAPTURE --sample LONG_CAPTURE \
  --output RESULTS --fund-manifest CHRONOLOGICAL_MANIFEST
```

The current 1,118-company snapshot is not a historical universe. The long
24-company connection sample was chosen today by theme. Neither is silently
used as the 2019 eligible cohort. Missing chronological manifests produce a
blocked fund result with null metrics, not a fabricated cash strategy.

The separate SPY reference uses the long provider-adjusted series, fractional
benchmark units, 25 bps initial transaction cost, no forced final sale and
lagged DGS3MO initial releases. It is a comparison reference, not the requested
stock-selection strategy or proof of alpha. Report its methodology with its
CAGR, MDD, Sharpe and annual/monthly returns.

The requested integrated fullrun still requires complete date-indexed
membership, publication-timed financial packets, price/action cashflows and
reviewed as-of company/scenario/regime packets. Do not create fake approval
flags or rename an inadmissible survivor backtest to bypass that boundary.

## Sustainable updates

1. Retain source captures and receipt hashes; append each new capture under a
   fresh immutable research prefix. Change the restore registry only after its
   private byte check succeeds.
2. Append a reviewed interim observation version with source, pages, units,
   period and actual observation time; preserve previous versions. Never
   advance dates merely to make freshness checks pass.
3. Recompute all candidate horizons against one completed session and emit
   explicit coverage. A 504-session result needs at least 505 aligned prices.
4. Advance the chronological manifest only with validated new events and
   packets. The shared runner maintains cash, whole shares, next-close fills,
   costs, dividends, splits and delisting accounting; its synthetic tests do
   not establish actual investment performance.

No accepted portfolio, ledger, targets or champion is changed. PR review and
required exact-head checks remain necessary before merge.
