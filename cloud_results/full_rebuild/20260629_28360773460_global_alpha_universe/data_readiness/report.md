# Data Readiness Audit

- status: `warn`
- ready_for_fullrun: `true`
- ready_for_skip_collector_replay: `true`
- ready_for_policy_replay: `true`
- latest_target_date: `2026-06-29`
- latest_observable_close_date: `2026-06-26`
- effective_latest_target_date: `2026-06-26`

## Prices

- cache files: `1122`
- manifest end: `2026-06-26`
- manifest tickers: `541`

## Latest Outputs

| File | Rows | Max date | Weight sum |
| --- | ---: | --- | ---: |
| scored_latest | 742 | 2026-06-29 |  |
| portfolio_latest | 19 |  | 0.9999999999999996 |
| concentrated_portfolio_latest | 4 | 2026-06-29 | 1.0 |

## Target Books

| Book | Rows | Min date | Max date | Weight sum |
| --- | ---: | --- | --- | ---: |
| main_history | 2123 | 2019-05-31 | 2026-03-31 | 82.99999999999991 |
| concentrated_history | 23205 | 2019-05-31 | 2026-03-31 | 4999.499999999999 |
| operating_main | 1282 | 2019-05-31 | 2026-06-26 | 84.99999999999994 |
| operating_concentrated | 537 | 2019-05-31 | 2026-06-26 | 84.99999999999997 |

## Feature Source Coverage

- status: `ok`
- pit_future_available_from_rows: `0`

| Portfolio | Rows | Non-cash rows | Date range | Available-from columns |
| --- | ---: | ---: | --- | ---: |
| main | 1282 | 1197 | 2019-05-31 to 2026-06-26 | 4 |
| concentrated | 537 | 456 | 2019-05-31 to 2026-06-26 | 4 |

## Universe Health

- status: `pass`
- promotion_allowed: `true`
- r1000_base_count: `701`
- min_r1000_base: `400`
- primary_universe_source: `static_iwb_seed`
- fallback_used: `true`

## Blockers

- none

## Warnings

- latest target date 2026-06-29 is after latest observable close 2026-06-26; freshness gate uses observable close
- dated target snapshot archive is missing for this run

## Next Actions

- Run tools/archive_target_snapshots.py after operating target books are built.
