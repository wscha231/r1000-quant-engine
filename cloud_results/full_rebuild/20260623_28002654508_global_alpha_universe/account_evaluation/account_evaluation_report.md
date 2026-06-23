# Account Evaluation

Official performance evidence uses broker-ledger replay with next-close fills, integer shares, cash, and transaction costs.
Legacy weight-level backtest metrics are retained only as research comparison fields and cannot produce a production-promotion verdict.

## Official Targets

Active target type: `interim_operating_gate`. Canonical mission targets are shown separately and remain unresolved until explicit user approval.

| Portfolio | Target Type | CAGR | Active Target | Canonical Target | Gap | MaxDD | Active Target | Canonical Target | Gap | Sharpe | Avg Cash | Pass |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | interim_operating_gate | 35.02% | 30.00% | 35.00% | 0.00pp | -26.03% | -25.00% | -25.00% | 1.03pp | 1.276 | 26.36% | false |
| concentrated | interim_operating_gate | 45.96% | 50.00% | 50.00% | 4.04pp | -24.60% | -28.00% | -25.00% | 0.00pp | 1.434 | 41.33% | false |

## Account State And Orders

| Portfolio | End Date | Equity | Latest Cash | Positions | Preview Orders | Buys | Sells | Blocked |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2026-06-22 | $812,322 | 14.63% | 13 | 12 | 7 | 5 | 0 |
| concentrated | 2026-06-22 | $1,398,681 | 5.54% | 5 | 5 | 3 | 2 | 0 |

## Broker Trade Journal

| Portfolio | Round Trips | Win Rate | Avg Return | Avg Holding Days | Profit Factor | Fees |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 1122 | 56.95% | 10.96% | 60.5 | 3.55 | $36,840 |
| concentrated | 387 | 55.04% | 12.11% | 53.5 | 3.77 | $37,072 |

## Tier-2 Strengthened Gates (IS / Sharpe / OOS-IS ratio / recent MDD / cash)

| Portfolio | IS CAGR | OOS CAGR | OOS/IS | Sharpe | Avg Cash | Recent MDD | Failing | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | :---: |
| main | 20.07% | 82.90% | 4.13x | 1.28 | 26.36% | -23.81% | is_cagr_min, oos_is_cagr_ratio_max | FAIL |
| concentrated | 18.64% | 147.80% | 7.93x | 1.43 | 41.33% | -23.03% | is_cagr_min, oos_is_cagr_ratio_max | FAIL |

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
- Generated at: `2026-06-23T08:19:02+00:00`
