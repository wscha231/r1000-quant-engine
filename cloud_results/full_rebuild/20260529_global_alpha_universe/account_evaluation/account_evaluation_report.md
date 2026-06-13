# Account Evaluation

Official performance evidence uses broker-ledger replay with next-close fills, integer shares, cash, and transaction costs.
Legacy weight-level backtest metrics are retained only as research comparison fields and cannot produce a production SHIP verdict.

## Official Targets

| Portfolio | CAGR | Target | Gap | MaxDD | Target | Gap | Sharpe | Avg Cash | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 23.49% | 30.00% | 6.51pp | -34.80% | -15.00% | 19.80pp | 1.065 | 5.82% | false |
| concentrated | 32.64% | 50.00% | 17.36pp | -37.80% | -18.00% | 19.80pp | 1.117 | 0.04% | false |

## Account State And Orders

| Portfolio | End Date | Equity | Latest Cash | Positions | Preview Orders | Buys | Sells | Blocked |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2026-05-28 | $444,909 | 24.38% | 14 | 25 | 12 | 13 | 0 |
| concentrated | 2026-05-28 | $737,811 | 0.00% | 4 | 8 | 4 | 4 | 0 |

## Broker Trade Journal

| Portfolio | Round Trips | Win Rate | Avg Return | Avg Holding Days | Profit Factor | Fees |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 1571 | 55.63% | 4.60% | 67.9 | 2.23 | $39,839 |
| concentrated | 323 | 60.99% | 7.05% | 52.4 | 3.78 | $73,002 |

## Governance

- Official metric mode: `broker_ledger_next_close`
- Production target pass: `false`
- Research target pass: `false`
- Generated at: `2026-05-29T12:45:02+00:00`
