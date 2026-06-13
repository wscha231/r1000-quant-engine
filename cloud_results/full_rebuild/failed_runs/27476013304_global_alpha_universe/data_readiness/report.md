# Data Readiness Audit

- status: `warn`
- ready_for_fullrun: `true`
- ready_for_skip_collector_replay: `true`
- ready_for_policy_replay: `false`
- latest_target_date: `2026-06-12`
- latest_observable_close_date: `2026-06-12`
- effective_latest_target_date: `2026-06-12`

## Prices

- cache files: `1122`
- manifest end: `2026-06-12`
- manifest tickers: `543`

## Latest Outputs

| File | Rows | Max date | Weight sum |
| --- | ---: | --- | ---: |
| scored_latest | 737 | 2026-06-12 |  |
| portfolio_latest | 18 |  | 0.9999999999999993 |
| concentrated_portfolio_latest | 4 | 2026-06-12 | 1.0 |

## Target Books

| Book | Rows | Min date | Max date | Weight sum |
| --- | ---: | --- | --- | ---: |
| main_history | 1787 | 2019-05-31 | 2026-03-31 | 82.99999999999991 |
| concentrated_history | 23172 | 2019-05-31 | 2026-03-31 | 4999.499999999999 |
| operating_main | 1805 | 2019-05-31 | 2026-06-12 | 83.99999999999993 |
| operating_concentrated | 23176 | 2019-05-31 | 2026-06-12 | 5000.499999999998 |

## Feature Source Coverage

- status: `ok`
- pit_future_available_from_rows: `0`

| Portfolio | Rows | Non-cash rows | Date range | Available-from columns |
| --- | ---: | ---: | --- | ---: |
| main | 1805 | 1787 | 2019-05-31 to 2026-06-12 | 0 |
| concentrated | 23176 | 22390 | 2019-05-31 to 2026-06-12 | 0 |

## Blockers

- none

## Warnings

- dated target snapshot archive is missing for this run
- operating target books are missing sec_smart_money feature columns for portfolios: main

## Next Actions

- Build operating target books from the SEC-enriched candidate replay so Form4/13F/ETF/smart-money evidence is present or explicitly neutralized.
- Run tools/archive_target_snapshots.py after operating target books are built.
