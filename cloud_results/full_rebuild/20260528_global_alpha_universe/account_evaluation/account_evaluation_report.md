# Account Evaluation

Official performance evidence uses broker-ledger replay with next-close fills, integer shares, cash, and transaction costs.
Legacy weight-level backtest metrics are retained only as research comparison fields and cannot produce a production SHIP verdict.

## Official Targets

| Portfolio | CAGR | Target | Gap | MaxDD | Target | Gap | Sharpe | Avg Cash | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 24.45% | 30.00% | 5.55pp | -29.53% | -15.00% | 14.53pp | 1.141 | 5.76% | false |
| concentrated | 34.95% | 50.00% | 15.05pp | -39.95% | -18.00% | 21.95pp | 1.134 | 0.04% | false |

## Account State And Orders

| Portfolio | End Date | Equity | Latest Cash | Positions | Preview Orders | Buys | Sells | Blocked |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2026-05-27 | $469,594 | 24.60% | 41 | 45 | 16 | 29 | 0 |
| concentrated | 2026-05-27 | $832,823 | 0.00% | 3 | 6 | 3 | 3 | 0 |

## Broker Trade Journal

| Portfolio | Round Trips | Win Rate | Avg Return | Avg Holding Days | Profit Factor | Fees |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 0 |  |  | 0.0 | 0.00 | $41,126 |
| concentrated | 0 |  |  | 0.0 | 0.00 | $74,467 |

## Governance

- Official metric mode: `broker_ledger_next_close`
- Production target pass: `false`
- Research target pass: `false`
- Generated at: `2026-05-28T14:02:11+00:00`
