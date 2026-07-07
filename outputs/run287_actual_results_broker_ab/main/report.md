# Run287 Financial Score Broker A/B

- Status: `completed`
- Decision label: `no_positive_broker_ab_candidate`
- Portfolio: `main`
- Signal: `actual_results_score`
- Target book: `H:\codex\r1000_run287_closeout_20260707\cloud_results\full_rebuild\20260705_28725350727_global_alpha_universe\alphaops_vnext\official_main_target_book.csv`
- Price cache: `H:\codex\r1000_run287_r1r2_20260706\outputs\run287_latest_close_20260706\cache_prices`
- Replay end date: `2026-07-06`
- Metric mode: `risk_free_rate` / broker-ledger cash-carry
- Selected ticker set preserved; cash target is unchanged unless cap infeasible.
- This is default-off research evidence only. No fullrun, hook, production promotion, or live trading.

| arm | verdict | CAGR | MaxDD | Sharpe | dCAGR pp | dMDD pp | eligible events | abs weight delta | cash d pp |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | `baseline` | 34.25% | -25.36% | 1.276 | +0.00 | +0.00 | 0 | 0.000 | +0.000 |
| actual_results_top_quintile_tilt05 | `reject_oos_cagr_worse` | 34.88% | -24.93% | 1.289 | +0.64 | +0.43 | 249 | 6.079 | +0.007 |
| actual_results_top_quintile_tilt10 | `reject_oos_cagr_worse` | 35.45% | -24.59% | 1.298 | +1.20 | +0.77 | 249 | 12.159 | -0.039 |

## Guardrails

- `period_forward_return` is not used by this tool.
- `candidate_allowed=false` even when an arm is positive; a positive result only permits review of default-off broker A/B evidence.
- Production remains blocked while `pit_universe_label_clean=false`.
