# Historical Trade Journey

Status: `completed`

This report is sidecar-only. It reconstructs historical holdings and round-trip trades so current decisions can be compared against past ownership behavior.

## Summary

- Holding books: ['lifecycle_review_overlay_main', 'main_v2_research', 'monster_lifecycle_concentrated', 'monster_lifecycle_main', 'production_main']
- Holding runs: 1682
- Unique held tickers: 419
- Average run length: 3.15 months
- Median run length: 2.00 months
- Runs >= 6m / 12m: 263 / 18
- Trade journal rows: 713

## Longest Holding Runs

| book | ticker | entry_date | exit_date | status | months_held | total_return | max_weight | journey_tag |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| production_main | NVDA | 2019-11-29 | 2021-11-30 | closed | 25 | 466.18% | 11.29% | long_winner |
| monster_lifecycle_main | ANET | 2022-11-30 | 2024-11-29 | closed | 25 | 172.70% | 27.27% | long_winner |
| monster_lifecycle_concentrated | MLM | 2020-10-30 | 2022-01-31 | closed | 16 | 39.88% | 37.31% | normal |
| monster_lifecycle_main | MLM | 2020-10-30 | 2022-01-31 | closed | 16 | 39.88% | 18.33% | normal |
| production_main | BKNG | 2024-08-30 | 2025-10-31 | closed | 15 | 28.86% | 16.88% | normal |
| monster_lifecycle_main | HIG | 2023-11-30 | 2024-12-31 | closed | 14 | 42.70% | 13.74% | normal |
| lifecycle_review_overlay_main | NOW | 2023-01-31 | 2024-02-29 | closed | 14 | 53.50% | 24.12% | long_winner |
| monster_lifecycle_main | CB | 2023-11-30 | 2024-12-31 | closed | 14 | 22.31% | 6.11% | normal |
| lifecycle_review_overlay_main | CTAS | 2023-11-30 | 2024-12-31 | closed | 14 | 48.42% | 33.00% | normal |
| lifecycle_review_overlay_main | GOOGL | 2020-10-30 | 2021-11-30 | closed | 14 | 76.42% | 29.62% | long_winner |

## Largest Weighted Contributors

| book | ticker | entry_date | exit_date | months_held | total_return | weighted_contribution | journey_tag |
| --- | --- | --- | --- | --- | --- | --- | --- |
| monster_lifecycle_main | ANET | 2022-11-30 | 2024-11-29 | 25 | 172.70% | 22.62% | long_winner |
| main_v2_research | PLTR | 2024-06-28 | 2025-01-31 | 8 | 339.84% | 17.29% | long_winner |
| lifecycle_review_overlay_main | JBL | 2022-11-30 | 2023-11-30 | 13 | 80.88% | 15.67% | long_winner |
| monster_lifecycle_concentrated | ROKU | 2020-08-31 | 2021-01-29 | 6 | 142.14% | 14.82% | long_winner |
| main_v2_research | SMCI | 2024-01-31 | 2024-04-30 | 4 | 98.64% | 13.88% | normal |
| monster_lifecycle_main | XYZ | 2020-02-28 | 2020-10-30 | 9 | 179.72% | 12.89% | long_winner |
| production_main | NVDA | 2019-11-29 | 2021-11-30 | 25 | 466.18% | 12.61% | long_winner |
| monster_lifecycle_main | MELI | 2020-05-29 | 2021-01-29 | 9 | 114.86% | 11.34% | long_winner |
| main_v2_research | WDC | 2025-08-29 | 2026-02-27 | 7 | 224.16% | 10.73% | long_winner |
| monster_lifecycle_concentrated | AVGO | 2023-01-31 | 2023-09-29 | 9 | 48.45% | 10.37% | normal |

## Short Big Wins To Review

| book | ticker | entry_date | exit_date | months_held | total_return | journey_tag |
| --- | --- | --- | --- | --- | --- | --- |
| production_main | SMCI | 2024-01-31 | 2024-03-28 | 3 | 72.07% | short_big_win_review |
| main_v2_research | ELF | 2022-11-30 | 2023-01-31 | 3 | 65.92% | short_big_win_review |
| production_main | PYPL | 2020-04-30 | 2020-06-30 | 3 | 65.42% | short_big_win_review |
| production_main | MRNA | 2020-03-31 | 2020-03-31 | 1 | 62.10% | short_big_win_review |
| production_main | TSLA | 2019-12-31 | 2019-12-31 | 1 | 58.70% | short_big_win_review |
| main_v2_research | MU | 2020-10-30 | 2020-12-31 | 3 | 58.05% | short_big_win_review |
| production_main | VEEV | 2020-03-31 | 2020-05-29 | 3 | 56.31% | short_big_win_review |
| main_v2_research | XYZ | 2020-06-30 | 2020-07-31 | 2 | 55.42% | short_big_win_review |
| main_v2_research | VEEV | 2020-03-31 | 2020-05-29 | 3 | 55.07% | short_big_win_review |
| production_main | XYZ | 2020-06-30 | 2020-07-31 | 2 | 54.14% | short_big_win_review |
| main_v2_research | TER | 2025-10-31 | 2025-12-31 | 3 | 49.93% | short_big_win_review |
| production_main | BILL | 2021-06-30 | 2021-08-31 | 3 | 48.63% | short_big_win_review |

