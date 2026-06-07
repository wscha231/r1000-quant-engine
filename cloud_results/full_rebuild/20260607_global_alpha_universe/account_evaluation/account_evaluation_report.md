# Account Evaluation

Official performance evidence uses broker-ledger replay with next-close fills, integer shares, cash, and transaction costs.
Legacy weight-level backtest metrics are retained only as research comparison fields and cannot produce a production SHIP verdict.

## Official Targets

| Portfolio | CAGR | Target | Gap | MaxDD | Target | Gap | Sharpe | Avg Cash | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 32.38% | 35.00% | 2.62pp | -28.45% | -25.00% | 3.45pp | 1.183 | 23.36% | false |
| concentrated | 37.34% | 50.00% | 12.66pp | -31.72% | -25.00% | 6.72pp | 1.271 | 44.25% | false |

## Account State And Orders

| Portfolio | End Date | Equity | Latest Cash | Positions | Preview Orders | Buys | Sells | Blocked |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2026-06-05 | $713,553 | 6.49% | 15 | 13 | 8 | 5 | 0 |
| concentrated | 2026-06-05 | $923,354 | 11.88% | 5 | 5 | 3 | 2 | 0 |

## Broker Trade Journal

| Portfolio | Round Trips | Win Rate | Avg Return | Avg Holding Days | Profit Factor | Fees |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 0 |  |  | 0.0 | 0.00 | $40,612 |
| concentrated | 0 |  |  | 0.0 | 0.00 | $35,080 |

## Governance

- Official metric mode: `broker_ledger_next_close`
- Production target pass: `false`
- Research target pass: `false`
- Generated at: `2026-06-07T02:36:58+00:00`
