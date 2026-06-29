# Concentrated Cash-Funded Early Entry Hook Result - 2026-06-29

## Summary

This PR adds a default-OFF, Concentrated-only policy hook that deploys a small
cash-funded early-entry position when the top unheld PIT candidate is strong
enough.

The hook is a policy implementation of the successful cheap broker A/B path from
PR #208, but with two additional constraints discovered during hook validation:

- the added position is non-sticky, so it does not become a prior holding unless
  the core policy selects it later;
- the top unheld candidate must have `breakout_setup_quality_score >= 0.50`;
  if the top candidate fails that filter, the date is blocked instead of
  falling back to a lower-ranked candidate.

## Implementation

Changed file:

- `tools/run_alphaops_vnext_policy_replay.py`

New default-OFF phase:

- `PHASE_CONCENTRATED_CASHFUNDED_EARLY_ENTRY_ENABLED`

Default parameters:

- signal: `future_winner_scout_score`
- add weight: `0.058`
- minimum breakout quality: `0.50`
- crisis deployment: disabled by default

Environment overrides:

- `R1000_CONC_CASHFUNDED_EARLY_ENTRY_SIGNAL`
- `R1000_CONC_CASHFUNDED_EARLY_ENTRY_ADD_WEIGHT`
- `R1000_CONC_CASHFUNDED_EARLY_ENTRY_MIN_BREAKOUT_QUALITY`
- `R1000_CONC_CASHFUNDED_EARLY_ENTRY_ALLOW_CRISIS`

Safety constraints:

- default OFF;
- Concentrated only;
- cash-funded only;
- selected tickers and existing stock weights are preserved;
- no sale, replacement, or score mutation;
- explicit forward-return and audit-label signal names are rejected;
- early-entry rows are marked
  `concentrated_cashfunded_early_entry_non_sticky=True`.

## Broker Evidence

Reference artifact:

- `artifacts/28074476465`

Generated target-book broker replay:

- fill mode: `next_close`
- metric mode: `broker_ledger_next_close`
- window: `2019-06-03` to `2026-06-25`
- years: `7.060917180013689`

Same-local-cache baseline:

| Portfolio | CAGR | MaxDD | Sharpe | Avg cash | Trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| Concentrated baseline | 47.90% | -26.46% | 1.451 | 42.67% | 583 |

Final hook default:

| Portfolio | CAGR | MaxDD | Sharpe | Avg cash | Trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| Concentrated hook | 50.07% | -24.96% | 1.477 | 40.88% | 653 |

Delta versus same-local-cache baseline:

- CAGR: `+2.17pp`
- MaxDD: `+1.50pp`
- Sharpe: `+0.026`
- avg cash: `-1.79pp`
- trades: `+70`

Applied telemetry:

- applied rows: `44`
- blocked low-breakout top candidate rows: `75`
- blocked no-unheld-candidate rows: `123`

This is the first cheap Concentrated candidate in this sequence that clears both
mission thresholds in a broker-ledger target-book replay:

- Concentrated CAGR `>= 50%`;
- Concentrated MaxDD `>= -25%`.

## What Was Reused From Rejected Paths

Rejected paths still contributed useful parts:

- broad gross-floor was rejected, but the idea of using idle cash as fuel was
  retained in a bounded cash-funded entry;
- uncapped score sizing was rejected, but the signal-ranking idea was retained
  without changing existing selected weights;
- broad hold-duration rescue was rejected, but the non-sticky overlay prevents a
  temporary scout entry from becoming a permanent prior holding;
- broad reentry timing remains a possible later combination, but is not included
  here to keep attribution clean.

## 2-Week RS Follow-Up

The 2-week RS follow-up has been completed and rejected as a policy input.

What was tested:

- `2w` RS telemetry was added to the same PIT price-cache path used for `1w`,
  `1m`, `3m`, and `6m`;
- `tools/run_rs_2w_entry_timing_screen.py` found that `2w_rs_top_half` was a
  plausible timing/tie-breaker candidate on forward-label diagnostics;
- `tools/run_rs_timing_tiebreaker_broker_ab.py` then tested the candidate by
  removing failing cash-funded early-entry rows and returning that weight to
  cash before broker-ledger replay.

Broker A/B result on the clean 7Y integration artifact:

| Arm | CAGR | MaxDD | Sharpe | Decision |
|---|---:|---:|---:|---|
| baseline | 50.07% | -24.96% | 1.477 | keep |
| `rs2w_positive` | 49.88% | -24.82% | 1.475 | reject: lower CAGR |
| `rs2w_is_median` | 49.52% | -25.60% | 1.478 | reject: lower CAGR and worse MDD |

Conclusion:

- keep 2-week RS as sidecar/diagnostic telemetry only;
- do not add it to `alphaops_score`;
- do not add a 2-week RS tie-breaker to the integration fullrun flags;
- do not rerun this path unless a materially different candidate population is
  created and independently passes a new broker-ledger A/B.

## Caveats

- This is not production promotion.
- `pit_universe_label_clean=false` still blocks production evidence.
- The broker evidence is generated target-book A/B, not a full rebuild.
- A fullrun should only be dispatched after Main has an equivalent validated
  candidate and the cheap preflight/data freshness gates are green.
