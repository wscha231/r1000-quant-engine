# Account Evaluation

Official performance evidence uses broker-ledger replay with next-close fills, integer shares, cash, and transaction costs.
Legacy weight-level backtest metrics are retained only as research comparison fields and cannot produce a production SHIP verdict.

## Official Targets

| Portfolio | CAGR | Target | Gap | MaxDD | Target | Gap | Sharpe | Avg Cash | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 32.69% | 35.00% | 2.31pp | -28.45% | -25.00% | 3.45pp | 1.192 | 23.35% | false |
| concentrated | 38.66% | 50.00% | 11.34pp | -27.26% | -25.00% | 2.26pp | 1.305 | 44.36% | false |

## Account State And Orders

| Portfolio | End Date | Equity | Latest Cash | Positions | Preview Orders | Buys | Sells | Blocked |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2026-06-05 | $725,453 | 6.46% | 15 | 13 | 8 | 5 | 0 |
| concentrated | 2026-06-05 | $987,390 | 11.73% | 5 | 5 | 3 | 2 | 0 |

## Broker Trade Journal

| Portfolio | Round Trips | Win Rate | Avg Return | Avg Holding Days | Profit Factor | Fees |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 0 |  |  | 0.0 | 0.00 | $41,328 |
| concentrated | 0 |  |  | 0.0 | 0.00 | $36,466 |

## Governance

- Official metric mode: `broker_ledger_next_close`
- Production target pass: `false`
- Research target pass: `false`
- Generated at: `2026-06-06T14:04:54+00:00`
