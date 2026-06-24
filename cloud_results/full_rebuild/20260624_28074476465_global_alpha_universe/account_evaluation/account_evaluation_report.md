# Account Evaluation

Official performance evidence uses broker-ledger replay with next-close fills, integer shares, cash, and transaction costs.
Legacy weight-level backtest metrics are retained only as research comparison fields and cannot produce a production-promotion verdict.

## Official Targets

Active target type: `interim_operating_gate`. Canonical mission targets are shown separately and remain unresolved until explicit user approval.

| Portfolio | Target Type | CAGR | Active Target | Canonical Target | Gap | MaxDD | Active Target | Canonical Target | Gap | Sharpe | Avg Cash | Pass |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | interim_operating_gate | 33.15% | 30.00% | 35.00% | 0.00pp | -26.02% | -25.00% | -25.00% | 1.02pp | 1.219 | 26.70% | false |
| concentrated | interim_operating_gate | 46.24% | 50.00% | 50.00% | 3.76pp | -25.82% | -28.00% | -25.00% | 0.00pp | 1.421 | 42.18% | false |

## Account State And Orders

| Portfolio | End Date | Equity | Latest Cash | Positions | Preview Orders | Buys | Sells | Blocked |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2026-06-23 | $753,854 | 15.67% | 13 | 12 | 7 | 5 | 0 |
| concentrated | 2026-06-23 | $1,461,103 | 6.12% | 5 | 5 | 3 | 2 | 0 |

## Broker Trade Journal

| Portfolio | Round Trips | Win Rate | Avg Return | Avg Holding Days | Profit Factor | Fees |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 1140 | 57.54% | 10.96% | 60.1 | 3.61 | $37,653 |
| concentrated | 398 | 56.03% | 12.51% | 53.3 | 3.98 | $42,579 |

## Tier-2 Strengthened Gates (IS / Sharpe / OOS-IS ratio / recent MDD / cash)

| Portfolio | IS CAGR | OOS CAGR | OOS/IS | Sharpe | Avg Cash | Recent MDD | Failing | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | :---: |
| main | 20.27% | 73.91% | 3.65x | 1.22 | 26.70% | -24.31% | is_cagr_min, oos_is_cagr_ratio_max | FAIL |
| concentrated | 21.69% | 135.34% | 6.24x | 1.42 | 42.18% | -23.23% | is_cagr_min, oos_is_cagr_ratio_max | FAIL |

## Broker-Ledger Window Gate

| Portfolio | Status | Years | Actual Trading Days | Trading Days Evidence | Data Ready | Start | End | Reasons |
| --- | --- | ---: | ---: | ---: | :---: | --- | --- | --- |
| main | invalid_window | 7.06 | 1778 | 1778 | true | 2019-06-03 | 2026-06-23 | proxy_8y_10y_evidence_blocked_until_pit_universe_clean, pit_universe_label_missing |
| concentrated | invalid_window | 7.06 | 1778 | 1778 | true | 2019-06-03 | 2026-06-23 | proxy_8y_10y_evidence_blocked_until_pit_universe_clean, pit_universe_label_missing |

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
- Generated at: `2026-06-24T08:10:06+00:00`
