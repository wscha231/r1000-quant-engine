# Account Evaluation

Official performance evidence uses broker-ledger replay with next-close fills, integer shares, cash, and transaction costs.
Legacy weight-level backtest metrics are retained only as research comparison fields and cannot produce a production SHIP verdict.

## Official Targets

| Portfolio | CAGR | Target | Gap | MaxDD | Target | Gap | Sharpe | Avg Cash | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 12.86% | 30.00% | 17.14pp | -27.07% | -15.00% | 12.07pp | 0.635 | 5.65% | false |
| concentrated | 16.89% | 50.00% | 33.11pp | -33.80% | -18.00% | 15.80pp | 0.722 | 0.09% | false |

## Account State And Orders

| Portfolio | End Date | Equity | Latest Cash | Positions | Preview Orders | Buys | Sells | Blocked |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2026-05-15 | $231,829 | 1.82% | 17 | 0 | 0 | 0 | 0 |
| concentrated | 2026-05-15 | $295,768 | 0.24% | 7 | 0 | 0 | 0 | 0 |

## Broker Trade Journal

| Portfolio | Round Trips | Win Rate | Avg Return | Avg Holding Days | Profit Factor | Fees |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 1872 | 56.14% | 3.35% | 68.8 | 1.96 | $32,162 |
| concentrated | 571 | 59.72% | 3.85% | 55.4 | 2.44 | $49,154 |

## Governance

- Official metric mode: `broker_ledger_next_close`
- Production target pass: `false`
- Research target pass: `false`
- Generated at: `2026-05-16T18:49:57+00:00`
