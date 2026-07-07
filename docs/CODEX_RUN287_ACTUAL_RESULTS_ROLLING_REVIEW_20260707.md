# Run287 Actual Results Rolling Review

Date: 2026-07-07

Scope: cheap fixed-book broker-ledger review only. No fullrun was dispatched, no
new hook was added, no threshold was tuned, and production promotion remains
blocked while `pit_universe_label_clean=false`.

## Verdict

`actual_results_top_quintile_tilt10` is mixed evidence, not a hook/fullrun
candidate.

On the run287 official Main target book, replayed through the 2026-07-06 close
with `broker_ledger_next_close_cash_carry`, the tilt restores the full-window
headline contract:

| Arm | CAGR | MaxDD | Delta CAGR pp | Delta MaxDD pp |
| --- | ---: | ---: | ---: | ---: |
| Main baseline | 34.25% | -25.36% | - | - |
| `actual_results_top_quintile_tilt10` | 35.45% | -24.59% | +1.20 | +0.77 |

But the post-2024-07-01 OOS window is worse than baseline:

| Window | Candidate CAGR | Candidate MaxDD | Delta CAGR pp | Delta MaxDD pp |
| --- | ---: | ---: | ---: | ---: |
| IS to 2024-06-30 | 25.49% | -24.59% | +2.78 | +0.77 |
| OOS from 2024-07-01 | 65.37% | -21.48% | -4.06 | -0.86 |
| OOS2 from 2023-01-01 | 49.86% | -21.48% | +0.42 | -0.86 |

Decision label: `mixed_headline_pass_oos_cagr_worse`.

## Rolling Evidence

Rolling windows are directionally positive in many periods, but not enough to
override the OOS regression:

| Group | Windows | Positive CAGR delta rate | Median dCAGR pp | Worst dCAGR pp | Median dMDD pp |
| --- | ---: | ---: | ---: | ---: | ---: |
| rolling_12m | 77 | 70.13% | +1.87 | -14.98 | +0.30 |
| rolling_24m | 68 | 88.24% | +1.92 | -4.46 | +0.30 |
| rolling_36m | 59 | 94.92% | +2.01 | -0.21 | +0.30 |

## Measurement Contract

- `runner_parity_status=parity_documented_gap`
- `measurement_contract_acceptance_allowed=false`
- `measurement_contract_acceptance_blockers=["runner_parity_not_exact"]`
- `survivorship_inflation_label=proxy`
- `survivorship_unmeasured_component=delisted_exclusion`

The full-window result can be discussed as research-only fixed-book evidence.
It cannot be used as acceptance evidence or as a production/public claim.

## Artifacts

- `outputs/run287_actual_results_rolling_review/summary.json`
- `outputs/run287_actual_results_rolling_review/window_metrics.csv`
- `outputs/run287_actual_results_rolling_review/report.md`

Bulky per-arm replay internals were intentionally not retained in the committed
artifact package.

## Next Action

Do not dispatch a fullrun from this result and do not design a policy hook from
this tilt. The correct next alpha path is still separate W4 decision-time source
screening, especially SEC Form 4 and 13F feed screening, with OOS validation
before any hook proposal.
