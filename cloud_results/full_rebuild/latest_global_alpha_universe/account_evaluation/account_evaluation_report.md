# Account Evaluation

Official performance evidence uses broker-ledger replay with next-close fills, integer shares, cash, and transaction costs.
Legacy weight-level backtest metrics are retained only as research comparison fields and cannot produce a production-promotion verdict.

## Official Targets

Active target type: `interim_operating_gate`. Canonical mission targets are shown separately and remain unresolved until explicit user approval.

| Portfolio | Target Type | CAGR | Active Target | Canonical Target | Gap | MaxDD | Active Target | Canonical Target | Gap | Sharpe | Avg Cash | Pass |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | interim_operating_gate | 34.68% | 30.00% | 35.00% | 0.00pp | -26.05% | -25.00% | -25.00% | 1.05pp | 1.269 | 26.66% | false |
| concentrated | interim_operating_gate | 44.66% | 50.00% | 50.00% | 5.34pp | -25.86% | -28.00% | -25.00% | 0.00pp | 1.394 | 42.48% | false |

## Account State And Orders

| Portfolio | End Date | Equity | Latest Cash | Positions | Preview Orders | Buys | Sells | Blocked |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2026-06-18 | $795,558 | 14.92% | 13 | 12 | 7 | 5 | 0 |
| concentrated | 2026-06-18 | $1,308,628 | 5.71% | 5 | 5 | 3 | 2 | 0 |

## Broker Trade Journal

| Portfolio | Round Trips | Win Rate | Avg Return | Avg Holding Days | Profit Factor | Fees |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 1124 | 57.12% | 10.99% | 60.3 | 3.59 | $37,511 |
| concentrated | 392 | 54.59% | 11.96% | 53.1 | 3.76 | $36,616 |

## Tier-2 Strengthened Gates (IS / Sharpe / OOS-IS ratio / recent MDD / cash)

| Portfolio | IS CAGR | OOS CAGR | OOS/IS | Sharpe | Avg Cash | Recent MDD | Failing | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | :---: |
| main | 20.91% | 78.40% | 3.75x | 1.27 | 26.66% | -24.28% | is_cagr_min, oos_is_cagr_ratio_max | FAIL |
| concentrated | 19.11% | 138.35% | 7.24x | 1.39 | 42.48% | -23.23% | is_cagr_min, oos_is_cagr_ratio_max, sharpe_min | FAIL |

## Broker-Ledger Window Gate

| Portfolio | Status | Years | Actual Trading Days | Trading Days Evidence | Data Ready | Start | End | Reasons |
| --- | --- | ---: | ---: | ---: | :---: | --- | --- | --- |
| main | invalid_window | 6.97 | 1752 | 1752 | true | 2019-07-01 | 2026-06-18 | broker_ledger_years_below_7, broker_ledger_trading_days_below_7y |
| concentrated | invalid_window | 6.97 | 1733 | 1733 | true | 2019-07-01 | 2026-06-18 | broker_ledger_years_below_7, broker_ledger_trading_days_below_7y |

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
- Generated at: `2026-06-21T23:00:30+00:00`
