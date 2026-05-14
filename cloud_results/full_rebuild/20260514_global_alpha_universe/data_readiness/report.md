# Data Readiness Audit

- status: `blocked`
- ready_for_fullrun: `false`
- ready_for_skip_collector_replay: `false`
- latest_target_date: `2026-05-14`

## Prices

- cache files: `1124`
- manifest end: ``
- manifest tickers: ``

## Latest Outputs

| File | Rows | Max date | Weight sum |
| --- | ---: | --- | ---: |
| scored_latest | 732 | 2026-05-14 |  |
| portfolio_latest | 17 |  | 0.9999999999999996 |
| concentrated_portfolio_latest | 3 | 2026-05-14 | 1.0 |

## Target Books

| Book | Rows | Min date | Max date | Weight sum |
| --- | ---: | --- | --- | ---: |
| main_history | 2123 | 2019-04-30 | 2026-02-27 | 82.99999999999991 |
| concentrated_history | 23454 | 2019-04-30 | 2026-02-27 | 4999.499999999999 |
| operating_main | 2140 | 2019-04-30 | 2026-05-13 | 83.9999999999999 |
| operating_concentrated | 23457 | 2019-04-30 | 2026-05-14 | 5000.499999999999 |

## Blockers

- main operating target book max date 2026-05-13 is older than latest target date 2026-05-14

## Warnings

- price cache manifest end date is missing
- canonical data_raw/free/sec/companyfacts.zip is missing

## Next Actions

- Restore root companyfacts.zip into data_raw/free/sec or run the SEC companyfacts bootstrap.
