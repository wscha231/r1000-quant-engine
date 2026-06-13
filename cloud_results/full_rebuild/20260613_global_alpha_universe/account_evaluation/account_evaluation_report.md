# Account Evaluation

Official performance evidence uses broker-ledger replay with next-close fills, integer shares, cash, and transaction costs.
Legacy weight-level backtest metrics are retained only as research comparison fields and cannot produce a production SHIP verdict.

## Official Targets

| Portfolio | CAGR | Target | Gap | MaxDD | Target | Gap | Sharpe | Avg Cash | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 34.51% | 35.00% | 0.49pp | -26.01% | -25.00% | 1.01pp | 1.275 | 26.61% | false |
| concentrated | 44.86% | 50.00% | 5.14pp | -25.83% | -25.00% | 0.83pp | 1.406 | 42.31% | false |

## Account State And Orders

| Portfolio | End Date | Equity | Latest Cash | Positions | Preview Orders | Buys | Sells | Blocked |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2026-06-12 | $802,518 | 16.07% | 13 | 13 | 8 | 5 | 0 |
| concentrated | 2026-06-12 | $1,351,363 | 6.60% | 5 | 5 | 3 | 2 | 0 |

## Broker Trade Journal

| Portfolio | Round Trips | Win Rate | Avg Return | Avg Holding Days | Profit Factor | Fees |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 0 |  |  | 0.0 | 0.00 | $40,215 |
| concentrated | 0 |  |  | 0.0 | 0.00 | $42,609 |

## Governance

- Official metric mode: `broker_ledger_next_close`
- Production target pass: `false`
- Research target pass: `false`
- Generated at: `2026-06-13T09:06:55+00:00`
