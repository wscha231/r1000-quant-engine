# Account Evaluation

Official performance evidence uses broker-ledger replay with next-close fills, integer shares, cash, and transaction costs.
Legacy weight-level backtest metrics are retained only as research comparison fields and cannot produce a production SHIP verdict.

## Official Targets

| Portfolio | CAGR | Target | Gap | MaxDD | Target | Gap | Sharpe | Avg Cash | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 21.84% | 30.00% | 8.16pp | -28.62% | -15.00% | 13.62pp | 1.056 | 5.55% | false |
| concentrated | 35.76% | 50.00% | 14.24pp | -36.74% | -18.00% | 18.74pp | 1.204 | 0.04% | false |

## Account State And Orders

| Portfolio | End Date | Equity | Latest Cash | Positions | Preview Orders | Buys | Sells | Blocked |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2026-05-08 | $400,191 | 26.15% | 27 | 40 | 16 | 24 | 0 |
| concentrated | 2026-05-08 | $855,012 | 0.00% | 4 | 8 | 4 | 4 | 0 |

## Broker Trade Journal

| Portfolio | Round Trips | Win Rate | Avg Return | Avg Holding Days | Profit Factor | Fees |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 1754 | 57.47% | 5.03% | 69.7 | 2.44 | $37,913 |
| concentrated | 328 | 60.37% | 6.13% | 53.1 | 3.61 | $76,204 |

## Governance

- Official metric mode: `broker_ledger_next_close`
- Production target pass: `false`
- Research target pass: `false`
- Generated at: `2026-05-12T08:12:16+00:00`
