# Data Readiness Audit

- status: `blocked`
- ready_for_fullrun: `false`
- ready_for_skip_collector_replay: `false`
- ready_for_policy_replay: `false`
- latest_target_date: `2026-06-18`
- latest_observable_close_date: `2026-06-18`
- effective_latest_target_date: `2026-06-18`

## Prices

- cache files: `1122`
- manifest end: `2026-06-18`
- manifest tickers: `539`

## Latest Outputs

| File | Rows | Max date | Weight sum |
| --- | ---: | --- | ---: |
| scored_latest | 737 | 2026-06-18 |  |
| portfolio_latest | 17 |  | 0.9999999999999992 |
| concentrated_portfolio_latest | 3 | 2026-06-18 | 1.0 |

## Target Books

| Book | Rows | Min date | Max date | Weight sum |
| --- | ---: | --- | --- | ---: |
| main_history | 2090 | 2019-06-28 | 2026-03-31 | 81.99999999975921 |
| concentrated_history | 23175 | 2019-06-28 | 2026-03-31 | 4939.5 |
| operating_main | 1267 | 2019-06-28 | 2026-06-17 | 83.99999999999994 |
| operating_concentrated | 490 | 2019-06-28 | 2026-06-18 | 83.99999999999999 |

## Feature Source Coverage

- status: `ok`
- pit_future_available_from_rows: `0`

| Portfolio | Rows | Non-cash rows | Date range | Available-from columns |
| --- | ---: | ---: | --- | ---: |
| main | 1267 | 1183 | 2019-06-28 to 2026-06-17 | 4 |
| concentrated | 490 | 406 | 2019-06-28 to 2026-06-18 | 4 |

## Universe Health

- status: `pass`
- promotion_allowed: `true`
- r1000_base_count: `700`
- min_r1000_base: `400`
- primary_universe_source: `static_iwb_seed`
- fallback_used: `true`

## Blockers

- main operating target book max date 2026-06-17 is older than latest target date 2026-06-18

## Warnings

- dated target snapshot archive is missing for this run

## Next Actions

- Run tools/archive_target_snapshots.py after operating target books are built.
