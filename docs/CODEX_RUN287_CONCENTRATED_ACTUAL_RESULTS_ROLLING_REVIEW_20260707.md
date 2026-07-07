# Run287 Concentrated Actual Results Rolling Review

Date: 2026-07-07

Scope: cheap fixed-book broker-ledger review only. No fullrun was dispatched, no
new hook was added, no threshold was tuned, and production promotion remains
blocked while `pit_universe_label_clean=false`.

## Verdict

Both Concentrated `actual_results_score` top-quintile tilts are rejected.

The replay uses the run287 official Concentrated target book through the
2026-07-06 close with `broker_ledger_next_close_cash_carry`.

| Arm | CAGR | MaxDD | Delta CAGR pp | Delta MaxDD pp | Verdict |
| --- | ---: | ---: | ---: | ---: | --- |
| Baseline | 48.66% | -22.96% | - | - | baseline |
| `actual_results_top_quintile_tilt05` | 48.28% | -23.19% | -0.38 | -0.24 | `reject_headline_contract_not_restored` |
| `actual_results_top_quintile_tilt10` | 47.81% | -23.39% | -0.85 | -0.43 | `reject_headline_contract_not_restored` |

The 50% Concentrated CAGR contract is not restored. Both tilts also weaken the
post-2024-07-01 OOS CAGR versus baseline:

| Arm | OOS CAGR | OOS MaxDD | OOS Delta CAGR pp | OOS Delta MaxDD pp |
| --- | ---: | ---: | ---: | ---: |
| `actual_results_top_quintile_tilt05` | 115.20% | -23.19% | -4.41 | -0.24 |
| `actual_results_top_quintile_tilt10` | 110.86% | -23.39% | -8.75 | -0.43 |

## Rolling Evidence

| Arm | 12m positive rate | 12m median dCAGR pp | 12m worst dCAGR pp | 24m positive rate | 36m positive rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| `actual_results_top_quintile_tilt05` | 44.16% | -0.14 | -20.24 | 60.29% | 64.41% |
| `actual_results_top_quintile_tilt10` | 44.16% | -0.28 | -38.97 | 58.82% | 62.71% |

Rolling evidence is not strong enough to override the full-window miss and OOS
regression.

## Measurement Contract

- `runner_parity_status=parity_documented_gap`
- `measurement_contract_acceptance_allowed=false`
- `measurement_contract_acceptance_blockers=["runner_parity_not_exact"]`
- `survivorship_inflation_label=proxy`
- `survivorship_unmeasured_component=delisted_exclusion`

The results are research-only fixed-book evidence. They cannot be used as
acceptance evidence or as a production/public claim.

## Artifacts

- `outputs/run287_concentrated_actual_results_rolling_review_tilt05/summary.json`
- `outputs/run287_concentrated_actual_results_rolling_review_tilt05/window_metrics.csv`
- `outputs/run287_concentrated_actual_results_rolling_review_tilt05/report.md`
- `outputs/run287_concentrated_actual_results_rolling_review_tilt10/summary.json`
- `outputs/run287_concentrated_actual_results_rolling_review_tilt10/window_metrics.csv`
- `outputs/run287_concentrated_actual_results_rolling_review_tilt10/report.md`

Bulky per-arm replay internals were intentionally not retained in the committed
artifact package.

## Next Action

Do not dispatch a fullrun and do not design a policy hook from these tilts. The
Concentrated path still requires a separate W4 decision-time source screen,
especially SEC Form 4 and 13F feed screening, with OOS validation before any
hook proposal.
