# Run287 Main Growth Fixed-Policy Embargo Result — 2026-07-18

## Decision

`REJECT_EMBARGO_FOLD`

Close the `growth_confirmation_top_quintile_tilt10` Main lane. Do not build the
proposed accepted-time balance-sheet veto on top of this arm. The recent fixed
policy segment had negative incremental CAGR after a complete 126-session
embargo, so adding a veto would be post-failure retuning of the same arm.

## Measurement

- Baseline and candidate are the existing cash-carry, 25 bps, integer-share,
  next-close broker-ledger curves. No replay or fullrun was dispatched.
- The signal formula and 10% tilt remain fixed across both segments.
- Each segment starts only after 126 common trading sessions following its
  training cutoff. The two test segments do not overlap.
- Target-book provenance checked five available/source-date columns. Future-row
  violations were `0`; `used_forward_return_in_ranking=false`.
- This is fixed-policy embargoed segment evidence. It is not represented as a
  per-fold model-retraining result.

| Fold | Embargo | Test | Sessions | dCAGR | dSharpe | dMDD diagnostic | Verdict |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| post-2022 | 2023-01-03 to 2023-07-05 | 2023-07-06 to 2024-06-28 | 248 | +9.4606 pp | +0.2447 | +1.7075 pp | PASS |
| post-2024H1 | 2024-07-01 to 2024-12-27 | 2024-12-30 to 2026-07-02 | 377 | -0.1993 pp | +0.0031 | -0.1869 pp | REJECT |

The second fold fails the preregistered requirement that every embargoed fold
have positive incremental CAGR. This agrees with the prior era-attribution
warning: the apparent full-period improvement was not temporally uniform.

## Safety and next action

- Target books, cash, positions, orders, production, and live trading were not
  changed.
- Existing untracked outputs were preserved.
- No threshold, fold endpoint, ticker, or failed month was adjusted after
  observing the result.
- A future accepted-time balance-sheet signal may be screened only as a new,
  standalone preregistered source. It may not be used to reopen or retune this
  rejected growth-tilt combination without the registry's semantic/coverage
  exception.

## Evidence

- `docs/run287_growth_embargo_contract_v1.json`
- `tools/audit_run287_growth_embargo.py`
- `tests/run287_growth_embargo_smoke.py`
- `outputs/run287_growth_embargo_walk_forward_20260718/summary.json`
- `outputs/run287_growth_embargo_walk_forward_20260718/fold_results.csv`
