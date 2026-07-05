# Post-Run287 Alpha Workplan

Status: research-only, production-blocked.

Run287 latest-basis generated-book cash-carry replay failed the contract:

| Portfolio | Latest cash-carry | Contract | Gap |
| --- | ---: | ---: | ---: |
| Main CAGR | 33.81% | 35.00% | +1.19pp |
| Main MaxDD | -25.36% | -25.00% | +0.36pp |
| Concentrated CAGR | 48.41% | 50.00% | +1.59pp |
| Concentrated MaxDD | -22.96% | -25.00% | pass |

Decision label: `alpha_candidate_rejected_on_generated_book`.

Interpretation correction:

- The drop from the frozen combo is mostly measurement honesty, not a proven
  hook failure.
- The frozen candidate stopped at `2026-06-29`; run287 latest-basis evidence
  includes the `2026-06-30` through `2026-07-02` shock.
- Hook applied counts prove payload presence, not positive contribution.
- Alpha work must start from the run287 latest-basis baseline above, not from
  the frozen 06-29 headline.

## Sequence

1. Stabilize W1 target-book generation.
   - Default CatBoost task type must be CPU.
   - GPU is allowed only through explicit `R1000_CATBOOST_TASK_TYPE=GPU`.
   - `R1000_CATBOOST_TASK_TYPE=AUTO` is an explicit performance experiment, not
     a governance default.
   - Current-code local W1 double-run under
     `outputs/run287_w1_determinism_exact` passes 0/0/0 mismatch with max
     weight delta 0.0 for Main and Concentrated.
   - Boundary: local same-input determinism is proven; official artifact parity
     is still separate because the restored local candidate-generation price
     cache is smaller than the original runner cache.

2. Continue attribution before adding a rule.
   - Use latest-basis `2026-07-02`, not the `2026-06-29` clamp, for acceptance.
   - Keep frozen-book results diagnostic only.
   - Keep generated-book cash-carry as the research metric.
   - Rolling multi-window deficit measurement is now available under
     `outputs/run287_rolling_window_deficit`.
   - Main at `2026-06-29` clears CAGR but fails MDD; Main work is not just a
     July endpoint problem.
   - Concentrated at `2026-06-29` passes and `2026-07-02` fails; it is
     endpoint-sensitive, but not robustly above 50 across nearby endpoints.

3. New alpha work is allowed only as ex-ante research.
   - The rule must be expressible from decision-time observable inputs.
   - No losing run287 month or ticker may be directly edited.
   - Thresholds must be predeclared before replay.
   - Evaluation must report zero-yield and cash-carry side by side.

## First Alpha Target

The first useful candidate should target the exact gaps above, not broad
threshold retuning:

- Main needs drawdown repair and at least +1.19pp CAGR.
- Concentrated needs at least +1.59pp CAGR without increasing MaxDD beyond
  -25%.

Preferred candidate class:

- decision-time observable entry-quality or exit-quality signal
- applies symmetrically across historical months
- measurable on generated-book hook-off/hook-on replay
- produces a negative-evidence record if it fails

Forbidden candidate class:

- direct BE/CIEN/WDC/LNG vs AMD/UMC/TXN/MU hindsight substitution
- selecting `2026-06-29` because it avoids the July shock
- a new crash predictor, DD breaker, or VIX guard fitted to the
  `2026-06-30` through `2026-07-02` path
- post-hoc rank/revenue threshold picking after seeing run287 losses
- production or public performance wording while PIT membership is not clean

## Run287 Alpha Diagnostics

Local measurement-only diagnostics were run under `outputs/run287_alpha_diagnostics`.

Stock selection quality audit:

- candidate rows: 47,435
- selected rows: 1,604
- available ex-ante leader rows: 4,325
- missed ex-ante leader rows: 3,802
- forward labels used for ranking: false

Missed leader rejection reasons:

| Portfolio | cash | candidate_gate | cap_or_replacement |
| --- | ---: | ---: | ---: |
| Main | 868 | 792 | 172 |
| Concentrated | 873 | 853 | 244 |

Forward-label screen on missed leaders:

