# Account Evaluation

Official performance evidence uses broker-ledger replay with next-close fills, integer shares, cash, and transaction costs.
Legacy weight-level backtest metrics are retained only as research comparison fields and cannot produce a production SHIP verdict.

## Official Targets

| Portfolio | CAGR | Target | Gap | MaxDD | Target | Gap | Sharpe | Avg Cash | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 33.46% | 35.00% | 1.54pp | -26.23% | -25.00% | 1.23pp | 1.251 | 27.25% | false |
| concentrated | 40.61% | 50.00% | 9.39pp | -29.94% | -25.00% | 4.94pp | 1.325 | 41.93% | false |

## Account State And Orders

| Portfolio | End Date | Equity | Latest Cash | Positions | Preview Orders | Buys | Sells | Blocked |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2026-06-05 | $755,371 | 17.18% | 13 | 11 | 6 | 5 | 0 |
| concentrated | 2026-06-05 | $1,088,909 | 7.19% | 5 | 5 | 3 | 2 | 0 |

## Broker Trade Journal

| Portfolio | Round Trips | Win Rate | Avg Return | Avg Holding Days | Profit Factor | Fees |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 0 |  |  | 0.0 | 0.00 | $39,147 |
| concentrated | 0 |  |  | 0.0 | 0.00 | $38,980 |

## Governance

- Official metric mode: `broker_ledger_next_close`
- Production target pass: `false`
- Research target pass: `false`
- Generated at: `2026-06-07T12:35:11+00:00`
