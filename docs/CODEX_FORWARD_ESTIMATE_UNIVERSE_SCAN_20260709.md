# Codex Forward Estimate Universe Scan - 2026-07-09

## Verdict

The user is right: latest estimate/revision data should not be limited to the
current Concentrated holdings. The correct workflow is to scan the broad
candidate universe, archive what free vendors can provide, and then let forward
evidence decide which names deserve attention.

This remains a forward-only evidence track. It does not improve or restate the
run287 7Y CAGR/MDD result, does not add an alpha hook, does not dispatch a
fullrun, and does not enable production.

## Implemented

- `tools/build_forward_estimate_universe_plan.py`
- `tools/build_forward_estimate_catchup_universe.py`
- `tools/build_earnings_estimate_archive_manifest.py`
- `tests/forward_estimate_universe_plan_smoke.py`
- `tests/earnings_estimate_catchup_universe_smoke.py`
- `tests/earnings_estimate_archive_manifest_smoke.py`
- `tools/run_pr_validation.py` registration

The planner reads one or more CSV/parquet sources with a ticker-like column,
dedupes tickers, drops non-equity placeholders such as `CASH`, and writes shard
inputs for `.github/workflows/earnings_estimates_daily.yml`.

The daily archive workflow also writes a per-run manifest and an append-only
archive index:

- `outputs/earnings_estimates_daily/archive_manifest.json`
- `data_pit/events/earnings_estimates/archive_index.jsonl`

The manifest records run id, fetch date, collector coverage, vendor order,
artifact name, file sizes, and SHA-256 hashes for the snapshot/signals/log
files. The index is restored from cache/GDrive and appended every run so future
agents can locate and verify old snapshots without relying on chat history.

Storage contract:

- Durable archive path: `data_pit/events/earnings_estimates/`
- Daily snapshot: `data_pit/events/earnings_estimates/estimates_YYYYMMDD.parquet`
- Append-only index: `data_pit/events/earnings_estimates/archive_index.jsonl`
- Derived latest PIT signals: `data_pit/events/earnings_revision_signals.parquet`
- Run summary/manifest/logs: `outputs/earnings_estimates_daily/`
- GitHub artifacts are temporary retention copies.
- GitHub cache is a convenience restore path, not the source of truth.
- Google Drive sync is the intended durable store for `data_pit/events/earnings_estimates/`
  and `data_pit/events/earnings_revision_signals.parquet`.

The data becomes historically usable only from its `available_from` fetch date
forward. Current/free vendor snapshots cannot be backfilled into dates before
the archive existed.

The scheduled archive rotates through the checked-in broad-universe shard plan.
Each scheduled run collects:

- the fixed core watchlist, so current high-priority names stay fresh
- one `outputs/forward_estimate_universe_plan_20260709/shards/shard_*.csv`
  file, selected by UTC day modulo shard count

This avoids trying to pull all 858 tickers in one run while still building
coverage across the full candidate universe over time.

Scheduled runs also build an incremental add-on universe from restored archive
history:

- known-covered tickers are recollected so future 30/90-day revision deltas can
  be measured
- newly added current-universe tickers are collected immediately instead of
  waiting for their shard date
- the selected rotating shard continues slow coverage retry for currently
  uncovered names

This is the normal operating mode after the all-shards baseline run. It stores
new forward snapshots only; it does not try to recreate missing historical
estimate data.

Manual catch-up is also available for the user's "cover most of the universe"
request. The workflow input `catchup_all_universe_shards=true` combines every
checked-in shard into one deduped universe CSV and archives it in one run. This
uses materially more free API quota, so it is manual-only; the scheduled job
remains one rotating shard plus the core watchlist.

Manual catch-up dispatch:

```bash
gh workflow run earnings_estimates_daily.yml \
  --repo wscha231/r1000-quant-engine \
  --ref master \
  -f catchup_all_universe_shards=true \
  -f ticker_limit=0 \
  -f collector_max_errors=5000 \
  -f vendor_order='fmp,finnhub'
```

The manifest/index records `shard_id=all_shards` and
`shard_mode=all_shards_catchup` so later agents can separate broad catch-up
runs from normal 65-name daily shard runs. Catch-up also raises the default
collector error cap from `100` to `5000`, because free-vendor entitlement and
coverage errors are expected when scanning the full universe.

