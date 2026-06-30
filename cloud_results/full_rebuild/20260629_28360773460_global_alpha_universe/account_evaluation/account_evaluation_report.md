# Account Evaluation

Official performance evidence uses broker-ledger replay with next-close fills, integer shares, cash, and transaction costs.
Legacy weight-level backtest metrics are retained only as research comparison fields and cannot produce a production-promotion verdict.

## Official Targets

Active target type: `interim_operating_gate`. Canonical mission targets are shown separately and remain unresolved until explicit user approval.

| Portfolio | Target Type | CAGR | Active Target | Canonical Target | Gap | MaxDD | Active Target | Canonical Target | Gap | Sharpe | Avg Cash | Pass |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | interim_operating_gate | 35.28% | 30.00% | 35.00% | 0.00pp | -24.25% | -25.00% | -25.00% | 0.00pp | 1.268 | 26.54% | false |
| concentrated | interim_operating_gate | 46.66% | 50.00% | 50.00% | 3.34pp | -24.12% | -28.00% | -25.00% | 0.00pp | 1.401 | 40.48% | false |

## Account State And Orders

| Portfolio | End Date | Equity | Latest Cash | Positions | Preview Orders | Buys | Sells | Blocked |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2026-06-26 | $845,076 | 15.78% | 13 | 13 | 7 | 6 | 0 |
| concentrated | 2026-06-26 | $1,495,156 | 6.38% | 5 | 5 | 3 | 2 | 0 |

## Broker Trade Journal

| Portfolio | Round Trips | Win Rate | Avg Return | Avg Holding Days | Profit Factor | Fees |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 1136 | 58.19% | 11.28% | 59.6 | 3.75 | $41,773 |
| concentrated | 438 | 57.53% | 11.78% | 52.0 | 4.03 | $48,545 |

## Tier-2 Strengthened Gates (IS / Sharpe / OOS-IS ratio / recent MDD / cash)

| Portfolio | IS CAGR | OOS CAGR | OOS/IS | Sharpe | Avg Cash | Recent MDD | Failing | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | :---: |
| main | 23.28% | 72.61% | 3.12x | 1.27 | 26.54% | -24.25% | is_cagr_min, oos_is_cagr_ratio_max | FAIL |
| concentrated | 24.84% | 122.29% | 4.92x | 1.40 | 40.48% | -24.02% | is_cagr_min, oos_is_cagr_ratio_max | FAIL |

## Broker-Ledger Window Gate

| Portfolio | Status | Years | Actual Trading Days | Trading Days Evidence | Data Ready | Start | End | Reasons |
| --- | --- | ---: | ---: | ---: | :---: | --- | --- | --- |
| main | invalid_window | 7.06 | 1780 | 1780 | true | 2019-06-03 | 2026-06-26 | proxy_8y_10y_evidence_blocked_until_pit_universe_clean, pit_universe_label_missing |
| concentrated | invalid_window | 7.06 | 1780 | 1780 | true | 2019-06-03 | 2026-06-26 | proxy_8y_10y_evidence_blocked_until_pit_universe_clean, pit_universe_label_missing |

## Governance

- Official metric mode: `broker_ledger_next_close`
- Active target type: `interim_operating_gate`
- Target contract status: `unresolved_user_decision_required`
- Canonical mission targets remain Main `35% / -25%` and Concentrated `50% / -25%` until explicit user approval changes them.
- Clean broker-ledger research window: `7.0 years / 1764 trading days`
- Proxy 8Y/10Y evidence is blocked until a PIT-clean historical universe label is present.
- Production target pass (Tier-1: full CAGR/MDD): `false`
- Strengthened pass (Tier-1 AND Tier-2 IS/Sharpe/ratio/cash/recent-MDD): `false`
- Research target pass: `false`
- Generated at: `2026-06-29T13:01:14+00:00`
