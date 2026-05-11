# Account Evaluation

Official performance evidence uses broker-ledger replay with next-close fills, integer shares, cash, and transaction costs.
Legacy weight-level backtest metrics are retained only as research comparison fields and cannot produce a production SHIP verdict.

## Official Targets

| Portfolio | CAGR | Target | Gap | MaxDD | Target | Gap | Sharpe | Avg Cash | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 21.09% | 30.00% | 8.91pp | -31.69% | -15.00% | 16.69pp | 1.003 | 5.32% | false |
| concentrated | 31.31% | 50.00% | 18.69pp | -39.23% | -18.00% | 21.23pp | 1.051 | 0.04% | false |

## Account State And Orders

| Portfolio | End Date | Equity | Latest Cash | Positions | Preview Orders | Buys | Sells | Blocked |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2026-05-08 | $383,222 | 26.28% | 28 | 41 | 16 | 25 | 0 |
| concentrated | 2026-05-08 | $676,612 | 0.01% | 3 | 7 | 4 | 3 | 0 |

## Broker Trade Journal

| Portfolio | Round Trips | Win Rate | Avg Return | Avg Holding Days | Profit Factor | Fees |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 1873 | 55.26% | 4.42% | 67.4 | 2.27 | $39,505 |
| concentrated | 244 | 62.30% | 5.28% | 52.0 | 3.11 | $64,548 |

## Governance

- Official metric mode: `broker_ledger_next_close`
- Production target pass: `false`
- Research target pass: `false`
- Generated at: `2026-05-11T12:03:33+00:00`
