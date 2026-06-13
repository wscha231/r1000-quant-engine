# Account Evaluation

Official performance evidence uses broker-ledger replay with next-close fills, integer shares, cash, and transaction costs.
Legacy weight-level backtest metrics are retained only as research comparison fields and cannot produce a production SHIP verdict.

## Official Targets

| Portfolio | CAGR | Target | Gap | MaxDD | Target | Gap | Sharpe | Avg Cash | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 19.79% | 35.00% | 15.21pp | -33.25% | -25.00% | 8.25pp | 0.950 | 5.94% | false |
| concentrated | 32.90% | 50.00% | 17.10pp | -37.96% | -25.00% | 12.96pp | 1.107 | 0.05% | false |

## Account State And Orders

| Portfolio | End Date | Equity | Latest Cash | Positions | Preview Orders | Buys | Sells | Blocked |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2026-06-12 | $355,474 | 27.69% | 17 | 33 | 17 | 16 | 0 |
| concentrated | 2026-06-12 | $737,683 | 0.00% | 4 | 8 | 4 | 4 | 0 |

## Broker Trade Journal

| Portfolio | Round Trips | Win Rate | Avg Return | Avg Holding Days | Profit Factor | Fees |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2100 | 53.33% | 4.00% | 72.1 | 1.95 | $38,498 |
| concentrated | 326 | 62.27% | 7.10% | 52.2 | 3.89 | $73,838 |

## Governance

- Official metric mode: `broker_ledger_next_close`
- Production target pass: `false`
- Research target pass: `false`
- Generated at: `2026-06-13T15:37:56+00:00`
