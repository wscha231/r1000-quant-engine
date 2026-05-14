# Account Evaluation

Official performance evidence uses broker-ledger replay with next-close fills, integer shares, cash, and transaction costs.
Legacy weight-level backtest metrics are retained only as research comparison fields and cannot produce a production SHIP verdict.

## Official Targets

| Portfolio | CAGR | Target | Gap | MaxDD | Target | Gap | Sharpe | Avg Cash | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 23.10% | 30.00% | 6.90pp | -29.98% | -15.00% | 14.98pp | 1.090 | 5.62% | false |
| concentrated | 33.00% | 50.00% | 17.00pp | -41.82% | -18.00% | 23.82pp | 1.094 | 0.05% | false |

## Account State And Orders

| Portfolio | End Date | Equity | Latest Cash | Positions | Preview Orders | Buys | Sells | Blocked |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2026-05-13 | $431,232 | 24.42% | 18 | 33 | 16 | 17 | 0 |
| concentrated | 2026-05-13 | $743,083 | 0.00% | 3 | 6 | 3 | 3 | 0 |

## Broker Trade Journal

| Portfolio | Round Trips | Win Rate | Avg Return | Avg Holding Days | Profit Factor | Fees |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 1970 | 52.44% | 3.96% | 68.3 | 2.00 | $39,076 |
| concentrated | 243 | 65.02% | 6.00% | 50.5 | 3.64 | $69,818 |

## Governance

- Official metric mode: `broker_ledger_next_close`
- Production target pass: `false`
- Research target pass: `true`
- Generated at: `2026-05-14T07:53:43+00:00`
