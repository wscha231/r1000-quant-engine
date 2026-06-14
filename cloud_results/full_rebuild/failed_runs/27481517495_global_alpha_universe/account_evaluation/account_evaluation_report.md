# Account Evaluation

Official performance evidence uses broker-ledger replay with next-close fills, integer shares, cash, and transaction costs.
Legacy weight-level backtest metrics are retained only as research comparison fields and cannot produce a production SHIP verdict.

## Official Targets

| Portfolio | CAGR | Target | Gap | MaxDD | Target | Gap | Sharpe | Avg Cash | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 22.14% | 35.00% | 12.86pp | -33.24% | -25.00% | 8.24pp | 1.018 | 5.96% | false |
| concentrated | 32.90% | 50.00% | 17.10pp | -37.96% | -25.00% | 12.96pp | 1.107 | 0.05% | false |

## Account State And Orders

| Portfolio | End Date | Equity | Latest Cash | Positions | Preview Orders | Buys | Sells | Blocked |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2026-06-12 | $407,529 | 27.18% | 14 | 25 | 12 | 13 | 0 |
| concentrated | 2026-06-12 | $737,683 | 0.00% | 4 | 8 | 4 | 4 | 0 |

## Broker Trade Journal

| Portfolio | Round Trips | Win Rate | Avg Return | Avg Holding Days | Profit Factor | Fees |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 1367 | 55.96% | 5.70% | 69.2 | 2.61 | $40,566 |
| concentrated | 326 | 62.27% | 7.10% | 52.2 | 3.89 | $73,838 |

## Governance

- Official metric mode: `broker_ledger_next_close`
- Production target pass: `false`
- Research target pass: `false`
- Generated at: `2026-06-14T02:06:28+00:00`
