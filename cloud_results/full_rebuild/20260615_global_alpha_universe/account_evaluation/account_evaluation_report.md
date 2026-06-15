# Account Evaluation

Official performance evidence uses broker-ledger replay with next-close fills, integer shares, cash, and transaction costs.
Legacy weight-level backtest metrics are retained only as research comparison fields and cannot produce a production SHIP verdict.

## Official Targets

| Portfolio | CAGR | Target | Gap | MaxDD | Target | Gap | Sharpe | Avg Cash | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 35.20% | 35.00% | 0.00pp | -24.49% | -25.00% | 0.00pp | 1.305 | 26.58% | true |
| concentrated | 44.43% | 50.00% | 5.57pp | -25.92% | -25.00% | 0.92pp | 1.402 | 42.57% | false |

## Account State And Orders

| Portfolio | End Date | Equity | Latest Cash | Positions | Preview Orders | Buys | Sells | Blocked |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2026-06-12 | $832,259 | 15.81% | 13 | 13 | 8 | 5 | 0 |
| concentrated | 2026-06-12 | $1,323,438 | 6.55% | 5 | 5 | 3 | 2 | 0 |

## Broker Trade Journal

| Portfolio | Round Trips | Win Rate | Avg Return | Avg Holding Days | Profit Factor | Fees |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 1138 | 58.79% | 11.43% | 59.9 | 3.82 | $41,789 |
| concentrated | 397 | 55.67% | 12.26% | 53.7 | 3.90 | $42,817 |

## Tier-2 Strengthened Gates (IS / Sharpe / OOS-IS ratio / recent MDD / cash)

| Portfolio | IS CAGR | OOS CAGR | OOS/IS | Sharpe | Avg Cash | Recent MDD | Failing | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | :---: |
| main | 22.90% | 74.53% | 3.25x | 1.31 | 26.58% | -23.80% | is_cagr_min, oos_is_cagr_ratio_max | FAIL |
| concentrated | 22.41% | 123.26% | 5.50x | 1.40 | 42.57% | -23.03% | is_cagr_min, oos_is_cagr_ratio_max | FAIL |

## Governance

- Official metric mode: `broker_ledger_next_close`
- Production target pass (Tier-1: full CAGR/MDD): `false`
- Strengthened pass (Tier-1 AND Tier-2 IS/Sharpe/ratio/cash/recent-MDD): `false`
- Research target pass: `false`
- Generated at: `2026-06-15T03:13:45+00:00`
