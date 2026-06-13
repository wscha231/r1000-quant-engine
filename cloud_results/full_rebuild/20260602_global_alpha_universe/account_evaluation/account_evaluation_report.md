# Account Evaluation

Official performance evidence uses broker-ledger replay with next-close fills, integer shares, cash, and transaction costs.
Legacy weight-level backtest metrics are retained only as research comparison fields and cannot produce a production SHIP verdict.

## Official Targets

| Portfolio | CAGR | Target | Gap | MaxDD | Target | Gap | Sharpe | Avg Cash | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 35.21% | 30.00% | 0.00pp | -41.43% | -20.00% | 21.43pp | 1.133 | 9.91% | false |
| concentrated | 25.73% | 50.00% | 24.27pp | -62.51% | -25.00% | 37.51pp | 0.783 | 10.11% | false |

## Account State And Orders

| Portfolio | End Date | Equity | Latest Cash | Positions | Preview Orders | Buys | Sells | Blocked |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2026-06-01 | $825,138 | 14.39% | 15 | 32 | 18 | 14 | 0 |
| concentrated | 2026-06-01 | $496,043 | 15.51% | 5 | 6 | 2 | 4 | 0 |

## Broker Trade Journal

| Portfolio | Round Trips | Win Rate | Avg Return | Avg Holding Days | Profit Factor | Fees |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 0 |  |  | 0.0 | 0.00 | $45,887 |
| concentrated | 0 |  |  | 0.0 | 0.00 | $30,731 |

## Governance

- Official metric mode: `broker_ledger_next_close`
- Production target pass: `false`
- Research target pass: `false`
- Generated at: `2026-06-02T06:53:25+00:00`
