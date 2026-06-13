# Account Evaluation

Official performance evidence uses broker-ledger replay with next-close fills, integer shares, cash, and transaction costs.
Legacy weight-level backtest metrics are retained only as research comparison fields and cannot produce a production SHIP verdict.

## Official Targets

| Portfolio | CAGR | Target | Gap | MaxDD | Target | Gap | Sharpe | Avg Cash | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 20.21% | 30.00% | 9.79pp | -33.27% | -15.00% | 18.27pp | 0.947 | 5.75% | false |
| concentrated | 33.20% | 50.00% | 16.80pp | -39.88% | -18.00% | 21.88pp | 1.087 | 0.05% | false |

## Account State And Orders

| Portfolio | End Date | Equity | Latest Cash | Positions | Preview Orders | Buys | Sells | Blocked |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2026-05-29 | $368,019 | 24.33% | 18 | 34 | 17 | 17 | 0 |
| concentrated | 2026-05-29 | $760,476 | 0.00% | 3 | 6 | 3 | 3 | 0 |

## Broker Trade Journal

| Portfolio | Round Trips | Win Rate | Avg Return | Avg Holding Days | Profit Factor | Fees |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 0 |  |  | 0.0 | 0.00 | $39,901 |
| concentrated | 0 |  |  | 0.0 | 0.00 | $71,400 |

## Governance

- Official metric mode: `broker_ledger_next_close`
- Production target pass: `false`
- Research target pass: `false`
- Generated at: `2026-05-30T08:43:14+00:00`
