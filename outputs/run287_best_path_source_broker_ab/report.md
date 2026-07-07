# Run287 Multi-Source Fusion Broker A/B

- Status: `completed`
- Decision label: `reject_no_broker_ab_candidate`
- Signals: `w4_sec_score, financial_statement_proxy_score, technical_momentum_score, macro_regime_score, risk_control_score`
- Cash carry mode: `risk_free_rate`
- Replay end date: `2026-07-02`
- Runner parity status: `parity_documented_gap`
- Measurement acceptance allowed: `False`
- No fullrun, hook, threshold tuning, production promotion, or live trading.

## Score Join Coverage

| Portfolio | Non-cash rows | Exact rows | As-of prior rows | Missing rows | Missing rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| concentrated | 463 | 458 | 5 | 0 | 0.00% |

- As-of prior rows use the latest ticker score available on or before the target rebalance date.
- No missing non-cash scores remain after the as-of prior join.

## Broker A/B

| Portfolio | Signal | Arm | Verdict | CAGR | MaxDD | dCAGR pp | dMDD pp | Contract pass |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| concentrated | w4_sec_score | baseline | `baseline` | 48.41% | -22.96% | +0.00 | +0.00 | False |
| concentrated | w4_sec_score | w4_sec_top_quintile_tilt05 | `reject_oos_cagr_worse` | 49.37% | -22.60% | +0.97 | +0.35 | False |
| concentrated | w4_sec_score | w4_sec_top_quintile_tilt10 | `reject_oos_cagr_worse` | 49.56% | -22.26% | +1.16 | +0.70 | False |
| concentrated | financial_statement_proxy_score | baseline | `baseline` | 48.41% | -22.96% | +0.00 | +0.00 | False |
| concentrated | financial_statement_proxy_score | financial_statement_proxy_top_quintile_tilt05 | `reject_mdd_worse` | 47.09% | -23.32% | -1.32 | -0.36 | False |
| concentrated | financial_statement_proxy_score | financial_statement_proxy_top_quintile_tilt10 | `reject_mdd_worse` | 45.66% | -23.40% | -2.75 | -0.44 | False |
| concentrated | technical_momentum_score | baseline | `baseline` | 48.41% | -22.96% | +0.00 | +0.00 | False |
| concentrated | technical_momentum_score | technical_momentum_top_quintile_tilt05 | `reject_oos_cagr_worse` | 47.50% | -22.13% | -0.91 | +0.82 | False |
| concentrated | technical_momentum_score | technical_momentum_top_quintile_tilt10 | `reject_oos_cagr_worse` | 46.51% | -21.27% | -1.90 | +1.68 | False |
| concentrated | macro_regime_score | baseline | `baseline` | 48.41% | -22.96% | +0.00 | +0.00 | False |
| concentrated | macro_regime_score | macro_regime_top_quintile_tilt05 | `reject_oos_cagr_worse` | 47.76% | -23.13% | -0.64 | -0.17 | False |
| concentrated | macro_regime_score | macro_regime_top_quintile_tilt10 | `reject_oos_cagr_worse` | 47.16% | -23.05% | -1.25 | -0.10 | False |
| concentrated | risk_control_score | baseline | `baseline` | 48.41% | -22.96% | +0.00 | +0.00 | False |
| concentrated | risk_control_score | risk_control_top_quintile_tilt05 | `reject_oos_cagr_worse` | 47.37% | -22.27% | -1.03 | +0.68 | False |
| concentrated | risk_control_score | risk_control_top_quintile_tilt10 | `reject_oos_cagr_worse` | 46.32% | -21.55% | -2.08 | +1.41 | False |

## Interpretation

- This is fixed-book broker-ledger evidence on enriched official run287 target books.
- Selected ticker sets are preserved; the A/B shifts weight only among already-selected non-cash names.
- Measurement contract blockers: `runner_parity_not_exact`.
- A positive arm remains review-only while runner parity is not exact and PIT membership is not clean.
