# Free Historical Data Backfill Contract - 2026-07-10

## Objective

Build a durable free-data layer that can be reused by future CAGR/MDD research
without silently mixing point-in-time evidence, vendor snapshots, and proxy
membership data.

## Durable Stores

| Store | Path | Source | PIT usage |
|---|---|---|---|
| SEC company facts bulk | `data_raw/free/sec/companyfacts.zip` | SEC EDGAR bulk companyfacts | Actual filings only. Use accepted timestamps when materialized into features. |
| SEC ticker/CIK reference | `data_pit/free/sec_company_tickers.parquet` | SEC `company_tickers.json` plus raw manifest/hash | Current identity snapshot only. Fill blank CIKs uniquely; never overwrite existing conflicts or map cash placeholders. Not index membership. |
| Listing lifecycle | `data_pit/free/av_listing_status.parquet` | Alpha Vantage `LISTING_STATUS` | Reference lifecycle proxy. Helps delisted/survivorship audits; does not make Russell 1000 membership PIT-clean. |
| Earnings calendar history | `data_pit/events/earnings_calendar_history.parquet` | FMP earnings calendar | Vendor historical snapshot. Event/coverage audit only until event-time normalization is added. |
| Forward estimate snapshots | `data_pit/events/earnings_estimates/` | FMP/Finnhub/Alpha Vantage estimate endpoints | Forward-only archive from collection date onward. Do not backfill historical estimates from current snapshots. |
| Forward collection universe/checkpoint | `data_pit/events/earnings_estimates/collection_universe.csv` and `collection_checkpoint.json` | Exact current 993-row proxy universe plus archive history | Durable, resumable missing/stale/new queue. Includes one cash placeholder in audit state but never in vendor requests. |
| Forward revision signals | `data_pit/events/earnings_revision_signals.parquet` | Derived from forward estimate snapshots | Forward-only operating/paper-ledger signal until enough PIT history exists. |
| Forward paper ledger | `outputs/free_data_forward_paper_ledger/ledger_events.jsonl` | Latest-only selection observations and later adjusted-price outcomes | Append-only forward evidence. Contemporaneous receipt, exact next-NYSE-session entry, and exact-session 21D/63D/126D SPY-relative outcomes; never historical backtest acceptance. |
| Free price cache | `cache_prices/` plus `data_raw/free/prices/replay_price_cache_manifest.json` | Free price providers | Replay input only when manifest coverage/freshness checks pass. |

## Non-Negotiable Rules

- Do not write API keys into files, logs, manifests, or committed docs.
- Every stored dataset must carry source, collection time, path, and usage label.
- Vendor historical snapshots are not analyst revision history.
- Current forward estimates cannot be pasted into past rebalance dates.
- Missing coverage stays missing or neutral; do not impute alpha-positive data.
- `pit_universe_label_clean=false` remains a production-promotion blocker.
- Historical listing lifecycle narrows survivorship bounds but does not prove
  historical Russell 1000 constituents.

## Workflow

Collector-only historical backfill:

```bash
gh workflow run free_historical_data_backfill.yml \
  -f listing_status=true \
  -f fmp_earnings_calendar=false
```

Manual broad free-data bootstrap:

```bash
gh workflow run free_data_lake_bootstrap.yml \
  -f sec_companyfacts=true \
  -f listing_status=true \
  -f fmp_earnings_calendar=false \
  -f price_mode=target_books \
  -f max_price_tickers=0
```

Daily maintenance:

- `free_data_daily_update.yml` restores and syncs `data_raw/free`,
  `data_pit/free`, `data_pit/events`, `manifests/free_data`, `cache_prices`,
  and `data/catalog.json`.
- `earnings_estimates_daily.yml` appends forward-only estimate snapshots and
  same-day merges rather than shrinking broad snapshots. Its exact 993-row
  queue reuses fresh successes, collects only bounded missing/stale/new rows,
  and resumes from a hash-validated checkpoint. Retry order advances only for
  tickers the collector actually attempts; an unattempted tail remains due.
- FMP earnings calendar remains opt-in and disabled by default after HTTP 402.
  A 401/402/403 stops after the first chunk; do not retry without an access
  change.

## Validation Outputs

- `data/catalog.json`: current inventory, freshness, rows, ticker counts, and
  missing/stale feeds.
- `outputs/free_historical_data_coverage/universe_coverage.csv`: per-ticker
  coverage for SEC actuals, listing lifecycle, earnings-calendar history, and
  forward estimate snapshots.
- `outputs/free_historical_data_coverage/summary.json`: aggregate coverage
  ratios and known gaps.
- `data_pit/free/coverage_audit.json`: free data readiness and known gaps.
- `manifests/free_data/latest_manifest.json`: durable path manifest and action
  log.
- `outputs/free_historical_data_backfill/*_summary.json`: source-specific
  backfill summaries.
- `outputs/earnings_estimates_daily/collection_queue.csv`,
  `incremental_universe_summary.json`, and `collection_queue_report.md`:
  exact-universe queue/checkpoint status.
- `outputs/free_data_forward_paper_ledger/schema.json`, `summary.json`,
  `current_status.csv`, and `report.md`: append-only paper-ledger contract and
  pending/completed 21D/63D/126D coverage.

## CAGR/MDD Research Use

Allowed now:

- Coverage audits.
- Survivorship-bound narrowing from listing lifecycle.
- Event studies that respect event availability.
- Forward-only paper ledger monitoring from estimate snapshots.

Blocked until additional PIT proof:

- Using FMP historical earnings-calendar estimates as historical selection
  features.
- Using current forward estimates in 7Y backtests.
- Production promotion or public return claims from proxy data.
