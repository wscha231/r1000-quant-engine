# Account Evaluation

Official performance evidence uses broker-ledger replay with next-close fills, integer shares, cash, and transaction costs.
Legacy weight-level backtest metrics are retained only as research comparison fields and cannot produce a production SHIP verdict.

## Official Targets

| Portfolio | CAGR | Target | Gap | MaxDD | Target | Gap | Sharpe | Avg Cash | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 18.44% | 30.00% | 11.56pp | -31.93% | -15.00% | 16.93pp | 0.848 | 14.70% | false |
| concentrated | 35.10% | 50.00% | 14.90pp | -22.68% | -18.00% | 4.68pp | 1.300 | 17.90% | false |

## Account State And Orders

| Portfolio | End Date | Equity | Latest Cash | Positions | Preview Orders | Buys | Sells | Blocked |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2026-05-14 | $328,975 | 0.45% | 17 | 1 | 0 | 1 | 0 |
| concentrated | 2026-05-14 | $830,606 | 0.23% | 5 | 1 | 1 | 0 | 1 |

## Broker Trade Journal

| Portfolio | Round Trips | Win Rate | Avg Return | Avg Holding Days | Profit Factor | Fees |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2050 | 53.32% | 4.15% | 67.1 | 2.07 | $34,566 |
| concentrated | 413 | 63.44% | 6.65% | 55.5 | 3.61 | $69,041 |

## Governance

- Official metric mode: `broker_ledger_next_close`
- Production target pass: `false`
- Research target pass: `true`
- Generated at: `2026-05-14T21:09:12+00:00`
