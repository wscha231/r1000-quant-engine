# Free Data Lake Plan

This plan keeps the first historical daily-decision system free-first. GitHub
remains the code and automation layer. Google Drive is the durable data store.
The local checkout is replaceable.

## Short Answer

Yes: GitHub Actions can use data stored in Google Drive, but only through an
authenticated sync step. It cannot see a personal Drive folder automatically.
Use the existing rclone pattern already present in the workflows:

- `GOOGLE_SERVICE_ACCOUNT_KEY` secret, plus an optional
  `GDRIVE_ROOT_FOLDER_ID` variable or secret.
- Or `RCLONE_CONFIG_GDRIVE` secret for an OAuth-backed rclone remote.
- Run `.github/workflows/gdrive_smoke_test.yml` after credentials change.

With that in place, GitHub Actions can download Drive data into `data_raw/`,
`data_pit/`, or cache folders before a run, then upload manifests and outputs
afterward.

## Storage Contract

GitHub should track code, configs, docs, tests, workflow YAML, and small
manifests. It should not track large raw archives, price caches, or parquet
feature stores.

Google Drive/object storage should hold:

- `data_raw/free/sec/`
  - SEC `companyfacts.zip`, `submissions.zip`, per-run raw filing snapshots,
    and a source manifest.
- `data_raw/free/prices/`
  - Free provider raw daily bars, split/dividend fields when available, and
    provider manifests.
- `data_raw/free/macro/`
  - FRED, BLS, BEA, Treasury, and other official macro time series snapshots.
- `data_raw/free/universe_proxy/`
  - Free approximate universe inputs, symbol maps, exchange listings, and
    eligibility snapshots.
- `data_pit/free/`
  - Normalized PIT-safe or PIT-labeled parquet/CSV outputs.
- `manifests/free_data/`
  - Data snapshot manifests, source versions, coverage audits, row counts,
    as-of dates, and known limitations.

Recommended normalized files:

- `data_pit/free/prices_daily.parquet`
- `data_pit/free/fundamentals_pit.parquet`
- `data_pit/free/macro_pit.parquet`
- `data_pit/free/universe_daily_proxy.parquet`
- `data_pit/free/feature_store_daily.parquet`
- `data_pit/free/coverage_audit.json`

## Free Source Tiers

Tier A: official and durable.

- SEC EDGAR submissions and XBRL company facts.
- FRED, BLS, BEA, Treasury and other government macro data.

Tier B: useful but needs reconciliation.

- Free daily price sources such as Stooq, free API tiers, and broker/export
  compatible historical bars.
- Use at least two sources when possible and write discrepancy reports before
  treating the result as official.

Tier C: proxy only.

- Current constituents, scraped lists, static Russell 1000 lists, or latest
  rescue/watch lists used as a historical universe.
- These must be labeled as `proxy` or `survivorship_risk` in outputs.

## Daily Decision Backtest Labels

Every historical result must carry one of these labels:

- `pit_safe`: uses date-valid price, filing-accepted fundamentals, and
  date-valid universe membership.
- `pit_proxy_universe`: uses PIT prices/fundamentals but approximate universe
  membership.
- `research_proxy`: uses current constituents, latest-only leaders, or partial
  historical data.

Until historical Russell 1000 membership and delisted coverage are solved, the
free system should not call itself an official Russell 1000 backtest. It should
be named a free-data large-cap proxy backtest.

## GitHub Actions Flow

1. Restore repo checkout and Python dependencies.
2. Install rclone and configure `gdrive` from secrets.
3. Copy the latest Drive data snapshot into the runner:
   - `data_raw/free/`
   - `data_pit/free/`
   - optional caches such as `cache_prices/`
4. Run collectors only for missing or stale snapshots.
5. Build normalized PIT files and coverage audits.
6. Run daily snapshot or backtest jobs.
7. Upload outputs, manifests, and updated data snapshots back to Drive.
8. Commit only small summaries or manifests to GitHub when useful.

## Credential Model

Service-account mode is the most stable for GitHub Actions:

1. Create a Google Cloud service account.
2. Store the JSON key as the GitHub secret `GOOGLE_SERVICE_ACCOUNT_KEY`.
3. Share the target Drive folder with the service account email.
4. Store the folder id as `GDRIVE_ROOT_FOLDER_ID`.
5. Run the Google Drive smoke workflow.

OAuth rclone mode also works, but it is more awkward to set up and rotate from
a phone-only environment.

## Guardrails

- Never commit raw Drive data, SEC bulk archives, or parquet stores to Git.
- Every data snapshot needs a manifest with:
  - `generated_at_utc`
  - source names and URLs
  - as-of date range
  - row counts
  - provider/license notes
  - PIT label
  - known gaps
- Daily operating snapshots may use the latest available close and skip market
  holidays. They should not create fake rows for non-trading days.
- Backtests must use only data available at the simulated decision date.
- Free source gaps must be shown in coverage reports, not hidden.

## Practical First Milestone

Build a 2016-2026 free-data proxy system before paying for vendors:

- SEC fundamentals with accepted filing dates.
- Free daily adjusted price cache with provider reconciliation.
- FRED/BLS/BEA macro snapshots.
- Proxy large-cap universe with explicit survivorship-risk labeling.
- Daily broker-ledger replay and current portfolio snapshot from the latest
  available close.

If that system shows the decision logic is promising, paid data should be used
only to remove the remaining major biases: historical Russell 1000 membership,
delisted price coverage, and vendor-normalized PIT fundamentals.
