# Account Evaluation

Official performance evidence uses broker-ledger replay with next-close fills, integer shares, cash, and transaction costs.
Legacy weight-level backtest metrics are retained only as research comparison fields.

## Official Targets

| Portfolio | CAGR | Target | Gap | MaxDD | Target | Gap | Sharpe | Avg Cash | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 18.39% | 30.00% | 11.61pp | -33.75% | -15.00% | 18.75pp | 0.906 | 4.16% | false |
| concentrated | 27.07% | 50.00% | 22.93pp | -39.18% | -18.00% | 21.18pp | 0.965 | 0.03% | false |

## Account State And Orders

| Portfolio | End Date | Equity | Latest Cash | Positions | Preview Orders | Buys | Sells | Blocked |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2026-05-08 | $451,929 | 25.77% | 34 | 44 | 17 | 27 | 0 |
| concentrated | 2026-05-08 | $850,362 | 0.01% | 3 | 8 | 5 | 3 | 0 |

## Broker Trade Journal

| Portfolio | Round Trips | Win Rate | Avg Return | Avg Holding Days | Profit Factor | Fees |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2398 | 55.00% | 3.86% | 71.0 | 2.03 | $53,805 |
| concentrated | 314 | 63.69% | 5.17% | 59.8 | 3.21 | $84,828 |

## Governance

- Official metric mode: `broker_ledger_next_close`
- Production target pass: `false`
- Research target pass: `false`
- Generated at: `2026-05-11T07:51:40+00:00`
