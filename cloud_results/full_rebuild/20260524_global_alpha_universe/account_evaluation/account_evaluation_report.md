# Account Evaluation

Official performance evidence uses broker-ledger replay with next-close fills, integer shares, cash, and transaction costs.
Legacy weight-level backtest metrics are retained only as research comparison fields and cannot produce a production SHIP verdict.

## Official Targets

| Portfolio | CAGR | Target | Gap | MaxDD | Target | Gap | Sharpe | Avg Cash | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 21.45% | 30.00% | 8.55pp | -32.45% | -15.00% | 17.45pp | 1.044 | 5.59% | false |
| concentrated | 36.61% | 50.00% | 13.39pp | -42.58% | -18.00% | 24.58pp | 1.100 | 0.03% | false |

## Account State And Orders

| Portfolio | End Date | Equity | Latest Cash | Positions | Preview Orders | Buys | Sells | Blocked |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2026-05-22 | $387,337 | 24.80% | 14 | 27 | 14 | 13 | 0 |
| concentrated | 2026-05-22 | $879,167 | 0.00% | 2 | 5 | 3 | 2 | 0 |

## Broker Trade Journal

| Portfolio | Round Trips | Win Rate | Avg Return | Avg Holding Days | Profit Factor | Fees |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 1538 | 55.53% | 4.27% | 69.4 | 2.18 | $38,329 |
| concentrated | 162 | 65.43% | 6.55% | 47.9 | 3.72 | $66,691 |

## Governance

- Official metric mode: `broker_ledger_next_close`
- Production target pass: `false`
- Research target pass: `false`
- Generated at: `2026-05-24T18:51:06+00:00`
