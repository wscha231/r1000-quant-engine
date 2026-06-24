# Data Readiness Audit

- status: `warn`
- ready_for_fullrun: `true`
- ready_for_skip_collector_replay: `true`
- ready_for_policy_replay: `true`
- latest_target_date: `2026-06-24`
- latest_observable_close_date: `2026-06-23`
- effective_latest_target_date: `2026-06-23`

## Prices

- cache files: `1122`
- manifest end: `2026-06-23`
- manifest tickers: `545`

## Latest Outputs

| File | Rows | Max date | Weight sum |
| --- | ---: | --- | ---: |
| scored_latest | 741 | 2026-06-24 |  |
| portfolio_latest | 19 |  | 0.9999999999999996 |
| concentrated_portfolio_latest | 4 | 2026-06-24 | 1.0 |

## Target Books

| Book | Rows | Min date | Max date | Weight sum |
| --- | ---: | --- | --- | ---: |
| main_history | 2109 | 2019-05-31 | 2026-03-31 | 82.99999999999991 |
| concentrated_history | 23181 | 2019-05-31 | 2026-03-31 | 4999.499999999999 |
| operating_main | 1282 | 2019-05-31 | 2026-06-23 | 84.99999999999994 |
| operating_concentrated | 497 | 2019-05-31 | 2026-06-23 | 85.0 |

## Feature Source Coverage

- status: `ok`
- pit_future_available_from_rows: `0`

| Portfolio | Rows | Non-cash rows | Date range | Available-from columns |
| --- | ---: | ---: | --- | ---: |
| main | 1282 | 1197 | 2019-05-31 to 2026-06-23 | 4 |
| concentrated | 497 | 412 | 2019-05-31 to 2026-06-23 | 4 |

## Universe Health

- status: `pass`
- promotion_allowed: `true`
- r1000_base_count: `700`
- min_r1000_base: `400`
- primary_universe_source: `static_iwb_seed`
- fallback_used: `true`

## Blockers

- none

## Warnings

- latest target date 2026-06-24 is after latest observable close 2026-06-23; freshness gate uses observable close
- dated target snapshot archive is missing for this run

## Next Actions

- Run tools/archive_target_snapshots.py after operating target books are built.
