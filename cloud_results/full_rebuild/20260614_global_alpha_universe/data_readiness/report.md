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
- manifest tickers: `514`

## Latest Outputs

| File | Rows | Max date | Weight sum |
| --- | ---: | --- | ---: |
| scored_latest | 736 | 2026-06-12 |  |
| portfolio_latest | 15 |  | 0.9999999999999996 |
| concentrated_portfolio_latest | 4 | 2026-06-12 | 1.0 |

## Target Books

| Book | Rows | Min date | Max date | Weight sum |
| --- | ---: | --- | --- | ---: |
| main_history | 1445 | 2019-05-31 | 2026-03-31 | 82.99999999999993 |
| concentrated_history | 23208 | 2019-05-31 | 2026-03-31 | 4999.5 |
| operating_main | 1280 | 2019-05-31 | 2026-06-12 | 84.99999999999997 |
| operating_concentrated | 497 | 2019-05-31 | 2026-06-12 | 85.0 |

## Feature Source Coverage

- status: `ok`
- pit_future_available_from_rows: `0`

| Portfolio | Rows | Non-cash rows | Date range | Available-from columns |
| --- | ---: | ---: | --- | ---: |
| main | 1280 | 1195 | 2019-05-31 to 2026-06-12 | 4 |
| concentrated | 497 | 412 | 2019-05-31 to 2026-06-12 | 4 |

## Blockers

- none

## Warnings

- dated target snapshot archive is missing for this run

## Next Actions

- Run tools/archive_target_snapshots.py after operating target books are built.
