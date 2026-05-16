# Data Readiness Audit

- status: `warn`
- ready_for_fullrun: `true`
- ready_for_skip_collector_replay: `true`
- latest_target_date: `2026-05-15`

## Prices

- cache files: `866`
- manifest end: `2026-05-18`
- manifest tickers: `456`

## Latest Outputs

| File | Rows | Max date | Weight sum |
| --- | ---: | --- | ---: |
| scored_latest | 746 | 2026-05-15 |  |
| portfolio_latest | 17 |  | 0.9999999999999987 |
| concentrated_portfolio_latest | 7 | 2026-05-15 | 0.9999999999999996 |

## Target Books

| Book | Rows | Min date | Max date | Weight sum |
| --- | ---: | --- | --- | ---: |
| main_history | 1977 | 2019-05-31 | 2026-02-27 | 81.99999999999991 |
| concentrated_history | 22908 | 2019-05-31 | 2026-02-27 | 4939.499999999999 |
| operating_main | 1994 | 2019-05-31 | 2026-05-15 | 82.99999999999991 |
| operating_concentrated | 22915 | 2019-05-31 | 2026-05-15 | 4940.499999999999 |

## Blockers

- none

## Warnings

- canonical data_raw/free/sec/companyfacts.zip is missing

## Next Actions

- Restore root companyfacts.zip into data_raw/free/sec or run the SEC companyfacts bootstrap.
