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
- `tests/forward_estimate_universe_plan_smoke.py`
- `tools/run_pr_validation.py` registration

The planner reads one or more CSV/parquet sources with a ticker-like column,
dedupes tickers, drops non-equity placeholders such as `CASH`, and writes shard
inputs for `.github/workflows/earnings_estimates_daily.yml`.

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

If the broad scan shows low coverage, the conclusion is a data entitlement
block, not an alpha failure. If coverage is usable, the next step is a
forward-only ranking and paper-ledger outcome report, not a backtest mutation.

## First Shard Dispatch

Initial shard-0 dispatch:

- GitHub Actions run: `29015925250`
- tickers requested: 50
- vendor order: `fmp,finnhub`
- fullrun: no
- status when this patch was prepared: in progress, still before collector
  output

The run must be inspected after completion before drawing any coverage or alpha
conclusion.
