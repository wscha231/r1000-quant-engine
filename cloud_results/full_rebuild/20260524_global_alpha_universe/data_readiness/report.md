# Data Readiness Audit

- status: `warn`
- ready_for_fullrun: `true`
- ready_for_skip_collector_replay: `true`
- latest_target_date: `2026-05-22`

## Prices

- cache files: `842`
- manifest end: ``
- manifest tickers: ``

## Latest Outputs

| File | Rows | Max date | Weight sum |
| --- | ---: | --- | ---: |
| scored_latest | 725 | 2026-05-22 |  |
| portfolio_latest | 14 |  | 0.9999999999999993 |
| concentrated_portfolio_latest | 3 | 2026-05-22 | 1.0 |

## Target Books

| Book | Rows | Min date | Max date | Weight sum |
| --- | ---: | --- | --- | ---: |
| main_history | 1664 | 2019-05-31 | 2026-02-27 | 81.99999999999994 |
| concentrated_history | 22770 | 2019-05-31 | 2026-02-27 | 4939.5 |
| operating_main | 1678 | 2019-05-31 | 2026-05-22 | 82.99999999999994 |
| operating_concentrated | 22773 | 2019-05-31 | 2026-05-22 | 4940.499999999999 |

## Blockers

- none

## Warnings

- price cache manifest end date is missing
- canonical data_raw/free/sec/companyfacts.zip is missing

## Next Actions

- Restore root companyfacts.zip into data_raw/free/sec or run the SEC companyfacts bootstrap.
