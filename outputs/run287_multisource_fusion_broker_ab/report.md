# Run287 Multi-Source Fusion Broker A/B

- Status: `completed`
- Decision label: `reject_no_broker_ab_candidate`
- Signals: `growth_confirmation_score`
- Cash carry mode: `risk_free_rate`
- Replay end date: `2026-07-02`
- Runner parity status: `parity_documented_gap`
- Measurement acceptance allowed: `False`
- No fullrun, hook, threshold tuning, production promotion, or live trading.

## Score Join Coverage

| Portfolio | Non-cash rows | Exact rows | As-of prior rows | Missing rows | Missing rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| concentrated | 463 | 458 | 5 | 0 | 0.00% |
| main | 1121 | 1107 | 14 | 0 | 0.00% |

- As-of prior rows use the latest ticker score available on or before the target rebalance date.
- No missing non-cash scores remain after the as-of prior join.

## Broker A/B

| Portfolio | Signal | Arm | Verdict | CAGR | MaxDD | dCAGR pp | dMDD pp | Contract pass |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| main | growth_confirmation_score | baseline | `baseline` | 33.81% | -25.36% | +0.00 | +0.00 | False |
| main | growth_confirmation_score | growth_confirmation_top_quintile_tilt05 | `reject_mdd_worse` | 34.87% | -25.62% | +1.06 | -0.26 | False |
| main | growth_confirmation_score | growth_confirmation_top_quintile_tilt10 | `reject_mdd_worse` | 35.79% | -25.93% | +1.98 | -0.56 | False |
| concentrated | growth_confirmation_score | baseline | `baseline` | 48.41% | -22.96% | +0.00 | +0.00 | False |
| concentrated | growth_confirmation_score | growth_confirmation_top_quintile_tilt05 | `reject_oos_cagr_worse` | 47.52% | -22.88% | -0.89 | +0.07 | False |
| concentrated | growth_confirmation_score | growth_confirmation_top_quintile_tilt10 | `reject_oos_cagr_worse` | 46.53% | -22.55% | -1.87 | +0.41 | False |

## Interpretation

- This is fixed-book broker-ledger evidence on enriched official run287 target books.
- Selected ticker sets are preserved; the A/B shifts weight only among already-selected non-cash names.
- Measurement contract blockers: `runner_parity_not_exact`.
- A positive arm remains review-only while runner parity is not exact and PIT membership is not clean.
