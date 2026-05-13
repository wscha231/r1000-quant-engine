# Account Evaluation

Official performance evidence uses broker-ledger replay with next-close fills, integer shares, cash, and transaction costs.
Legacy weight-level backtest metrics are retained only as research comparison fields and cannot produce a production SHIP verdict.

## Official Targets

| Portfolio | CAGR | Target | Gap | MaxDD | Target | Gap | Sharpe | Avg Cash | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 21.38% | 30.00% | 8.62pp | -33.19% | -15.00% | 18.19pp | 1.026 | 5.62% | false |
| concentrated | 37.35% | 50.00% | 12.65pp | -37.89% | -18.00% | 19.89pp | 1.278 | 0.04% | false |

## Account State And Orders

| Portfolio | End Date | Equity | Latest Cash | Positions | Preview Orders | Buys | Sells | Blocked |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2026-05-12 | $390,572 | 25.04% | 14 | 24 | 12 | 12 | 0 |
| concentrated | 2026-05-12 | $931,175 | 0.00% | 4 | 8 | 4 | 4 | 0 |

## Broker Trade Journal

| Portfolio | Round Trips | Win Rate | Avg Return | Avg Holding Days | Profit Factor | Fees |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 1525 | 55.41% | 4.03% | 69.6 | 2.08 | $37,667 |
| concentrated | 326 | 62.27% | 6.40% | 54.8 | 3.78 | $81,872 |

## Governance

- Official metric mode: `broker_ledger_next_close`
- Production target pass: `false`
- Research target pass: `true`
- Generated at: `2026-05-13T14:41:41+00:00`
