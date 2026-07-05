# Account Evaluation

Official performance evidence uses broker-ledger replay with next-close fills, integer shares, cash, and transaction costs.
Legacy weight-level backtest metrics are retained only as research comparison fields and cannot produce a production-promotion verdict.

## Official Targets

Active target type: `interim_operating_gate`. Canonical mission targets are shown separately and remain unresolved until explicit user approval.

| Portfolio | Target Type | CAGR | Active Target | Canonical Target | Gap | MaxDD | Active Target | Canonical Target | Gap | Sharpe | Avg Cash | Pass |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | interim_operating_gate | 32.94% | 30.00% | 35.00% | 0.00pp | -25.65% | -25.00% | -25.00% | 0.65pp | 1.237 | 29.34% | false |
| concentrated | interim_operating_gate | 46.99% | 50.00% | 50.00% | 3.01pp | -23.22% | -28.00% | -25.00% | 0.00pp | 1.455 | 41.04% | false |

## Account State And Orders

| Portfolio | End Date | Equity | Latest Cash | Positions | Preview Orders | Buys | Sells | Blocked |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 2026-07-02 | $750,715 | 11.03% | 14 | 13 | 6 | 7 | 0 |
| concentrated | 2026-07-02 | $1,528,890 | 16.88% | 5 | 5 | 1 | 4 | 0 |

## Broker Trade Journal

| Portfolio | Round Trips | Win Rate | Avg Return | Avg Holding Days | Profit Factor | Fees |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 1067 | 58.39% | 11.97% | 57.2 | 4.01 | $41,730 |
| concentrated | 449 | 58.80% | 10.34% | 47.4 | 3.74 | $60,181 |

## Tier-2 Strengthened Gates (IS / Sharpe / OOS-IS ratio / recent MDD / cash)

| Portfolio | IS CAGR | OOS CAGR | OOS/IS | Sharpe | Avg Cash | Recent MDD | Failing | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | :---: |
| main | 22.03% | 66.17% | 3.00x | 1.24 | 29.34% | -20.70% | is_cagr_min, oos_is_cagr_ratio_max | FAIL |
| concentrated | 26.47% | 116.14% | 4.39x | 1.45 | 41.04% | -23.22% | is_cagr_min, oos_is_cagr_ratio_max | FAIL |

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
- Generated at: `2026-07-05T04:31:48+00:00`
