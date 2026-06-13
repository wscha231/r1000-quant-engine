# Data Readiness Audit

- status: `warn`
- ready_for_fullrun: `true`
- ready_for_skip_collector_replay: `true`
- ready_for_policy_replay: `true`
- latest_target_date: `2026-06-12`
- latest_observable_close_date: `2026-06-12`
- effective_latest_target_date: `2026-06-12`

## Prices

- cache files: `1122`
- manifest end: `2026-06-12`
- manifest tickers: `553`

## Latest Outputs

| File | Rows | Max date | Weight sum |
| --- | ---: | --- | ---: |
| scored_latest | 740 | 2026-06-12 |  |
| portfolio_latest | 19 |  | 0.9999999999999997 |
| concentrated_portfolio_latest | 3 | 2026-06-12 | 0.9999999999999998 |

## Target Books

| Book | Rows | Min date | Max date | Weight sum |
| --- | ---: | --- | --- | ---: |
| main_history | 2172 | 2019-05-31 | 2026-03-31 | 82.99999999999991 |
| concentrated_history | 23199 | 2019-05-31 | 2026-03-31 | 4999.499999999999 |
| operating_main | 1283 | 2019-05-31 | 2026-06-12 | 84.99999999999994 |
| operating_concentrated | 497 | 2019-05-31 | 2026-06-12 | 84.99999999999997 |

## Feature Source Coverage

- status: `ok`
- pit_future_available_from_rows: `0`

| Portfolio | Rows | Non-cash rows | Date range | Available-from columns |
| --- | ---: | ---: | --- | ---: |
| main | 1283 | 1198 | 2019-05-31 to 2026-06-12 | 4 |
| concentrated | 497 | 412 | 2019-05-31 to 2026-06-12 | 4 |

## Blockers

- none

## Warnings

- dated target snapshot archive is missing for this run

## Next Actions

- Run tools/archive_target_snapshots.py after operating target books are built.
