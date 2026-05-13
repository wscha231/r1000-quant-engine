# Data Readiness Audit

- status: `blocked`
- ready_for_fullrun: `false`
- ready_for_skip_collector_replay: `false`
- latest_target_date: `2026-05-13`

## Prices

- cache files: `1124`
- manifest end: ``
- manifest tickers: ``

## Latest Outputs

| File | Rows | Max date | Weight sum |
| --- | ---: | --- | ---: |
| scored_latest | 732 | 2026-05-13 |  |
| portfolio_latest | 13 |  | 0.9999999999999997 |
| concentrated_portfolio_latest | 4 | 2026-05-13 | 0.9999999999999999 |

## Target Books

| Book | Rows | Min date | Max date | Weight sum |
| --- | ---: | --- | --- | ---: |
| main_history | 1617 | 2019-04-30 | 2026-02-27 | 82.99999999999994 |
| concentrated_history | 23436 | 2019-04-30 | 2026-02-27 | 4999.5 |
| operating_main | 1630 | 2019-04-30 | 2026-05-12 | 83.99999999999993 |
| operating_concentrated | 23440 | 2019-04-30 | 2026-05-13 | 5000.499999999999 |

## Blockers

- main operating target book max date 2026-05-12 is older than latest target date 2026-05-13

## Warnings

- price cache manifest end date is missing
- canonical data_raw/free/sec/companyfacts.zip is missing

## Next Actions

- Restore root companyfacts.zip into data_raw/free/sec or run the SEC companyfacts bootstrap.
