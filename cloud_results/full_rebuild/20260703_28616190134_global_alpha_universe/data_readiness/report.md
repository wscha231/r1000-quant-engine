# Data Readiness Audit

- status: `warn`
- ready_for_fullrun: `true`
- ready_for_skip_collector_replay: `true`
- ready_for_policy_replay: `true`
- latest_target_date: `2026-07-02`
- latest_observable_close_date: `2026-07-02`
- effective_latest_target_date: `2026-07-02`

## Prices

- cache files: `1122`
- manifest end: `2026-07-02`
- manifest tickers: `533`

## Latest Outputs

| File | Rows | Max date | Weight sum |
| --- | ---: | --- | ---: |
| scored_latest | 741 | 2026-07-02 |  |
| portfolio_latest | 18 |  | 0.9999999999999993 |
| concentrated_portfolio_latest | 3 | 2026-07-02 | 1.0 |

## Target Books

| Book | Rows | Min date | Max date | Weight sum |
| --- | ---: | --- | --- | ---: |
| main_history | 2031 | 2019-05-31 | 2026-04-30 | 83.99999999999991 |
| concentrated_history | 23481 | 2019-05-31 | 2026-04-30 | 5060.999999999999 |
| operating_main | 1302 | 2019-05-31 | 2026-07-02 | 85.99999999999996 |
| operating_concentrated | 504 | 2019-05-31 | 2026-07-02 | 86.0 |

## Feature Source Coverage

- status: `ok`
- pit_future_available_from_rows: `0`

| Portfolio | Rows | Non-cash rows | Date range | Available-from columns |
| --- | ---: | ---: | --- | ---: |
| main | 1302 | 1216 | 2019-05-31 to 2026-07-02 | 4 |
| concentrated | 504 | 418 | 2019-05-31 to 2026-07-02 | 4 |

## Universe Health

- status: `pass`
- promotion_allowed: `true`
- r1000_base_count: `700`
- min_r1000_base: `400`
- primary_universe_source: `static_iwb_seed`
- fallback_used: `true`

## Blockers

- none

## Warnings

- dated target snapshot archive is missing for this run

## Next Actions

- Run tools/archive_target_snapshots.py after operating target books are built.
