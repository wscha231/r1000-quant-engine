# Run287 Profitability Broker A/B

Date: 2026-07-07

Status: rejected as a performance candidate.

This package tests whether the positive row-level financial proxy screen for
`profitability_inflection_score` transfers to broker-ledger performance when
applied to the run287 official fixed target books.

## Guardrails

- No fullrun was dispatched.
- No policy hook was added.
- No threshold tuning was performed.
- No production promotion or live trading path is enabled.
- `period_forward_return` is not used by the A/B tool.
- `pit_universe_label_clean=false`; all evidence is research-only.
- The selected ticker set is preserved. The A/B only shifts weight among names
  already selected in the official target book.
- Cash is intended to remain unchanged; the run records cash deltas and cap
  infeasibility as blockers.

## Measurement Contract

- Source run: `28725350727`
- Target books:
  - `cloud_results/full_rebuild/20260705_28725350727_global_alpha_universe/alphaops_vnext/official_main_target_book.csv`
  - `cloud_results/full_rebuild/20260705_28725350727_global_alpha_universe/alphaops_vnext/official_concentrated_target_book.csv`
- Metric mode: `broker_ledger_next_close_cash_carry`
- Replay end date: `2026-07-06`
- Cash rate: `DGS3MO`, 1 business-day lag, 50 bps haircut, ACT/365
- Signal: `profitability_inflection_score`
- A/B arms:
  - `baseline`
  - `profitability_top_quintile_tilt05`
  - `profitability_top_quintile_tilt10`

## Results

| Portfolio | Arm | Verdict | CAGR | MaxDD | Delta CAGR pp | Delta MDD pp |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| Main | baseline | `baseline` | 34.25% | -25.36% | +0.00 | +0.00 |
| Main | profitability_top_quintile_tilt05 | `reject_oos_cagr_worse` | 33.42% | -25.05% | -0.83 | +0.31 |
| Main | profitability_top_quintile_tilt10 | `reject_oos_cagr_worse` | 32.56% | -24.83% | -1.69 | +0.54 |
| Concentrated | baseline | `baseline` | 48.66% | -22.96% | +0.00 | +0.00 |
| Concentrated | profitability_top_quintile_tilt05 | `reject_mdd_worse` | 46.53% | -23.52% | -2.13 | -0.57 |
| Concentrated | profitability_top_quintile_tilt10 | `reject_mdd_worse` | 44.40% | -23.80% | -4.26 | -0.84 |

## Verdict

The row-level positive proxy does not transfer to fixed-book broker-ledger
reweighting. The profitability top-quintile tilt should not become a policy
hook, a fullrun candidate, or a production claim.

For Main, the tilt improves full-window MDD slightly but reduces CAGR and
worsens OOS CAGR. For Concentrated, the tilt reduces CAGR materially and also
worsens MDD. This is negative evidence against the simple top-quintile
profitability reweight.

## Artifacts

- Combined summary: `outputs/run287_profitability_broker_ab/summary.json`
- Main summary: `outputs/run287_profitability_broker_ab/main/summary.json`
- Main report: `outputs/run287_profitability_broker_ab/main/report.md`
- Concentrated summary: `outputs/run287_profitability_broker_ab/concentrated/summary.json`
- Concentrated report: `outputs/run287_profitability_broker_ab/concentrated/report.md`
- Tool: `tools/run_run287_profitability_broker_ab.py`
- Smoke: `tests/run287_profitability_broker_ab_smoke.py`
