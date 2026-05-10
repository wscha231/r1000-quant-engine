# Free Backtest And Learning Plan

This plan connects the free-first data lake to historical daily-decision
backtests, AutoLearning, and engine promotion. The goal is not to create a
second strategy stack. The goal is to feed cleaner, better-labeled data into
the existing broker replay, monster lifecycle, policy fusion, and learning
sidecars.

## Phase 1: Bootstrap Free Data

Status: implemented as the first executable path.

- Use `.github/workflows/free_data_lake_bootstrap.yml`.
- Restore existing Drive data into:
  - `data_raw/free/`
  - `data_pit/free/`
  - `cache_prices/`
  - `manifests/free_data/`
- Seed or refresh:
  - SEC bulk fundamentals, optionally, because the file is large.
  - Macro daily snapshot.
  - Free replay price cache from current target books and scored leaders.
- Write:
  - `manifests/free_data/latest_manifest.json`
  - `data_pit/free/coverage_audit.json`
  - `outputs/free_data_lake_bootstrap/summary.json`
  - `outputs/free_data_engine_validation/summary.json`
  - `outputs/free_data_engine_validation/report.md`

Default mode is conservative. It does not download the 1GB+ SEC archive and it
dry-runs price collection until Drive auth and restore are confirmed.

## Phase 2: Normalize PIT Datasets

Target outputs:

- `data_pit/free/prices_daily.parquet`
- `data_pit/free/fundamentals_pit.parquet`
- `data_pit/free/macro_pit.parquet`
- `data_pit/free/universe_daily_proxy.parquet`
- `data_pit/free/feature_store_daily.parquet`

Rules:

- Price rows must be keyed by `ticker`, `date`, `open`, `high`, `low`,
  `close`, `adj_close`, `volume`, and source fields.
- Fundamental rows must be keyed by `ticker`, `cik`, `fiscal_period`,
  `filed_at`, and `available_from`.
- Macro rows must preserve release dates or first-known timestamps when
  available.
- Universe rows must carry `universe_label` and `pit_label`.

Free data starts as `pit_proxy_universe` until historical Russell 1000
membership and delisted coverage are solved.

## Phase 3: Daily Decision Replay

The backtest should simulate each trading date as if the engine were operating
after the close:

1. Load only data available at that decision date.
2. Score eligible names.
3. Build candidate targets.
4. Apply macro policy and cash floors.
5. Apply monster hold/trim/replace overlay.
6. Generate target deltas, not blind buy/sell instructions.
7. Fill on next close with transaction costs and fill-lag limits.
8. Mark the portfolio to market daily.

Outputs should be broker-like:

- positions
- cash ledger
- trade journal
- daily equity curve
- current snapshot
- reason-coded review actions

## Phase 4: Learning Loop

Use the existing learning stack after the replay emits enough evidence:

- `tools/run_auto_learning_v2.py`
- `tools/run_autolearning_winner_challenger.py`
- `tools/run_alphaops_policy_fusion.py`
- winner onset and shakeout studies
- monster lifecycle replay
- cash-drag and crisis-reentry replay

Learning must be gated:

- Promote only if a challenger improves out-of-sample CAGR/Sharpe/drawdown or
  reduces avoidable churn without hiding risk.
- Never promote a rule based only on current constituents or latest-only
  winners.
- Store every candidate policy with evidence, counterfactual result, and data
  label.

Performance validation is handled by
`tools/run_free_data_engine_validation.py`. It collects main and concentrated
broker replay metrics, including CAGR, Sharpe, MaxDD, ending capital, cash, and
trade count, then writes the next action gate. Learning work should start only
after this report reaches `ready_for_learning_review`.

## Phase 5: Engine Strengthening Targets

The first rules to improve should match the user's operating intent:

- Hold monster leaders longer when leadership, trend, and fundamentals remain
  intact.
- Detect leadership break earlier with relative strength decay, failed
  recoveries, distribution days, sector rotation, and earnings damage.
- Avoid monthly mechanical churn when the current holding still dominates.
- Replace only when a better leader has clear evidence and liquidity.
- Separate cash policy from individual portfolio cash rows.
- Make every snapshot show what is actually held, not only target weights.

## Initial Execution Sequence

1. Run `gdrive_smoke_test.yml` if Drive credentials changed.
2. Run `free_data_lake_bootstrap.yml` with:
   - `price_mode=dry_run`
   - `sec_companyfacts=false`
   - `run_proxy_replay=true`
3. If Drive restore/sync works, rerun with:
   - `price_mode=target_books`
   - `max_price_tickers=80`
4. If the first price run is stable, rerun with:
   - `max_price_tickers=0`
5. After price coverage is adequate, enable:
   - `sec_companyfacts=true`
6. Then add the PIT normalizer and daily-decision replay against
   `data_pit/free/`.

For continuous updates, `.github/workflows/free_data_daily_update.yml` runs
after the US close on scheduled trading days. It checks the latest NYSE close,
skips stale/holiday windows, refreshes free data, runs proxy broker replays,
and writes the engine validation report.

## Success Criteria

- Data manifest exists on Drive and in workflow artifacts.
- Coverage audit explicitly reports PIT/proxy status.
- Broker replay can produce daily equity from free-restored data.
- Current portfolio snapshot remains as-of the latest available close.
- Learning sidecars consume replay evidence and produce gated candidates.
- No output labels free proxy data as official Russell 1000 history.
