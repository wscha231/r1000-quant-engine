# Account Evaluation

Official performance evidence uses broker-ledger replay with next-close fills, integer shares, cash, and transaction costs.
Legacy weight-level backtest metrics are retained only as research comparison fields and cannot produce a production SHIP verdict.

## Official Targets

| Portfolio | CAGR | Target | Gap | MaxDD | Target | Gap | Sharpe | Avg Cash | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 20.20% | 30.00% | 9.79pp | -32.02% | -15.00% | 17.02pp | 1.057 | 14.67% | false |
| concentrated | 29.42% | 50.00% | 20.59pp | -32.56% | -18.00% | 14.56pp | 1.078 | 17.93% | false |

## Account State And Orders

| Portfolio | End Date | Equity | Latest Cash | Positions | Preview Orders | Buys | Sells | Blocked |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2026-05-13 | $364,870 | 24.64% | 18 | 32 | 18 | 14 | 0 |
| concentrated | 2026-05-13 | $613,265 | 13.96% | 2 | 6 | 4 | 2 | 0 |

## Broker Trade Journal

| Portfolio | Round Trips | Win Rate | Avg Return | Avg Holding Days | Profit Factor | Fees |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2020 | 53.86% | 3.99% | 66.5 | 2.06 | $34,259 |
| concentrated | 163 | 61.35% | 5.09% | 44.0 | 2.88 | $58,620 |

## Governance

- Official metric mode: `broker_ledger_next_close`
- Production target pass: `false`
- Research target pass: `true`
- Generated at: `2026-05-14T12:05:01+00:00`
