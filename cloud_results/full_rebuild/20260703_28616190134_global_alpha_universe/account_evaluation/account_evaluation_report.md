# Account Evaluation

Official performance evidence uses broker-ledger replay with next-close fills, integer shares, cash, and transaction costs.
Legacy weight-level backtest metrics are retained only as research comparison fields and cannot produce a production-promotion verdict.

## Official Targets

Active target type: `interim_operating_gate`. Canonical mission targets are shown separately and remain unresolved until explicit user approval.

| Portfolio | Target Type | CAGR | Active Target | Canonical Target | Gap | MaxDD | Active Target | Canonical Target | Gap | Sharpe | Avg Cash | Pass |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | interim_operating_gate | 30.61% | 30.00% | 35.00% | 0.00pp | -26.02% | -25.00% | -25.00% | 1.02pp | 1.130 | 26.39% | false |
| concentrated | interim_operating_gate | 44.53% | 50.00% | 50.00% | 5.47pp | -23.27% | -28.00% | -25.00% | 0.00pp | 1.354 | 41.54% | false |

## Account State And Orders

| Portfolio | End Date | Equity | Latest Cash | Positions | Preview Orders | Buys | Sells | Blocked |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2026-07-02 | $662,358 | 5.21% | 15 | 13 | 6 | 7 | 0 |
| concentrated | 2026-07-02 | $1,356,612 | 17.06% | 5 | 4 | 1 | 3 | 0 |

## Broker Trade Journal

| Portfolio | Round Trips | Win Rate | Avg Return | Avg Holding Days | Profit Factor | Fees |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 1157 | 57.99% | 11.28% | 60.0 | 3.74 | $39,730 |
| concentrated | 406 | 57.14% | 13.50% | 54.0 | 4.31 | $48,106 |

## Tier-2 Strengthened Gates (IS / Sharpe / OOS-IS ratio / recent MDD / cash)

| Portfolio | IS CAGR | OOS CAGR | OOS/IS | Sharpe | Avg Cash | Recent MDD | Failing | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | :---: |
| main | 20.56% | 60.93% | 2.96x | 1.13 | 26.39% | -24.26% | is_cagr_min, sharpe_min | FAIL |
| concentrated | 22.90% | 118.81% | 5.19x | 1.35 | 41.54% | -23.27% | is_cagr_min, oos_is_cagr_ratio_max, sharpe_min | FAIL |

## Broker-Ledger Window Gate

| Portfolio | Status | Years | Actual Trading Days | Trading Days Evidence | Data Ready | Start | End | Reasons |
| --- | --- | ---: | ---: | ---: | :---: | --- | --- | --- |
| main | ok | 7.08 | 1784 | 1784 | true | 2019-06-03 | 2026-07-02 | none |
| concentrated | ok | 7.08 | 1784 | 1784 | true | 2019-06-03 | 2026-07-02 | none |

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
- Generated at: `2026-07-02T23:51:30+00:00`