| Portfolio | Rejection reason | 126d excess mean | 126d hit rate positive |
| --- | --- | ---: | ---: |
| Concentrated | cap_or_replacement | 9.26% | 54.35% |
| Concentrated | candidate_gate | 3.95% | 49.08% |
| Concentrated | cash | 2.00% | 46.00% |
| Main | cash | 4.29% | 50.35% |
| Main | candidate_gate | 3.93% | 47.72% |
| Main | cap_or_replacement | -0.51% | 36.72% |

Right-tail entry signal audit:

- Main winners: 14, skill evidence: 14, average signal stack: 7.07
- Concentrated winners: 5, skill evidence: 5, average signal stack: 7.60
- Drops that still had skill signals: Main 16, Concentrated 7

Interpretation:

- Winner identification was not the primary weakness; winners generally had
  strong ex-ante signal stacks when held.
- The first alpha candidate should focus on Concentrated
  `cap_or_replacement` misses, not broad cash deployment.
- Main needs a separate drawdown repair path. Main cap/replacement misses were
  not attractive on the 126d forward-label screen.

Next candidate to test:

`concentrated_cap_replacement_leader_capture_v1`

Contract:

- apply only to `cap_or_replacement` missed leaders
- require decision-time signal stack and positive leadership evidence
- preserve cash buffer
- do not use realized forward returns in ranking
- evaluate hook-off vs hook-on on the latest generated book
- reject if it fails to improve Concentrated CAGR by at least +1.59pp without
  breaching -25% MaxDD

## Candidate 1 Result

`concentrated_cap_replacement_leader_capture_v1` was tested with the existing
research-only broker counterfactual:

- output: `outputs/run287_alpha_diagnostics/concentrated_cap_replacement_counterfactual`
- baseline: `outputs/run287_metric_sidecar/generated_book_cash_carry/concentrated/metrics.json`
- metric mode: `broker_ledger_next_close_cash_carry`
- replay end: `2026-07-02`
- fullrun executed: false
- production mutation allowed: false
- forward returns used for ranking: false
- broad cash reduction allowed: false

Best arm by full-period CAGR delta:

| Rule | Swaps | Full CAGR delta | Full MaxDD delta | Challenger CAGR | Challenger MaxDD |
| --- | ---: | ---: | ---: | ---: | ---: |
| `rs3_ge20_and_revenue_ge10` | 10 | +0.01pp | -0.03pp | 48.41% | -22.99% |

Other tested arms were negative, with full-period CAGR deltas from roughly
-0.45pp to -1.31pp.

Decision:

`concentrated_cap_replacement_leader_capture_v1` is rejected on the generated
book. It does not close the +1.59pp Concentrated CAGR gap and should not be
promoted into a policy hook.

Next alpha direction:

- Do not broaden cap/replacement swapping.
- Do not frame Main work as "shock defense"; that revives falsified
  crash-prediction paths.
- Reframe Main work as exit-timing latency: did existing trend/RS exit logic
  react as quickly as a decision-time observable rule allowed?
- If there is no latency, record the -25.36% MDD as the honest latest-window
  value rather than fitting a rule to the shock.
- For Concentrated, only revisit leader capture if the rule is event-matched
  to a decision-time source stronger than rank/RS/revenue.
- Before any new Concentrated hook, require evidence that the rule improves
  more than the `2026-07-02` endpoint and does not merely restore a one-day
  50% print.

## Main Exit-Latency Result

`outputs/run287_exit_latency` audits the run287 generated-book cash-carry Main
max-drawdown window without replaying, dispatching, mutating target books, or
tuning thresholds.

Window:

- peak: `2021-11-19`, equity `$257,936.22`
- trough: `2022-09-26`, equity `$192,518.61`
- MaxDD: `-25.36%`

Result:

- hard exit/reduction signals on top contributors: `12`
- material latency count: `0`
- latency candidate present: `false`
- diagnosis:
  `hard_signals_found_but_latency_or_post_signal_loss_not_material`

Top mark-to-market loss contributors were NET, ENPH, U, BKR, MOS, SAIA, MA,
DDOG, SNOW, and CAR. The target/actual alignment was generally complete within
1 to 3 calendar days after the first hard signal, so this does not justify a
new Main exit-latency counterfactual.

Updated Main decision:

- Do not build a July/2022 shock guard.
- Do not directly edit the losing drawdown names.
- Record Main MDD as honest latest-basis negative evidence unless a new
  decision-time observable failure mode is identified.