## Open Stale Watch

| book | ticker | entry_date | exit_date | months_held | total_return | recent_3m_return | journey_tag |
| --- | --- | --- | --- | --- | --- | --- | --- |
| lifecycle_review_overlay_main | GOOGL | 2025-07-31 | 2026-02-27 | 8 | 55.35% | -7.47% | open_stale_watch |

## Current Holdings Versus History

| current_book | ticker | current_weight | history_status | total_months_held | run_count | current_run_months | current_run_return | current_run_tag |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| current_concentrated | GLW | 50.00% | returning_after_gap | 1.0000 | 1.0000 | 1.0000 | -6.98% | normal |
| current_concentrated | CIEN | 30.00% | open_history | 4.0000 | 4.0000 | 1.0000 | 13.55% | normal |
| current_concentrated | WDC | 20.00% | open_history | 13.0000 | 3.0000 | 4.0000 | 76.36% | normal |
| current_main | GOOGL | 17.60% | open_history | 87.0000 | 24.0000 | 8.0000 | 55.35% | open_stale_watch |
| current_main | NVDA | 9.45% | returning_after_gap | 105.0000 | 15.0000 | 8.0000 | 23.11% | normal |
| current_main | VRT | 6.21% | open_history | 15.0000 | 5.0000 | 1.0000 | 3.06% | normal |
| current_main | FTI | 6.08% | open_history | 5.0000 | 5.0000 | 1.0000 | 8.00% | normal |
| current_main | GEV | 5.99% | new_unseen |  |  |  |  |  |
| current_main | FIX | 5.22% | new_unseen |  |  |  |  |  |
| current_main | LRCX | 4.76% | open_history | 95.0000 | 23.0000 | 6.0000 | 63.18% | open_winner_hold |
| current_main | AMAT | 4.76% | open_history | 61.0000 | 10.0000 | 3.0000 | 29.44% | short_big_win_review |
| current_main | ASML | 4.33% | open_history | 76.0000 | 14.0000 | 5.0000 | 26.75% | normal |
| current_main | TSM | 4.31% | new_unseen |  |  |  |  |  |
| current_main | FANG | 4.25% | returning_after_gap | 50.0000 | 15.0000 | 6.0000 | -2.17% | normal |
| current_main | GLW | 4.22% | returning_after_gap | 1.0000 | 1.0000 | 1.0000 | -6.98% | normal |
| current_main | PR | 4.00% | open_history | 5.0000 | 4.0000 | 1.0000 | 10.91% | normal |
| current_main | UMC | 4.00% | new_unseen |  |  |  |  |  |
| current_main | DTM | 4.00% | returning_after_gap | 2.0000 | 1.0000 | 2.0000 | -7.74% | normal |
| current_main | MLI | 4.00% | returning_after_gap | 17.0000 | 6.0000 | 1.0000 | 5.56% | normal |
| current_main | TER | 3.70% | returning_after_gap | 21.0000 | 7.0000 | 3.0000 | 49.93% | short_big_win_review |
| current_main | ON | 3.10% | returning_after_gap | 10.0000 | 6.0000 | 1.0000 | -7.82% | normal |

## Reentry Churn Watch

| ticker | trade_count | win_rate | avg_realized_return | avg_holding_days | compound_realized_return | churn_tag |
| --- | --- | --- | --- | --- | --- | --- |
| GOOGL | 9 | 0.5556 | 9.83% | 54.2222 | 94.78% | profitable_reentry_churn |
| COST | 8 | 0.5000 | 4.64% | 41.7500 | 35.29% | profitable_reentry_churn |
| AMZN | 8 | 0.5000 | 3.28% | 42.2500 | 21.29% | profitable_reentry_churn |
| CTAS | 7 | 0.5714 | 3.96% | 35.2857 | 27.77% | profitable_reentry_churn |
| AAPL | 6 | 0.6667 | 6.62% | 55.3333 | 42.62% | profitable_reentry_churn |
| STLD | 6 | 0.5000 | 1.51% | 45.6667 | 4.82% | profitable_reentry_churn |
| VRTX | 6 | 0.5000 | 1.68% | 66.1667 | 7.78% | profitable_reentry_churn |
| FTNT | 6 | 0.5000 | 13.36% | 36.0000 | 95.58% | profitable_reentry_churn |
| ORCL | 6 | 0.1667 | -6.79% | 71.8333 | -34.84% | unproductive_reentry_churn |
| EXP | 5 | 0.6000 | 5.01% | 30.0000 | 25.19% | profitable_reentry_churn |
| NRG | 5 | 0.4000 | 5.50% | 42.2000 | 23.95% | profitable_reentry_churn |
| ETR | 5 | 0.6000 | 1.01% | 55.0000 | 3.36% | profitable_reentry_churn |
| CPRT | 5 | 0.6000 | 4.78% | 61.0000 | 25.18% | profitable_reentry_churn |
| BIO | 5 | 0.6000 | 9.46% | 30.6000 | 49.17% | profitable_reentry_churn |
| XYZ | 5 | 0.4000 | 13.64% | 43.0000 | 66.44% | profitable_reentry_churn |
