# Data Readiness Audit

- status: `blocked`
- ready_for_fullrun: `false`
- ready_for_skip_collector_replay: `false`
- latest_target_date: `2026-05-12`

## Prices

- cache files: `1124`
- manifest end: ``
- manifest tickers: ``

## Latest Outputs

| File | Rows | Max date | Weight sum |
| --- | ---: | --- | ---: |
| scored_latest | 734 | 2026-05-12 |  |
| portfolio_latest | 17 |  | 0.9999999999999993 |
| concentrated_portfolio_latest | 4 | 2026-05-12 | 1.0 |

## Target Books

| Book | Rows | Min date | Max date | Weight sum |
| --- | ---: | --- | --- | ---: |
| main_history | 1852 | 2019-04-30 | 2026-02-27 | 82.99999999999991 |
| concentrated_history | 23475 | 2019-04-30 | 2026-02-27 | 4999.5 |
| operating_main | 1869 | 2019-04-30 | 2026-05-08 | 83.99999999999991 |
| operating_concentrated | 23479 | 2019-04-30 | 2026-05-12 | 5000.499999999999 |

## Blockers

- main operating target book max date 2026-05-08 is older than latest target date 2026-05-12

## Warnings

- price cache manifest end date is missing
- canonical data_raw/free/sec/companyfacts.zip is missing

## Next Actions

- Restore root companyfacts.zip into data_raw/free/sec or run the SEC companyfacts bootstrap.
