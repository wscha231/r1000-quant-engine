# Account Evaluation

Official performance evidence uses broker-ledger replay with next-close fills, integer shares, cash, and transaction costs.
Legacy weight-level backtest metrics are retained only as research comparison fields and cannot produce a production SHIP verdict.

## Official Targets

| Portfolio | CAGR | Target | Gap | MaxDD | Target | Gap | Sharpe | Avg Cash | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 22.90% | 30.00% | 7.10pp | -29.95% | -15.00% | 14.95pp | 1.090 | 5.67% | false |
| concentrated | 32.85% | 50.00% | 17.15pp | -37.84% | -18.00% | 19.84pp | 1.133 | 0.05% | false |

## Account State And Orders

| Portfolio | End Date | Equity | Latest Cash | Positions | Preview Orders | Buys | Sells | Blocked |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2026-05-27 | $429,953 | 23.63% | 41 | 45 | 15 | 30 | 0 |
| concentrated | 2026-05-27 | $745,458 | 0.01% | 4 | 8 | 4 | 4 | 0 |

## Broker Trade Journal

| Portfolio | Round Trips | Win Rate | Avg Return | Avg Holding Days | Profit Factor | Fees |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 0 |  |  | 0.0 | 0.00 | $40,441 |
| concentrated | 0 |  |  | 0.0 | 0.00 | $71,873 |

## Governance

- Official metric mode: `broker_ledger_next_close`
- Production target pass: `false`
- Research target pass: `false`
- Generated at: `2026-05-28T17:58:51+00:00`
