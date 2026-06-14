# Account Evaluation

Official performance evidence uses broker-ledger replay with next-close fills, integer shares, cash, and transaction costs.
Legacy weight-level backtest metrics are retained only as research comparison fields and cannot produce a production SHIP verdict.

## Official Targets

| Portfolio | CAGR | Target | Gap | MaxDD | Target | Gap | Sharpe | Avg Cash | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 34.33% | 35.00% | 0.67pp | -25.93% | -25.00% | 0.93pp | 1.271 | 26.79% | false |
| concentrated | 44.57% | 50.00% | 5.43pp | -25.88% | -25.00% | 0.88pp | 1.401 | 42.37% | false |

## Account State And Orders

| Portfolio | End Date | Equity | Latest Cash | Positions | Preview Orders | Buys | Sells | Blocked |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2026-06-12 | $795,359 | 16.09% | 13 | 13 | 8 | 5 | 0 |
| concentrated | 2026-06-12 | $1,332,294 | 6.55% | 5 | 5 | 3 | 2 | 0 |

## Broker Trade Journal

| Portfolio | Round Trips | Win Rate | Avg Return | Avg Holding Days | Profit Factor | Fees |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 1137 | 57.96% | 11.41% | 60.2 | 3.77 | $39,482 |
| concentrated | 398 | 55.78% | 12.30% | 53.4 | 3.91 | $42,132 |

## Governance

- Official metric mode: `broker_ledger_next_close`
- Production target pass: `false`
- Research target pass: `false`
- Generated at: `2026-06-14T16:04:47+00:00`
