# Data Readiness Audit

- status: `warn`
- ready_for_fullrun: `true`
- ready_for_skip_collector_replay: `true`
- ready_for_policy_replay: `true`
- latest_target_date: `2026-06-05`
- latest_observable_close_date: `2026-06-05`
- effective_latest_target_date: `2026-06-05`

## Prices

- cache files: `1122`
- manifest end: `2026-06-05`
- manifest tickers: `550`

## Latest Outputs

| File | Rows | Max date | Weight sum |
| --- | ---: | --- | ---: |
| scored_latest | 739 | 2026-06-05 |  |
| portfolio_latest | 18 |  | 0.9999999999999993 |
| concentrated_portfolio_latest | 4 | 2026-06-05 | 0.9999999999999998 |

## Target Books

| Book | Rows | Min date | Max date | Weight sum |
| --- | ---: | --- | --- | ---: |
| main_history | 2240 | 2019-05-31 | 2026-03-31 | 82.9999999999999 |
| concentrated_history | 23223 | 2019-05-31 | 2026-03-31 | 4999.499999999999 |
| operating_main | 1281 | 2019-05-31 | 2026-06-05 | 84.99999999999996 |
| operating_concentrated | 496 | 2019-05-31 | 2026-06-05 | 85.0 |

## Feature Source Coverage

- status: `ok`
- pit_future_available_from_rows: `0`

| Portfolio | Rows | Non-cash rows | Date range | Available-from columns |
| --- | ---: | ---: | --- | ---: |
| main | 1281 | 1196 | 2019-05-31 to 2026-06-05 | 3 |
| concentrated | 496 | 411 | 2019-05-31 to 2026-06-05 | 3 |

## Blockers

- none

## Warnings

- dated target snapshot archive is missing for this run

## Next Actions

- Run tools/archive_target_snapshots.py after operating target books are built.
