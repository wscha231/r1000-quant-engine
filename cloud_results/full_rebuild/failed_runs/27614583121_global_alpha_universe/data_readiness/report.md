# Data Readiness Audit

- status: `blocked`
- ready_for_fullrun: `false`
- ready_for_skip_collector_replay: `false`
- ready_for_policy_replay: `false`
- latest_target_date: `2026-06-16`
- latest_observable_close_date: `2026-06-12`
- effective_latest_target_date: `2026-06-12`

## Prices

- cache files: `1122`
- manifest end: `2026-06-15`
- manifest tickers: `565`

## Latest Outputs

| File | Rows | Max date | Weight sum |
| --- | ---: | --- | ---: |
| scored_latest | 259 | 2026-06-16 |  |
| portfolio_latest | 19 |  | 0.9999999999999994 |
| concentrated_portfolio_latest | 3 | 2026-06-16 | 0.9999999999999999 |

## Target Books

| Book | Rows | Min date | Max date | Weight sum |
| --- | ---: | --- | --- | ---: |
| main_history | 2105 | 2019-05-31 | 2026-03-31 | 82.99999999999991 |
| concentrated_history | 23235 | 2019-05-31 | 2026-03-31 | 4999.5 |
| operating_main | 1281 | 2019-05-31 | 2026-06-12 | 84.99999999999997 |
| operating_concentrated | 497 | 2019-05-31 | 2026-06-12 | 85.0 |

## Feature Source Coverage

- status: `ok`
- pit_future_available_from_rows: `0`

| Portfolio | Rows | Non-cash rows | Date range | Available-from columns |
| --- | ---: | ---: | --- | ---: |
| main | 1281 | 1196 | 2019-05-31 to 2026-06-12 | 4 |
| concentrated | 497 | 412 | 2019-05-31 to 2026-06-12 | 4 |

## Blockers

- scored_latest.csv row count is below threshold: 259

## Warnings

- latest target date 2026-06-16 is after latest observable close 2026-06-12; freshness gate uses observable close
- dated target snapshot archive is missing for this run

## Next Actions

- Run tools/archive_target_snapshots.py after operating target books are built.
