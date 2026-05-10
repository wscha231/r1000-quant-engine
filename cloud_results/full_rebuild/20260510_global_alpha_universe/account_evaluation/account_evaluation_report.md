# Account Evaluation

Official performance evidence uses broker-ledger replay with next-close fills, integer shares, cash, and transaction costs.
Legacy weight-level backtest metrics are retained only as research comparison fields.

## Official Targets

| Portfolio | CAGR | Target | Gap | MaxDD | Target | Gap | Sharpe | Avg Cash | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 20.25% | 30.00% | 9.74pp | -32.50% | -15.00% | 17.50pp | 0.965 | 4.97% | false |
| concentrated | 31.31% | 50.00% | 18.69pp | -39.03% | -18.00% | 21.03pp | 1.049 | 0.05% | false |

## Account State And Orders

| Portfolio | End Date | Equity | Latest Cash | Positions | Preview Orders | Buys | Sells | Blocked |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2026-05-08 | $365,016 | 25.61% | 18 | 28 | 15 | 13 | 0 |
| concentrated | 2026-05-08 | $676,654 | 0.01% | 3 | 7 | 4 | 3 | 0 |

## Broker Trade Journal

| Portfolio | Round Trips | Win Rate | Avg Return | Avg Holding Days | Profit Factor | Fees |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 1926 | 54.98% | 4.12% | 70.6 | 2.07 | $39,158 |
| concentrated | 245 | 61.22% | 4.89% | 51.5 | 2.93 | $64,452 |

## Governance

- Official metric mode: `broker_ledger_next_close`
- Production target pass: `false`
- Research target pass: `false`
- Generated at: `2026-05-10T07:09:49+00:00`
