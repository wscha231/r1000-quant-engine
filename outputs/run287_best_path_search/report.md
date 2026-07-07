# Run287 Best Path Search

- Status: `completed`
- Decision label: `best_path_main_mdd_neutralized_growth_design_needed`
- Runner parity status: `parity_documented_gap`
- Measurement acceptance allowed: `False`
- No fullrun, hook, threshold tuning, production promotion, or live trading.

## Main MDD Attribution

- Window: `2021-11-19` to `2022-09-26`
- Baseline: CAGR `33.81%`, MDD `-25.36%`
- Tilt10: CAGR `35.79%`, MDD `-25.93%`
- Delta: CAGR `+1.98pp`, MDD `-0.56pp`

| Ticker | Delta price contribution pp | Avg weight delta pp | Target delta sum pp | Avg score |
| --- | ---: | ---: | ---: | ---: |
| AMD | -0.62 | -0.13 | -0.17 | 0.143 |
| BLDR | -0.57 | -0.33 | -1.30 | 0.224 |
| NET | -0.56 | +3.19 | +5.26 | 0.319 |
| CHRW | -0.40 | +1.32 | +4.43 | 0.349 |
| NVDA | -0.38 | +0.61 | -2.12 | 0.212 |
| KMI | -0.34 | +1.66 | +3.49 | 0.387 |
| MA | -0.29 | +0.38 | +2.40 | 0.318 |
| MEDP | -0.24 | -0.21 | -0.42 | 0.138 |
| AVGO | -0.18 | +0.23 | +0.92 | 0.336 |
| FICO | -0.12 | -0.15 | -0.27 | 0.206 |

## Concentrated Source Ranking

- Source decision: `concentrated_source_edge_not_contract`
- Best source arm: `w4_sec_score` / `w4_sec_top_quintile_tilt10` with CAGR `49.56%`, MDD `-22.26%`, dCAGR `+1.16pp`, dMDD `+0.70pp`.

| Signal | Arm | Verdict | CAGR | MaxDD | dCAGR pp | dMDD pp | Contract pass |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| w4_sec_score | w4_sec_top_quintile_tilt10 | `reject_oos_cagr_worse` | 49.56% | -22.26% | +1.16 | +0.70 | False |
| w4_sec_score | w4_sec_top_quintile_tilt05 | `reject_oos_cagr_worse` | 49.37% | -22.60% | +0.97 | +0.35 | False |
| macro_regime_score | macro_regime_top_quintile_tilt05 | `reject_oos_cagr_worse` | 47.76% | -23.13% | -0.64 | -0.17 | False |
| technical_momentum_score | technical_momentum_top_quintile_tilt05 | `reject_oos_cagr_worse` | 47.50% | -22.13% | -0.91 | +0.82 | False |
| risk_control_score | risk_control_top_quintile_tilt05 | `reject_oos_cagr_worse` | 47.37% | -22.27% | -1.03 | +0.68 | False |
| macro_regime_score | macro_regime_top_quintile_tilt10 | `reject_oos_cagr_worse` | 47.16% | -23.05% | -1.25 | -0.10 | False |
| financial_statement_proxy_score | financial_statement_proxy_top_quintile_tilt05 | `reject_mdd_worse` | 47.09% | -23.32% | -1.32 | -0.36 | False |
| technical_momentum_score | technical_momentum_top_quintile_tilt10 | `reject_oos_cagr_worse` | 46.51% | -21.27% | -1.90 | +1.68 | False |
| risk_control_score | risk_control_top_quintile_tilt10 | `reject_oos_cagr_worse` | 46.32% | -21.55% | -2.08 | +1.41 | False |
| financial_statement_proxy_score | financial_statement_proxy_top_quintile_tilt10 | `reject_mdd_worse` | 45.66% | -23.40% | -2.75 | -0.44 | False |

## Interpretation

- Main has a growth signal, but direct overweighting worsens the structural 2022 drawdown.
- The closest Concentrated path is W4 SEC, but it is a near-miss rather than a candidate because it still fails 50% CAGR and worsens OOS CAGR.
- Concentrated source tilts must restore CAGR without relying on post-hoc percentile or threshold selection.
- Any positive path remains review-only while runner parity is not exact and PIT membership is not clean.
