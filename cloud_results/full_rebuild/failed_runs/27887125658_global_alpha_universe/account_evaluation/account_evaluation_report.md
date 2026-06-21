# Account Evaluation

Official performance evidence uses broker-ledger replay with next-close fills, integer shares, cash, and transaction costs.
Legacy weight-level backtest metrics are retained only as research comparison fields and cannot produce a production-promotion verdict.

## Official Targets

Active target type: `interim_operating_gate`. Canonical mission targets are shown separately and remain unresolved until explicit user approval.

| Portfolio | Target Type | CAGR | Active Target | Canonical Target | Gap | MaxDD | Active Target | Canonical Target | Gap | Sharpe | Avg Cash | Pass |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | interim_operating_gate | 34.28% | 30.00% | 35.00% | 0.00pp | -27.18% | -25.00% | -25.00% | 2.18pp | 1.256 | 26.60% | false |
| concentrated | interim_operating_gate | 44.37% | 50.00% | 50.00% | 5.63pp | -24.70% | -28.00% | -25.00% | 0.00pp | 1.399 | 41.88% | false |

## Account State And Orders

| Portfolio | End Date | Equity | Latest Cash | Positions | Preview Orders | Buys | Sells | Blocked |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2026-06-18 | $779,037 | 20.29% | 13 | 2 | 2 | 0 | 0 |
| concentrated | 2026-06-18 | $1,290,469 | 5.73% | 5 | 5 | 3 | 2 | 0 |

## Broker Trade Journal

| Portfolio | Round Trips | Win Rate | Avg Return | Avg Holding Days | Profit Factor | Fees |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 1132 | 57.16% | 11.69% | 60.4 | 3.77 | $36,829 |
| concentrated | 390 | 54.62% | 11.86% | 53.2 | 3.71 | $36,177 |

## Tier-2 Strengthened Gates (IS / Sharpe / OOS-IS ratio / recent MDD / cash)

| Portfolio | IS CAGR | OOS CAGR | OOS/IS | Sharpe | Avg Cash | Recent MDD | Failing | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | :---: |
| main | 19.93% | 80.19% | 4.02x | 1.26 | 26.60% | -23.74% | is_cagr_min, oos_is_cagr_ratio_max | FAIL |
| concentrated | 18.78% | 138.32% | 7.36x | 1.40 | 41.88% | -22.99% | is_cagr_min, oos_is_cagr_ratio_max, sharpe_min | FAIL |

## Broker-Ledger Window Gate

| Portfolio | Status | Years | Actual Trading Days | Trading Days Evidence | Data Ready | Start | End | Reasons |
| --- | --- | ---: | ---: | ---: | :---: | --- | --- | --- |
| main | invalid_window | 6.97 | 1752 | 1752 | false | 2019-07-01 | 2026-06-18 | broker_ledger_years_below_7, broker_ledger_trading_days_below_7y, data_readiness_not_ready_for_policy_replay |
| concentrated | invalid_window | 6.97 | 1713 | 1713 | false | 2019-07-01 | 2026-06-18 | broker_ledger_years_below_7, broker_ledger_trading_days_below_7y, data_readiness_not_ready_for_policy_replay |

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
- Generated at: `2026-06-21T03:13:14+00:00`
