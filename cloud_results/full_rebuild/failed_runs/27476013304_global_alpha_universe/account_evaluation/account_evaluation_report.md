# Account Evaluation

Official performance evidence uses broker-ledger replay with next-close fills, integer shares, cash, and transaction costs.
Legacy weight-level backtest metrics are retained only as research comparison fields and cannot produce a production SHIP verdict.

## Official Targets

| Portfolio | CAGR | Target | Gap | MaxDD | Target | Gap | Sharpe | Avg Cash | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 22.40% | 35.00% | 12.60pp | -31.66% | -25.00% | 6.66pp | 1.045 | 5.98% | false |
| concentrated | 30.79% | 50.00% | 19.21pp | -37.90% | -25.00% | 12.90pp | 1.063 | 0.05% | false |

## Account State And Orders

| Portfolio | End Date | Equity | Latest Cash | Positions | Preview Orders | Buys | Sells | Blocked |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2026-06-12 | $413,816 | 26.73% | 17 | 32 | 15 | 17 | 0 |
| concentrated | 2026-06-12 | $659,256 | 0.00% | 4 | 8 | 4 | 4 | 0 |

## Broker Trade Journal

| Portfolio | Round Trips | Win Rate | Avg Return | Avg Holding Days | Profit Factor | Fees |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 1696 | 53.95% | 5.63% | 67.9 | 2.47 | $40,518 |
| concentrated | 328 | 60.98% | 6.60% | 51.9 | 3.53 | $68,246 |

## Governance

- Official metric mode: `broker_ledger_next_close`
- Production target pass: `false`
- Research target pass: `false`
- Generated at: `2026-06-13T22:12:01+00:00`
