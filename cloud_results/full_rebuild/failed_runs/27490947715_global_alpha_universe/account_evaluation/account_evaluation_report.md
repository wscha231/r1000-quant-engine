# Account Evaluation

Official performance evidence uses broker-ledger replay with next-close fills, integer shares, cash, and transaction costs.
Legacy weight-level backtest metrics are retained only as research comparison fields and cannot produce a production SHIP verdict.

## Official Targets

| Portfolio | CAGR | Target | Gap | MaxDD | Target | Gap | Sharpe | Avg Cash | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 21.87% | 35.00% | 13.13pp | -26.37% | -25.00% | 1.37pp | 1.042 | 5.93% | false |
| concentrated | 28.54% | 50.00% | 21.46pp | -42.96% | -25.00% | 17.96pp | 1.002 | 0.05% | false |

## Account State And Orders

| Portfolio | End Date | Equity | Latest Cash | Positions | Preview Orders | Buys | Sells | Blocked |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2026-06-12 | $401,230 | 26.86% | 18 | 33 | 16 | 17 | 0 |
| concentrated | 2026-06-12 | $583,550 | 0.01% | 4 | 8 | 4 | 4 | 0 |

## Broker Trade Journal

| Portfolio | Round Trips | Win Rate | Avg Return | Avg Holding Days | Profit Factor | Fees |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 1697 | 55.98% | 6.15% | 69.6 | 2.82 | $40,873 |
| concentrated | 326 | 59.51% | 6.92% | 53.3 | 3.49 | $63,445 |

## Governance

- Official metric mode: `broker_ledger_next_close`
- Production target pass: `false`
- Research target pass: `false`
- Generated at: `2026-06-14T09:32:41+00:00`
