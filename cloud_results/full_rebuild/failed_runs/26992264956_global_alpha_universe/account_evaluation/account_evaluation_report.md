# Account Evaluation

Official performance evidence uses broker-ledger replay with next-close fills, integer shares, cash, and transaction costs.
Legacy weight-level backtest metrics are retained only as research comparison fields and cannot produce a production SHIP verdict.

## Official Targets

| Portfolio | CAGR | Target | Gap | MaxDD | Target | Gap | Sharpe | Avg Cash | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 31.36% | 30.00% | 0.00pp | -37.45% | -25.00% | 12.45pp | 1.136 | 19.66% | false |
| concentrated | 39.79% | 45.00% | 5.21pp | -35.20% | -25.00% | 10.20pp | 1.185 | 31.97% | false |

## Account State And Orders

| Portfolio | End Date | Equity | Latest Cash | Positions | Preview Orders | Buys | Sells | Blocked |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2026-06-04 | $675,441 | 5.94% | 15 | 14 | 8 | 6 | 0 |
| concentrated | 2026-06-04 | $1,044,244 | 2.51% | 5 | 5 | 3 | 2 | 0 |

## Broker Trade Journal

| Portfolio | Round Trips | Win Rate | Avg Return | Avg Holding Days | Profit Factor | Fees |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 0 |  |  | 0.0 | 0.00 | $36,903 |
| concentrated | 0 |  |  | 0.0 | 0.00 | $38,852 |

## Governance

- Official metric mode: `broker_ledger_next_close`
- Production target pass: `false`
- Research target pass: `false`
- Generated at: `2026-06-05T06:27:47+00:00`
