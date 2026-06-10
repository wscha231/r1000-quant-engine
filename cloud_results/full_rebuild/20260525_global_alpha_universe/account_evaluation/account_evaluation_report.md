# Account Evaluation

Official performance evidence uses broker-ledger replay with next-close fills, integer shares, cash, and transaction costs.
Legacy weight-level backtest metrics are retained only as research comparison fields and cannot produce a production SHIP verdict.

## Official Targets

| Portfolio | CAGR | Target | Gap | MaxDD | Target | Gap | Sharpe | Avg Cash | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 4.57% | 30.00% | 25.43pp | -28.28% | -15.00% | 13.28pp | 0.331 | 30.99% | false |
| concentrated | 3.77% | 50.00% | 46.23pp | -44.79% | -18.00% | 26.79pp | 0.281 | 11.09% | false |

## Account State And Orders

| Portfolio | End Date | Equity | Latest Cash | Positions | Preview Orders | Buys | Sells | Blocked |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2026-05-22 | $120,776 | 26.17% | 12 | 19 | 8 | 11 | 0 |
| concentrated | 2026-05-22 | $116,932 | 0.06% | 3 | 6 | 3 | 3 | 0 |

## Broker Trade Journal

| Portfolio | Round Trips | Win Rate | Avg Return | Avg Holding Days | Profit Factor | Fees |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 0 |  |  | 0.0 | 0.00 | $7,140 |
| concentrated | 0 |  |  | 0.0 | 0.00 | $8,995 |

## Governance

- Official metric mode: `broker_ledger_next_close`
- Production target pass: `false`
- Research target pass: `false`
- Generated at: `2026-05-25T19:19:43+00:00`
