# Run287 Main Exit Latency Audit

Status: `completed`

This is a research-only diagnostic. It does not replay trades, dispatch
a fullrun, mutate target books, tune thresholds, or create a crash
predictor.

## Max Drawdown Window

- Peak: `2021-11-19` equity `$257,936.22`
- Trough: `2022-09-26` equity `$192,518.61`
- MaxDD: `-25.36%`

## Top Mark-to-Market Contributors

| Ticker | MTM PnL | Pct of peak equity | Avg weight | Held days |
| --- | ---: | ---: | ---: | ---: |
| NET | $-8,374 | -3.25% | 4.09% | 29 |
| ENPH | $-5,358 | -2.08% | 7.13% | 29 |
| U | $-4,236 | -1.64% | 3.26% | 29 |
| BKR | $-2,859 | -1.11% | 2.22% | 62 |
| MOS | $-2,636 | -1.02% | 2.99% | 62 |
| SAIA | $-2,444 | -0.95% | 5.38% | 27 |
| MA | $-2,313 | -0.90% | 2.80% | 107 |
| DDOG | $-2,176 | -0.84% | 4.96% | 52 |
| SNOW | $-2,005 | -0.78% | 5.10% | 7 |
| CAR | $-1,921 | -0.74% | 2.20% | 42 |

## Exit-Latency Signals

| Ticker | Hard signal | First signal | Latency TD | Loss after signal | Reason |
| --- | --- | --- | ---: | ---: | --- |
| NET | true | 2021-09-30 | 2 | $-5,130 | target_removed,material_reduction |
| ENPH | true | 2021-11-30 | 2 | $-5,572 | material_reduction |
| U | true | 2021-11-30 | 2 | $-1,804 | material_reduction |
| BKR | true | 2022-06-30 | 2 | $-247 | target_removed,material_reduction |
| MOS | true | 2022-06-30 | 2 | $-171 | target_removed,material_reduction |
| SAIA | true | 2021-11-30 | 2 | $-1,222 | target_removed,material_reduction |
| MA | true | 2022-02-28 | 2 | $-1,619 | material_reduction |
| DDOG | true | 2021-10-29 | 2 | $1,636 | material_reduction |
| SNOW | true | 2021-10-29 | 2 | $-41 | material_reduction |
| CAR | true | 2021-12-31 | 2 | $-362 | material_reduction,trim_applied |

## Diagnosis

- Latency candidate present: `false`
- Diagnosis: `hard_signals_found_but_latency_or_post_signal_loss_not_material`
- Next action: `record_negative_latency_evidence; do_not_tune_losing_months`

Research boundary: if a candidate exists, the next step is an ex-ante
counterfactual with held-out validation. Directly editing losing
months or tickers remains forbidden.
