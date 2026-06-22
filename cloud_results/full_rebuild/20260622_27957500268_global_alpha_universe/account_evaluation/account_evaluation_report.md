# Account Evaluation

Official performance evidence uses broker-ledger replay with next-close fills, integer shares, cash, and transaction costs.
Legacy weight-level backtest metrics are retained only as research comparison fields and cannot produce a production-promotion verdict.

## Official Targets

Active target type: `interim_operating_gate`. Canonical mission targets are shown separately and remain unresolved until explicit user approval.

| Portfolio | Target Type | CAGR | Active Target | Canonical Target | Gap | MaxDD | Active Target | Canonical Target | Gap | Sharpe | Avg Cash | Pass |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | interim_operating_gate | 34.92% | 30.00% | 35.00% | 0.00pp | -26.05% | -25.00% | -25.00% | 1.05pp | 1.273 | 26.35% | false |
| concentrated | interim_operating_gate | 45.95% | 50.00% | 50.00% | 4.05pp | -24.59% | -28.00% | -25.00% | 0.00pp | 1.434 | 41.32% | false |

## Account State And Orders

| Portfolio | End Date | Equity | Latest Cash | Positions | Preview Orders | Buys | Sells | Blocked |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2026-06-22 | $807,857 | 14.54% | 13 | 13 | 8 | 5 | 0 |
| concentrated | 2026-06-22 | $1,397,820 | 5.51% | 5 | 5 | 3 | 2 | 0 |

## Broker Trade Journal

| Portfolio | Round Trips | Win Rate | Avg Return | Avg Holding Days | Profit Factor | Fees |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 1124 | 56.85% | 10.88% | 60.3 | 3.54 | $36,733 |
| concentrated | 388 | 55.15% | 12.14% | 53.5 | 3.78 | $37,076 |

## Tier-2 Strengthened Gates (IS / Sharpe / OOS-IS ratio / recent MDD / cash)

| Portfolio | IS CAGR | OOS CAGR | OOS/IS | Sharpe | Avg Cash | Recent MDD | Failing | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | :---: |
| main | 19.94% | 82.92% | 4.16x | 1.27 | 26.35% | -23.76% | is_cagr_min, oos_is_cagr_ratio_max | FAIL |
| concentrated | 18.65% | 147.69% | 7.92x | 1.43 | 41.32% | -23.10% | is_cagr_min, oos_is_cagr_ratio_max | FAIL |

## Broker-Ledger Window Gate

| Portfolio | Status | Years | Actual Trading Days | Trading Days Evidence | Data Ready | Start | End | Reasons |
| --- | --- | ---: | ---: | ---: | :---: | --- | --- | --- |
| main | invalid_window | 6.98 | 1753 | 1753 | true | 2019-07-01 | 2026-06-22 | broker_ledger_years_below_7, broker_ledger_trading_days_below_7y |
| concentrated | invalid_window | 6.98 | 1714 | 1714 | true | 2019-07-01 | 2026-06-22 | broker_ledger_years_below_7, broker_ledger_trading_days_below_7y |

## Governance

- Official metric mode: `broker_ledger_next_close`
- Active target type: `interim_operating_gate`
- Target contract status: `unresolved_user_decision_required`
- Canonical mission targets remain Main `35% / -25%` and Concentrated `50% / -25%` until explicit user approval changes them.
- Clean broker-ledger research window: `7.0 years / 1764 trading days`
- Proxy 8Y/10Y evidence is blocked until a PIT-clean historical universe label is present.
- Production target pass (Tier-1: full CAGR/MDD): `false`
- Strengthened pass (Tier-1 AND Tier-2 IS/Sharpe/ratio/cash/recent-MDD): `false`
- Research target pass: `true`
- Generated at: `2026-06-22T16:44:39+00:00`
