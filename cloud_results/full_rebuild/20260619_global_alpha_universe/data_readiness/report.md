# Data Readiness Audit

- status: `warn`
- ready_for_fullrun: `true`
- ready_for_skip_collector_replay: `true`
- ready_for_policy_replay: `true`
- latest_target_date: `2026-04-30`
- latest_observable_close_date: `2026-06-17`
- effective_latest_target_date: `2026-04-30`

## Prices

- cache files: `1122`
- manifest end: `2026-06-18`
- manifest tickers: `510`

## Latest Outputs

| File | Rows | Max date | Weight sum |
| --- | ---: | --- | ---: |
| scored_latest | 661 | 2026-04-30 |  |
| portfolio_latest | 0 |  |  |
| concentrated_portfolio_latest | 3 | 2026-04-30 | 1.0 |

## Target Books

| Book | Rows | Min date | Max date | Weight sum |
| --- | ---: | --- | --- | ---: |
| main_history | 1976 | 2020-04-30 | 2026-03-31 | 71.99999999999991 |
| concentrated_history | 20328 | 2020-04-30 | 2026-03-31 | 4338.0 |
| operating_main | 1119 | 2020-04-30 | 2026-06-17 | 73.99999999999996 |
| operating_concentrated | 431 | 2020-04-30 | 2026-06-17 | 74.0 |

## Feature Source Coverage

- status: `ok`
- pit_future_available_from_rows: `0`

| Portfolio | Rows | Non-cash rows | Date range | Available-from columns |
| --- | ---: | ---: | --- | ---: |
| main | 1119 | 1045 | 2020-04-30 to 2026-06-17 | 4 |
| concentrated | 431 | 357 | 2020-04-30 to 2026-06-17 | 4 |

## Universe Health

- status: `pass`
- promotion_allowed: `true`
- r1000_base_count: `627`
- min_r1000_base: `400`
- primary_universe_source: `static_iwb_seed`
- fallback_used: `true`

## Blockers

- none

## Warnings

- dated target snapshot archive is missing for this run

## Next Actions

- Run tools/archive_target_snapshots.py after operating target books are built.
