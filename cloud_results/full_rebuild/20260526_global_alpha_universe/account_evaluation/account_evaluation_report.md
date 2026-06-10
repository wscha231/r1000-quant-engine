# Account Evaluation

Official performance evidence uses broker-ledger replay with next-close fills, integer shares, cash, and transaction costs.
Legacy weight-level backtest metrics are retained only as research comparison fields and cannot produce a production SHIP verdict.

## Official Targets

| Portfolio | CAGR | Target | Gap | MaxDD | Target | Gap | Sharpe | Avg Cash | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 20.94% | 30.00% | 9.06pp | -31.86% | -15.00% | 16.86pp | 1.001 | 5.79% | false |
| concentrated | 31.50% | 50.00% | 18.50pp | -39.52% | -18.00% | 21.52pp | 1.056 | 0.05% | false |

## Account State And Orders

| Portfolio | End Date | Equity | Latest Cash | Positions | Preview Orders | Buys | Sells | Blocked |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2026-05-22 | $382,689 | 26.12% | 27 | 42 | 16 | 26 | 0 |
| concentrated | 2026-05-22 | $690,854 | 0.00% | 3 | 6 | 3 | 3 | 0 |

## Broker Trade Journal

| Portfolio | Round Trips | Win Rate | Avg Return | Avg Holding Days | Profit Factor | Fees |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 0 |  |  | 0.0 | 0.00 | $38,376 |
| concentrated | 0 |  |  | 0.0 | 0.00 | $64,330 |

## Governance

- Official metric mode: `broker_ledger_next_close`
- Production target pass: `false`
- Research target pass: `false`
- Generated at: `2026-05-26T22:30:35+00:00`
