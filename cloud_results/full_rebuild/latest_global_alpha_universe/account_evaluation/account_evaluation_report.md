# Account Evaluation

Official performance evidence uses broker-ledger replay with next-close fills, integer shares, cash, and transaction costs.
Legacy weight-level backtest metrics are retained only as research comparison fields and cannot produce a production SHIP verdict.

## Official Targets

| Portfolio | CAGR | Target | Gap | MaxDD | Target | Gap | Sharpe | Avg Cash | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 20.35% | 30.00% | 9.65pp | -33.45% | -15.00% | 18.45pp | 0.991 | 5.66% | false |
| concentrated | 36.41% | 50.00% | 13.59pp | -38.45% | -18.00% | 20.45pp | 1.186 | 0.04% | false |

## Account State And Orders

| Portfolio | End Date | Equity | Latest Cash | Positions | Preview Orders | Buys | Sells | Blocked |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2026-05-12 | $367,747 | 26.03% | 41 | 45 | 17 | 28 | 0 |
| concentrated | 2026-05-12 | $887,470 | 0.01% | 3 | 6 | 3 | 3 | 0 |

## Broker Trade Journal

| Portfolio | Round Trips | Win Rate | Avg Return | Avg Holding Days | Profit Factor | Fees |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2002 | 55.69% | 3.88% | 69.8 | 2.00 | $38,384 |
| concentrated | 244 | 62.70% | 6.13% | 55.0 | 3.55 | $73,729 |

## Governance

- Official metric mode: `broker_ledger_next_close`
- Production target pass: `false`
- Research target pass: `true`
- Generated at: `2026-05-12T23:25:46+00:00`
