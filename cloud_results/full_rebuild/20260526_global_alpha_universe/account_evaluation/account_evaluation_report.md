# Account Evaluation

Official performance evidence uses broker-ledger replay with next-close fills, integer shares, cash, and transaction costs.
Legacy weight-level backtest metrics are retained only as research comparison fields and cannot produce a production SHIP verdict.

## Official Targets

| Portfolio | CAGR | Target | Gap | MaxDD | Target | Gap | Sharpe | Avg Cash | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 22.13% | 30.00% | 7.87pp | -37.42% | -15.00% | 22.42pp | 1.018 | 5.53% | false |
| concentrated | 33.43% | 50.00% | 16.57pp | -37.89% | -18.00% | 19.89pp | 1.153 | 0.04% | false |

## Account State And Orders

| Portfolio | End Date | Equity | Latest Cash | Positions | Preview Orders | Buys | Sells | Blocked |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2026-05-22 | $409,932 | 25.79% | 14 | 27 | 14 | 13 | 0 |
| concentrated | 2026-05-22 | $765,877 | 0.00% | 4 | 8 | 4 | 4 | 0 |

## Broker Trade Journal

| Portfolio | Round Trips | Win Rate | Avg Return | Avg Holding Days | Profit Factor | Fees |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 0 |  |  | 0.0 | 0.00 | $39,492 |
| concentrated | 0 |  |  | 0.0 | 0.00 | $74,658 |

## Governance

- Official metric mode: `broker_ledger_next_close`
- Production target pass: `false`
- Research target pass: `false`
- Generated at: `2026-05-26T06:20:20+00:00`
