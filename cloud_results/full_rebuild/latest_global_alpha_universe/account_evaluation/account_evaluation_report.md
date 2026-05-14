# Account Evaluation

Official performance evidence uses broker-ledger replay with next-close fills, integer shares, cash, and transaction costs.
Legacy weight-level backtest metrics are retained only as research comparison fields and cannot produce a production SHIP verdict.

## Official Targets

| Portfolio | CAGR | Target | Gap | MaxDD | Target | Gap | Sharpe | Avg Cash | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 19.85% | 30.00% | 10.15pp | -32.13% | -15.00% | 17.13pp | 0.916 | 14.68% | false |
| concentrated | 32.65% | 50.00% | 17.35pp | -28.85% | -18.00% | 10.85pp | 1.071 | 17.90% | false |

## Account State And Orders

| Portfolio | End Date | Equity | Latest Cash | Positions | Preview Orders | Buys | Sells | Blocked |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2026-05-13 | $357,442 | 0.77% | 17 | 0 | 0 | 0 | 0 |
| concentrated | 2026-05-13 | $729,430 | 13.96% | 2 | 5 | 3 | 2 | 0 |

## Broker Trade Journal

| Portfolio | Round Trips | Win Rate | Avg Return | Avg Holding Days | Profit Factor | Fees |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2039 | 53.85% | 4.19% | 68.1 | 2.09 | $33,910 |
| concentrated | 163 | 65.03% | 6.01% | 45.7 | 3.46 | $64,915 |

## Governance

- Official metric mode: `broker_ledger_next_close`
- Production target pass: `false`
- Research target pass: `true`
- Generated at: `2026-05-14T16:26:55+00:00`