Default source:

- `research/entry_classifier_predictions.csv`

This tracked research file currently provides a broad candidate universe and is
preferable to only scanning the latest 5-stock Concentrated book.

## Example

```bash
python tools/build_forward_estimate_universe_plan.py \
  --source research/entry_classifier_predictions.csv \
  --output-dir outputs/forward_estimate_universe_plan_20260709 \
  --shard-size 50 \
  --vendor-order fmp,finnhub
```

Outputs:

- `ticker_universe.csv`
- `shards/shard_000.csv`
- `shards/shard_000.txt`
- `dispatch_commands.ps1`
- `summary.json`
- `report.md`

Each generated command uses:

```bash
gh workflow run earnings_estimates_daily.yml \
  --repo wscha231/r1000-quant-engine \
  --ref master \
  -f tickers='<shard tickers>' \
  -f ticker_limit=0 \
  -f vendor_order='fmp,finnhub'
```

Alpha Vantage is intentionally not in the default vendor order until the
exposed-key rotation checklist is complete.

## Measurement Contract

Allowed:

- broad universe forward estimate archive
- coverage/ranking reports
- latest-only candidate confirmation
- forward paper-ledger evidence

Forbidden:

- retrofitting current estimate snapshots into 2019-2026 historical windows
- claiming a 7Y CAGR/MDD improvement from this current snapshot feed
- treating missing free-vendor coverage as a negative stock signal
- production promotion, live trading, or public performance claims
- dispatching a fullrun from this work

Missing coverage is neutral. It can tell us the free API is insufficient; it
cannot tell us the stock is bad.

## How This Helps CAGR/MDD Work

The direct historical CAGR/MDD target still needs PIT-safe evidence. Current
estimate snapshots cannot supply that. The near-term value is operational:

- find which broad-universe names have usable forward estimate data now
- rank current positive-revision candidates for forward paper tracking
- avoid overfitting only the current holdings
- accumulate a true `available_from=fetch_date` archive for future OOS review
- preserve file hashes and run metadata so future analysis can verify exactly
  which snapshot was used

If the broad scan shows low coverage, the conclusion is a data entitlement
block, not an alpha failure. If coverage is usable, the next step is a
forward-only ranking and paper-ledger outcome report, not a backtest mutation.

## First Shard Dispatch

Initial shard-0 dispatch:

- GitHub Actions run: `29015925250`
- tickers requested: 50
- vendor order: `fmp,finnhub`
- fullrun: no
- workflow conclusion: success
- collector status: `blocked_partial_coverage`
- estimate coverage: 2 / 50 tickers, 4%
- tickers with true forward estimates: `AAPL`, `ADBE`
- raw known-secret fragment scan: clean; persisted vendor URL credentials were
  masked as `apikey=***` and `token=***`

Interpretation: the broad-universe scan path works mechanically, but the
current free FMP/Finnhub entitlement is not enough to support a broad
estimate-revision alpha signal. Missing coverage remains neutral.

## All-Shards Catch-Up Dispatch

Manual all-shards catch-up after PR #256/#257:

- GitHub Actions run: `29028159934`
- head sha: `a086a2653fd8a4a2a0e927dc8a55572acd26fecd`
- workflow conclusion: success
- shard mode: `all_shards_catchup`
- source shards: 18
- tickers requested: 863
- snapshot rows: 863
- true forward-estimate rows: 13
- estimate coverage: 1.506%
- collector status: `blocked_partial_coverage`
- collector errors: 2551
- collector max errors: 5000
- secret scan: clean; persisted vendor URL credentials were masked as
  `apikey=***` and `token=***`
- artifact: `earnings-estimates-daily-29028159934`

Covered tickers with true forward-estimate rows:

`AAPL`, `MSFT`, `NVDA`, `AMD`, `PLTR`, `TSLA`, `GOOGL`, `META`, `AMZN`,
`TSM`, `ADBE`, `BA`, `BAC`.

Interpretation: the all-universe path now works and did request essentially the
whole checked-in candidate universe, but the free FMP/Finnhub entitlement is not
usable as a broad estimate-revision alpha source today. This is a data coverage
block, not a negative stock signal. Because this was the first all-universe
snapshot day, 30/90-day revision deltas are still unavailable/zero; the archive
must accumulate forward history before revision-change evidence can be scored.
