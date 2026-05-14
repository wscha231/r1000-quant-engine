# Data Readiness Audit

- status: `blocked`
- ready_for_fullrun: `false`
- ready_for_skip_collector_replay: `false`
- latest_target_date: `2026-05-15`

## Prices

- cache files: `1137`
- manifest end: ``
- manifest tickers: ``

## Latest Outputs

| File | Rows | Max date | Weight sum |
| --- | ---: | --- | ---: |
| scored_latest | 745 | 2026-05-15 |  |
| portfolio_latest | 17 |  | 0.9999999999999996 |
| concentrated_portfolio_latest | 5 | 2026-05-15 | 1.0 |

## Target Books

| Book | Rows | Min date | Max date | Weight sum |
| --- | ---: | --- | --- | ---: |
| main_history | 2194 | 2019-04-30 | 2026-02-27 | 82.99999999999991 |
| concentrated_history | 23382 | 2019-04-30 | 2026-02-27 | 4999.5 |
| operating_main | 2211 | 2019-04-30 | 2026-05-14 | 76.3420408180361 |
| operating_concentrated | 23387 | 2019-04-30 | 2026-05-15 | 4174.19441984332 |

## Blockers

- main operating target book max date 2026-05-14 is older than latest target date 2026-05-15

## Warnings

- price cache manifest end date is missing
- canonical data_raw/free/sec/companyfacts.zip is missing

## Next Actions

- Restore root companyfacts.zip into data_raw/free/sec or run the SEC companyfacts bootstrap.
