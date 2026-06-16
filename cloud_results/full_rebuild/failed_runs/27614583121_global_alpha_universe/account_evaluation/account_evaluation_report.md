# Account Evaluation

Official performance evidence uses broker-ledger replay with next-close fills, integer shares, cash, and transaction costs.
Legacy weight-level backtest metrics are retained only as research comparison fields and cannot produce a production SHIP verdict.

## Official Targets

Active target type: `interim_operating_gate`. Canonical mission targets are shown separately and remain unresolved until explicit user approval.

| Portfolio | Target Type | CAGR | Active Target | Canonical Target | Gap | MaxDD | Active Target | Canonical Target | Gap | Sharpe | Avg Cash | Pass |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | interim_operating_gate | 35.01% | 30.00% | 35.00% | 0.00pp | -26.05% | -25.00% | -25.00% | 1.05pp | 1.291 | 26.67% | false |
| concentrated | interim_operating_gate | 45.00% | 50.00% | 50.00% | 5.00pp | -25.82% | -28.00% | -25.00% | 0.00pp | 1.411 | 42.29% | false |

## Account State And Orders

| Portfolio | End Date | Equity | Latest Cash | Positions | Preview Orders | Buys | Sells | Blocked |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2026-06-15 | $825,836 | 14.20% | 13 | 8 | 4 | 4 | 0 |
| concentrated | 2026-06-15 | $1,364,627 | 0.01% | 5 | 4 | 2 | 2 | 0 |

## Broker Trade Journal

| Portfolio | Round Trips | Win Rate | Avg Return | Avg Holding Days | Profit Factor | Fees |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 1138 | 58.44% | 11.56% | 60.1 | 3.84 | $40,994 |
| concentrated | 396 | 56.31% | 12.61% | 53.4 | 4.01 | $42,751 |

## Tier-2 Strengthened Gates (IS / Sharpe / OOS-IS ratio / recent MDD / cash)

| Portfolio | IS CAGR | OOS CAGR | OOS/IS | Sharpe | Avg Cash | Recent MDD | Failing | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | :---: |
| main | 22.36% | 75.33% | 3.37x | 1.29 | 26.67% | -23.73% | is_cagr_min, oos_is_cagr_ratio_max | FAIL |
| concentrated | 21.65% | 129.63% | 5.99x | 1.41 | 42.29% | -23.14% | is_cagr_min, oos_is_cagr_ratio_max | FAIL |

## Broker-Ledger Window Gate

| Portfolio | Status | Years | Actual Trading Days | Trading Days Evidence | Data Ready | Start | End | Reasons |
| --- | --- | ---: | ---: | ---: | :---: | --- | --- | --- |
| main | invalid_window | 7.03 | 1769 | 1769 | false | 2019-06-03 | 2026-06-15 | broker_ledger_years_below_8, broker_ledger_trading_days_below_8y, data_readiness_not_ready_for_policy_replay |
| concentrated | invalid_window | 7.03 | 1750 | 1750 | false | 2019-06-03 | 2026-06-15 | broker_ledger_years_below_8, broker_ledger_trading_days_below_8y, data_readiness_not_ready_for_policy_replay |

## Governance

- Official metric mode: `broker_ledger_next_close`
- Active target type: `interim_operating_gate`
- Target contract status: `unresolved_user_decision_required`
- Canonical mission targets remain Main `35% / -25%` and Concentrated `50% / -25%` until explicit user approval changes them.
- Minimum official broker-ledger window: `8.0 years / 2016 trading days`
- Production target pass (Tier-1: full CAGR/MDD): `false`
- Strengthened pass (Tier-1 AND Tier-2 IS/Sharpe/ratio/cash/recent-MDD): `false`
- Research target pass: `true`
- Generated at: `2026-06-16T15:49:43+00:00`
