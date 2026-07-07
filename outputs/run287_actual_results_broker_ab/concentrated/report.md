# Run287 Financial Score Broker A/B

- Status: `completed`
- Decision label: `no_positive_broker_ab_candidate`
- Portfolio: `concentrated`
- Signal: `actual_results_score`
- Target book: `H:\codex\r1000_run287_closeout_20260707\cloud_results\full_rebuild\20260705_28725350727_global_alpha_universe\alphaops_vnext\official_concentrated_target_book.csv`
- Price cache: `H:\codex\r1000_run287_r1r2_20260706\outputs\run287_latest_close_20260706\cache_prices`
- Replay end date: `2026-07-06`
- Metric mode: `risk_free_rate` / broker-ledger cash-carry
- Selected ticker set preserved; cash target is unchanged unless cap infeasible.
- This is default-off research evidence only. No fullrun, hook, production promotion, or live trading.

| arm | verdict | CAGR | MaxDD | Sharpe | dCAGR pp | dMDD pp | eligible events | abs weight delta | cash d pp |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | `baseline` | 48.66% | -22.96% | 1.495 | +0.00 | +0.00 | 0 | 0.000 | +0.000 |
| actual_results_top_quintile_tilt05 | `reject_oos_cagr_worse` | 48.28% | -23.19% | 1.504 | -0.38 | -0.24 | 129 | 4.549 | -0.008 |
| actual_results_top_quintile_tilt10 | `reject_mdd_worse` | 47.81% | -23.39% | 1.511 | -0.85 | -0.43 | 129 | 8.918 | -0.009 |

## Guardrails

- `period_forward_return` is not used by this tool.
- `candidate_allowed=false` even when an arm is positive; a positive result only permits review of default-off broker A/B evidence.
- Production remains blocked while `pit_universe_label_clean=false`.
