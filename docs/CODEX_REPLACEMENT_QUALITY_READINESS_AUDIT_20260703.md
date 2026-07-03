# Replacement-Quality Readiness Audit - 2026-07-03

## Context

The fixed-book Concentrated cap/replacement counterfactual produced the first
replay-stage result that appeared to clear the Concentrated 50% CAGR / -25% MDD
research target on both the reference and latest books.

This document records the follow-up readiness audit requested after external
red-team review. The audit checks whether the result is ready for a policy hook,
broker A/B acceptance, or fullrun. It is not.

## Verdict

Status: `blocked`

Do not run a fullrun. Do not treat the current hook as accepted. Do not promote
to production.

Two blockers were confirmed:

1. The fixed-book counterfactual control does not reproduce the official
   broker ledger after cash interest is accounted for.
2. The default-OFF policy hook fires far more broadly than the fixed-book
   winning counterfactual.

The hypothesis remains interesting, but it must be narrowed and remeasured.

## Run 28616190134 Readiness Audit

Inputs:

- Official metrics:
  `artifacts/run_28616190134_download/official-broker-ledger-global_alpha_universe-28616190134/outputs/account_evaluation/official_metrics.json`
- Counterfactual summary:
  `outputs/p4_cap_replacement_broker_counterfactual_28616190134_cash_carry_aligned/summary.json`
- Hook target book:
  `outputs/replacement_quality_hook_probe_286/official_concentrated_target_book.csv`
- Fixed swaps:
  `outputs/p4_cap_replacement_broker_counterfactual_28616190134_cash_carry_aligned/rank_top15_and_revenue_ge10/swaps.csv`

Control reproduction:

| Metric | Official | Expected official + cash interest | Counterfactual control |
|---|---:|---:|---:|
| CAGR | 44.5272% | 44.8665% | 49.3378% |
| MaxDD | -23.2682% | n/a | -23.0181% |
| Ending capital | 1,356,612.43 | 1,379,322.55 | 1,710,548.39 |

Delta after cash-interest adjustment:

- CAGR: +4.4713pp
- Ending capital: +331,225.84
- Ending capital delta pct: +24.0137%

This is not a cash-carry accounting difference. The control is measuring a
different replay substrate. The counterfactual summary points to a locally
rebuilt replay price cache:

`outputs/p4_cap_replacement_broker_counterfactual_28616190134/cache_prices`

That price-cache or replay-input mismatch must be resolved before using the
result as acceptance evidence.

Swap scope:

| Item | Count |
|---|---:|
| Fixed-book swaps | 17 |
| Hook swaps | 71 |
| Overlap | 1 |
| Fixed only | 16 |
| Hook only | 70 |
| Hook overlap share | 1.41% |

The hook is not implementing the same hypothesis as the fixed-book
counterfactual. It fires almost every eligible month because the event gate is
month-level rather than rejected-ticker-level.

## Run 28436307420 Readiness Audit

Inputs:

- Official metrics:
  `artifacts/fullrun_28436307420/official/outputs/account_evaluation/official_metrics.json`
- Counterfactual summary:
  `outputs/p4_cap_replacement_broker_counterfactual_28436307420_cash_carry_aligned/summary.json`
- Hook target book:
  `outputs/replacement_quality_hook_probe_286/official_concentrated_target_book.csv`
- Fixed swaps:
  `outputs/p4_cap_replacement_broker_counterfactual_28436307420_cash_carry_aligned/rank_top15_and_revenue_ge10/swaps.csv`

Control reproduction:

| Metric | Official | Expected official + cash interest | Counterfactual control |
|---|---:|---:|---:|
| CAGR | 47.4631% | 47.7606% | 48.8322% |
| MaxDD | -24.0781% | n/a | -23.7934% |
| Ending capital | 1,559,214.02 | 1,581,597.19 | 1,664,522.90 |

Delta after cash-interest adjustment:

- CAGR: +1.0716pp
- Ending capital: +82,925.71
- Ending capital delta pct: +5.2432%

This is smaller than the 286 mismatch but still above the readiness threshold.
The hook comparison for this run is not fully valid because the available hook
probe target book was generated for 286. A 284-specific hook probe is required
before using hook-vs-fixed overlap for 284.

## Required Next Work

1. Resolve control reproduction before any acceptance claim.
   - Re-run the counterfactual against the exact official replay substrate, or
     compute cash-carry on the official broker ledger directly.
   - The control must reproduce official plus cash interest within the numeric
     readiness tolerance.

2. Narrow the policy hook to event matching.
   - The fixed-book hypothesis swaps a missed leader event.
   - The hook currently swaps when any same-month cap/replacement rejection
     exists and a qualifying candidate is present.
   - The hook must match the rejected ticker or a persisted event id, not just
     the month.

3. Produce run-specific hook probes.
   - Do not reuse the 286 hook target book to judge 284 overlap.
   - Each official book needs its own generated hook probe before comparing
     fixed vs hook swaps.

4. Keep production blocked.
   - `pit_universe_label_clean=false` remains a production blocker.
   - The replacement-quality work remains research-only.

## Acceptance Gate Before Fullrun

The next broker A/B or fullrun is allowed only after all of the following are
true:

- Official control is reproduced after cash-carry adjustment.
- Hook swap list is a subset of, or tightly explained by, the fixed-book event
  list.
- The candidate still clears Concentrated CAGR >= 50% and MDD >= -25%.
- OOS/IS and multi-era gates do not deteriorate.
- Main is non-regressed.
- No live trading or production activation is enabled.
