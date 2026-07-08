# Run287 Concentrated Financial Proxy One-Pass A/B

## Verdict

The two screen-positive financial proxy signals failed fixed-book broker-ledger A/B.
No fullrun was dispatched. No hook was added. No threshold/grid tuning was performed.
This remains research-only evidence with production promotion blocked because `pit_universe_label_clean=false`.

Decision label: `financial_proxy_onepass_rejected`

## Protocol

- Portfolio: `concentrated`
- Target book: run287 official concentrated target book
- Replay end: `2026-07-02`
- Signals: `profitability_inflection_score`, `actual_results_score`
- Design: top-quintile only, single 5% stock-gross tilt, cash preserved
- Accounting: cash-carry and zero-yield side by side
- Forward returns: audit labels only, not ranking inputs

## Results

| Signal | Accounting | Arm CAGR | Arm MDD | dCAGR pp | dMDD pp | OOS dCAGR pp | OOS2 dCAGR pp | Verdict |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `profitability_inflection_score` | `cash_carry` | 46.28% | -23.52% | -2.13 | -0.57 | -3.77 | -2.50 | `reject_mdd_worse` |
| `profitability_inflection_score` | `zero_yield` | 44.95% | -23.76% | -2.05 | -0.54 | -3.67 | -2.43 | `reject_mdd_worse` |
| `actual_results_score` | `cash_carry` | 47.98% | -23.19% | -0.42 | -0.24 | -4.65 | -1.08 | `reject_oos_cagr_worse` |
| `actual_results_score` | `zero_yield` | 46.64% | -23.45% | -0.37 | -0.23 | -4.51 | -1.02 | `reject_oos_cagr_worse` |

## Baselines

- `cash_carry` baseline: 48.41% CAGR / -22.96% MDD
- `zero_yield` baseline: 47.00% CAGR / -23.22% MDD

## Interpretation

- `profitability_inflection_score` was the stronger diagnostic screen, but the 5% broker tilt reduced CAGR by more than 2 pp and worsened MDD in both accounting modes.
- `actual_results_score` produced a small IS benefit but damaged OOS and OOS2 CAGR, so it is not a clean candidate.
- The screen-to-broker failure means these financial proxy signals should not be promoted into a hook or fullrun candidate from run287 evidence.
- Concentrated remains below the 50% target on the honest run287 fixed-book baseline; the next legitimate source is true PIT earnings/guidance revision data or a different predeclared source screen.

## Artifacts

- `outputs/run287_financial_proxy_onepass_ab/summary.json`
- `outputs/run287_financial_proxy_onepass_ab/arm_metrics.csv`
- `outputs/run287_financial_proxy_onepass_ab/report.md`
