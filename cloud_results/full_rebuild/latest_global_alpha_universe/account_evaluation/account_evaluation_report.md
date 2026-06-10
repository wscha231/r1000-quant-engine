# Account Evaluation

Official performance evidence uses broker-ledger replay with next-close fills, integer shares, cash, and transaction costs.
Legacy weight-level backtest metrics are retained only as research comparison fields and cannot produce a production SHIP verdict.

## Official Targets

| Portfolio | CAGR | Target | Gap | MaxDD | Target | Gap | Sharpe | Avg Cash | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 20.55% | 30.00% | 9.45pp | -31.82% | -15.00% | 16.82pp | 0.983 | 5.75% | false |
| concentrated | 32.74% | 50.00% | 17.26pp | -39.58% | -18.00% | 21.58pp | 1.089 | 0.05% | false |

## Account State And Orders

| Portfolio | End Date | Equity | Latest Cash | Positions | Preview Orders | Buys | Sells | Blocked |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2026-05-22 | $374,064 | 26.12% | 27 | 42 | 16 | 26 | 0 |
| concentrated | 2026-05-22 | $738,345 | 0.00% | 3 | 6 | 3 | 3 | 0 |

## Broker Trade Journal

| Portfolio | Round Trips | Win Rate | Avg Return | Avg Holding Days | Profit Factor | Fees |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 0 |  |  | 0.0 | 0.00 | $37,912 |
| concentrated | 0 |  |  | 0.0 | 0.00 | $68,766 |

## Governance

- Official metric mode: `broker_ledger_next_close`
- Production target pass: `false`
- Research target pass: `false`
- Generated at: `2026-05-27T13:17:15+00:00`
