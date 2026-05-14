# Data Readiness Audit

- status: `blocked`
- ready_for_fullrun: `false`
- ready_for_skip_collector_replay: `false`
- latest_target_date: `2026-05-14`

## Prices

- cache files: `1138`
- manifest end: ``
- manifest tickers: ``

## Latest Outputs

| File | Rows | Max date | Weight sum |
| --- | ---: | --- | ---: |
| scored_latest | 737 | 2026-05-14 |  |
| portfolio_latest | 18 |  | 0.9999999999999997 |
| concentrated_portfolio_latest | 4 | 2026-05-14 | 1.0 |

## Target Books

| Book | Rows | Min date | Max date | Weight sum |
| --- | ---: | --- | --- | ---: |
| main_history | 2162 | 2019-04-30 | 2026-02-27 | 82.9999999999999 |
| concentrated_history | 23436 | 2019-04-30 | 2026-02-27 | 4999.5 |
| operating_main | 2180 | 2019-04-30 | 2026-05-13 | 76.33881690438739 |
| operating_concentrated | 23440 | 2019-04-30 | 2026-05-14 | 4166.670192701755 |

## Blockers

- main operating target book max date 2026-05-13 is older than latest target date 2026-05-14

## Warnings

- price cache manifest end date is missing
- canonical data_raw/free/sec/companyfacts.zip is missing

## Next Actions

- Restore root companyfacts.zip into data_raw/free/sec or run the SEC companyfacts bootstrap.
