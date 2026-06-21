# 8-year Backtest Readiness

- Status: `not_ready`
- Min years: `8.0`
- PIT label: `None`
- Coverage readiness: `None`

## Price Cache

- Range: `None` to `None`
- Effective files: `1122` / required `0`
- Window ready: `False`

## Target Books

- Main: `2019-06-28` to `2026-03-31`, rows `1471`
- Concentrated: `2019-06-28` to `2026-03-31`, rows `23193`
- Window ready: `False`

## Broker Replay

- Main: `2019-07-01` to `2026-06-18`, CAGR `0.34423943947854885`
- Concentrated: `2019-07-01` to `2026-06-18`, CAGR `0.44604493718599425`
- Window ready: `False`

## Blockers

- 8-year price cache/manifest is not ready for proxy replay
- monthly target books do not cover the requested 8-year window
- broker-ledger official replay does not yet cover the requested 8-year window

## Warnings

- universe is labeled proxy, not PIT-safe official Russell 1000 history

## Next Actions

- Run free_data_lake_bootstrap.yml with price_mode=target_books and max_price_tickers=0.
- After 8-year target books exist, rerun broker-ledger replay and account evaluation.

## Data Extension Plan

- Target window: `2018-06-18` to `2026-06-18`
- Target-book tickers: `353`
- Hard blockers: `6`

| Task | Status | Action |
| --- | --- | --- |
| price_cache_window | needs_extension | Run free_data_lake_bootstrap.yml with price_mode=target_books and max_price_tickers=0. |
| price_cache_ticker_count | ready | none |
| main_target_book_window | needs_extension | Run full_rebuild_manual.yml with backtest_years=8 after price readiness so main target books extend across the full 8-year window. |
| concentrated_target_book_window | needs_extension | Run full_rebuild_manual.yml with backtest_years=8 after price readiness so concentrated target books extend across the full 8-year window. |
| main_broker_replay_window | needs_extension | Rerun broker-ledger replay/account evaluation after target books cover the full 8-year window. |
| concentrated_broker_replay_window | needs_extension | Rerun broker-ledger replay/account evaluation after target books cover the full 8-year window. |
| sec_companyfacts_archive | ready | none |
| pit_universe_label | needs_extension | Keep the run labeled proxy until historical membership, delistings, ADR eligibility, and ticker changes are PIT-safe. |

## Review Dispatch Plan

- `workflow_dispatch_payloads.json` and `workflow_dispatch_commands.sh` are review-only.
- They require explicit user approval before use.

| Plan | Workflow | Dependencies | Reason |
| --- | --- | --- | --- |
| bootstrap_free_data_for_eight_year_window | free_data_lake_bootstrap.yml |  | 8-year price cache is not ready; restore/extend target-book price history first. |
| full_rebuild_eight_year_official_window | full_rebuild_manual.yml | bootstrap_free_data_for_eight_year_window | Run the official 8-year broker-ledger rebuild after data readiness is available. |
