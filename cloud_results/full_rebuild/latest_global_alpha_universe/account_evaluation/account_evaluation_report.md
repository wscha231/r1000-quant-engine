# Account Evaluation

Official performance evidence uses broker-ledger replay with next-close fills, integer shares, cash, and transaction costs.
Legacy weight-level backtest metrics are retained only as research comparison fields and cannot produce a production-promotion verdict.

## Official Targets

Active target type: `interim_operating_gate`. Canonical mission targets are shown separately and remain unresolved until explicit user approval.

| Portfolio | Target Type | CAGR | Active Target | Canonical Target | Gap | MaxDD | Active Target | Canonical Target | Gap | Sharpe | Avg Cash | Pass |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | interim_operating_gate | 34.42% | 30.00% | 35.00% | 0.00pp | -27.19% | -25.00% | -25.00% | 2.19pp | 1.261 | 26.69% | false |
| concentrated | interim_operating_gate | 44.60% | 50.00% | 50.00% | 5.40pp | -24.62% | -28.00% | -25.00% | 0.00pp | 1.395 | 42.43% | false |

## Account State And Orders

| Portfolio | End Date | Equity | Latest Cash | Positions | Preview Orders | Buys | Sells | Blocked |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2026-06-18 | $784,967 | 14.88% | 13 | 12 | 7 | 5 | 0 |
| concentrated | 2026-06-18 | $1,305,212 | 5.74% | 5 | 5 | 3 | 2 | 0 |

## Broker Trade Journal

| Portfolio | Round Trips | Win Rate | Avg Return | Avg Holding Days | Profit Factor | Fees |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 1124 | 57.03% | 10.90% | 59.9 | 3.56 | $36,835 |
| concentrated | 392 | 54.85% | 12.00% | 53.1 | 3.76 | $36,584 |

## Tier-2 Strengthened Gates (IS / Sharpe / OOS-IS ratio / recent MDD / cash)

| Portfolio | IS CAGR | OOS CAGR | OOS/IS | Sharpe | Avg Cash | Recent MDD | Failing | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | :---: |
| main | 20.37% | 79.23% | 3.89x | 1.26 | 26.69% | -23.73% | is_cagr_min, oos_is_cagr_ratio_max | FAIL |
| concentrated | 19.09% | 138.15% | 7.24x | 1.40 | 42.43% | -23.26% | is_cagr_min, oos_is_cagr_ratio_max, sharpe_min | FAIL |

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
- Generated at: `2026-06-21T22:54:37+00:00`
