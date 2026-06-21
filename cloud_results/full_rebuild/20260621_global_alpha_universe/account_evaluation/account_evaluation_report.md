# Account Evaluation

Official performance evidence uses broker-ledger replay with next-close fills, integer shares, cash, and transaction costs.
Legacy weight-level backtest metrics are retained only as research comparison fields and cannot produce a production-promotion verdict.

## Official Targets

Active target type: `interim_operating_gate`. Canonical mission targets are shown separately and remain unresolved until explicit user approval.

| Portfolio | Target Type | CAGR | Active Target | Canonical Target | Gap | MaxDD | Active Target | Canonical Target | Gap | Sharpe | Avg Cash | Pass |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | interim_operating_gate | 34.27% | 30.00% | 35.00% | 0.00pp | -27.18% | -25.00% | -25.00% | 2.18pp | 1.255 | 26.59% | false |
| concentrated | interim_operating_gate | 44.40% | 50.00% | 50.00% | 5.60pp | -24.70% | -28.00% | -25.00% | 0.00pp | 1.401 | 41.92% | false |

## Account State And Orders

| Portfolio | End Date | Equity | Latest Cash | Positions | Preview Orders | Buys | Sells | Blocked |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2026-06-18 | $778,666 | 14.77% | 13 | 12 | 7 | 5 | 0 |
| concentrated | 2026-06-18 | $1,292,176 | 5.77% | 5 | 5 | 3 | 2 | 0 |

## Broker Trade Journal

| Portfolio | Round Trips | Win Rate | Avg Return | Avg Holding Days | Profit Factor | Fees |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 1126 | 56.93% | 10.96% | 60.2 | 3.59 | $36,376 |
| concentrated | 390 | 54.87% | 11.95% | 53.3 | 3.74 | $36,218 |

## Tier-2 Strengthened Gates (IS / Sharpe / OOS-IS ratio / recent MDD / cash)

| Portfolio | IS CAGR | OOS CAGR | OOS/IS | Sharpe | Avg Cash | Recent MDD | Failing | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | :---: |
| main | 19.88% | 80.35% | 4.04x | 1.26 | 26.59% | -23.77% | is_cagr_min, oos_is_cagr_ratio_max | FAIL |
| concentrated | 18.80% | 138.39% | 7.36x | 1.40 | 41.92% | -22.98% | is_cagr_min, oos_is_cagr_ratio_max | FAIL |

## Broker-Ledger Window Gate

| Portfolio | Status | Years | Actual Trading Days | Trading Days Evidence | Data Ready | Start | End | Reasons |
| --- | --- | ---: | ---: | ---: | :---: | --- | --- | --- |
| main | invalid_window | 6.97 | 1752 | 1752 | true | 2019-07-01 | 2026-06-18 | broker_ledger_years_below_7, broker_ledger_trading_days_below_7y |
| concentrated | invalid_window | 6.97 | 1713 | 1713 | true | 2019-07-01 | 2026-06-18 | broker_ledger_years_below_7, broker_ledger_trading_days_below_7y |

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
- Generated at: `2026-06-21T02:50:40+00:00`
