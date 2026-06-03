# Account Evaluation

Official performance evidence uses broker-ledger replay with next-close fills, integer shares, cash, and transaction costs.
Legacy weight-level backtest metrics are retained only as research comparison fields and cannot produce a production SHIP verdict.

## Official Targets

| Portfolio | CAGR | Target | Gap | MaxDD | Target | Gap | Sharpe | Avg Cash | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 27.28% | 30.00% | 2.72pp | -38.95% | -20.00% | 18.95pp | 1.031 | 19.27% | false |
| concentrated | 26.87% | 50.00% | 23.13pp | -48.02% | -25.00% | 23.02pp | 0.898 | 29.79% | false |

## Account State And Orders

| Portfolio | End Date | Equity | Latest Cash | Positions | Preview Orders | Buys | Sells | Blocked |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2026-06-01 | $540,526 | 50.77% | 15 | 31 | 17 | 14 | 0 |
| concentrated | 2026-06-01 | $528,526 | 81.49% | 5 | 6 | 3 | 3 | 0 |

## Broker Trade Journal

| Portfolio | Round Trips | Win Rate | Avg Return | Avg Holding Days | Profit Factor | Fees |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 0 |  |  | 0.0 | 0.00 | $33,923 |
| concentrated | 0 |  |  | 0.0 | 0.00 | $28,960 |

## Governance

- Official metric mode: `broker_ledger_next_close`
- Production target pass: `false`
- Research target pass: `false`
- Generated at: `2026-06-03T12:33:50+00:00`
