# Account Evaluation

Official performance evidence uses broker-ledger replay with next-close fills, integer shares, cash, and transaction costs.
Legacy weight-level backtest metrics are retained only as research comparison fields.

## Official Targets

| Portfolio | CAGR | Target | Gap | MaxDD | Target | Gap | Sharpe | Avg Cash | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 19.72% | 30.00% | 10.28pp | -34.47% | -15.00% | 19.47pp | 0.962 | 5.37% | false |
| concentrated | 36.42% | 50.00% | 13.58pp | -37.38% | -18.00% | 19.38pp | 1.183 | 0.04% | false |

## Account State And Orders

| Portfolio | End Date | Equity | Latest Cash | Positions | Preview Orders | Buys | Sells | Blocked |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2026-05-08 | $353,738 | 25.60% | 28 | 42 | 17 | 25 | 0 |
| concentrated | 2026-05-08 | $884,837 | 0.01% | 3 | 8 | 5 | 3 | 0 |

## Broker Trade Journal

| Portfolio | Round Trips | Win Rate | Avg Return | Avg Holding Days | Profit Factor | Fees |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 1890 | 55.34% | 4.11% | 69.3 | 2.11 | $37,052 |
| concentrated | 246 | 67.48% | 6.33% | 52.3 | 3.97 | $78,662 |

## Governance

- Official metric mode: `broker_ledger_next_close`
- Production target pass: `false`
- Research target pass: `false`
- Generated at: `2026-05-09T11:10:24+00:00`
