# Run287 P6 candidate-gate and model-stability result - 2026-07-20

## Decision

P6 operating observability is accepted, but the only preregistered selector
remediation is rejected as `REJECT_OOS_AND_COST`. The system now exposes
candidate data completeness, neutralization, six-head activity, stale-column
integrity, rank stability, a common rejection taxonomy, and post-decision
outcomes. It does not automatically repair `rs_sector_3m`, change a gate, or
change either operating target.

The official headline baseline therefore remains Main `34.4032% / -25.3629%`
and Concentrated `49.0968% / -22.9560%`. The lower regenerated control levels
in the bounded A/B end at the common candidate decision date 2026-05-29 and
must not replace that official baseline.

## Frozen inputs and integrity

- Original candidate artifact: 47,435 unique ticker-date rows, 85 decision
  dates, 981 tickers, SHA-256
  `7ffa0b27382d303008ffca55878b259ccf7f11beaee28be6f1e4653c30e97989`.
- Restored scored-candidate cache: 237,175 rows across five identical policy
  variants, deduplicated without conflicts to 47,435 rows, SHA-256
  `3112bed1e7fdf90934043971f6e4ed322a594fe5d992d1621703c3ea9ef3ed96`.
- Main and Concentrated target SHA-256:
  `356bac22ec55090b2d2da882c7505b1460973227639a5d0b7a4c59c25c0ccff9`
  and
  `848c1bac00985ab0b132794ee3e1c2942c1561d2f728b0a89778bd6c4e63660e`.
- Future-return columns were physically excluded from decision decomposition.
  `used_forward_return_for_selection=false`.
- Current bounded 989-ticker audit found six of six active prediction heads
  finite, nonzero, nonconstant, deterministic, and passthrough-correct. It
  found no silent-zero fallback or suffix collision. Old `pred_*` columns were
  detected and removed before the fresh joins.
- The prior July 12 score snapshot had only four constant-zero heads and is
  not a valid six-head reference. Distribution drift is consequently
  `UNDERPOWERED_NO_PRIOR_ACTIVE_SIX_HEAD_SNAPSHOT`, not zero and not passed.
- All 989 current tickers have at least one neutralized model feature and a
  critical missing field; zero are fully data-complete. Missing remains
  neutral, so complete-versus-neutralized performance is underpowered.
- Sector-neutral outcomes were computed cross-sectionally. Sector-ETF excess
  is `BLOCKED_MISSING_PINNED_SECTOR_ETF_CACHE`; no network substitute or
  mutable ETF history was used.

## Existing selector evidence

Against a nearest-score-rank matched control, selected names had positive mean
return deltas in every tested portfolio, window, and horizon:

| Window | Portfolio | 21D | 63D | 126D | 252D |
| --- | --- | ---: | ---: | ---: | ---: |
| Full | Main | +1.21pp | +4.29pp | +6.22pp | +8.35pp |
| Full | Concentrated | +2.01pp | +4.54pp | +12.08pp | +16.22pp |
| OOS | Main | +4.89pp | +11.89pp | +19.54pp | +12.84pp |
| OOS | Concentrated | +3.27pp | +10.06pp | +34.30pp | +15.77pp |
| OOS2 | Main | +3.09pp | +7.93pp | +11.48pp | +6.19pp |
| OOS2 | Concentrated | +3.02pp | +5.82pp | +17.69pp | +4.68pp |

This is evidence that the nonlinear selector and its constraints add value;
it is not a causal claim about any single input. Raw score Spearman IC was
near zero or slightly negative at 21/63 days and positive at 126/252 days.
That divergence is why a scalar-score shortcut must not replace the complete
selection process.

Monthly rank stability remains a bottleneck. Across 84 adjacent decision
pairs, mean score Spearman was `0.6358`, top-10 overlap `33.57%`, and top-30
overlap `42.62%`. P7 must surface these alongside turnover and fees rather
than treating a changing top list as automatically better selection.

## Single remediation A/B

The only permitted remediation materialized missing
`rs_sector_3m = mom_3m - same-date sector mean`. Coverage rose from 0% to
100% for 47,435 cells, existing finite values were preserved, and no future
return was used. The repaired artifact SHA-256 is
`c325dd3845711643a82736e35ccdfb8e6727102a91b7e4c1e7913c79fda522b9`.

It materially changed the selector rather than being a no-op: 44 of 85 Main
and 35 of 85 Concentrated decisions changed. Average cash fell from 22.18% to
20.01% in Main and from 36.87% to 29.30% in Concentrated. That additional
exposure did not earn its risk or cost.

| Portfolio | 25bp control | 25bp treatment | dCAGR | dMDD | dSharpe |
| --- | --- | --- | ---: | ---: | ---: |
| Main | 30.9473% / -28.6871% | 30.2741% / -29.8857% | -0.67pp | -1.20pp | -0.039 |
| Concentrated | 45.2435% / -33.4563% | 43.4994% / -35.4483% | -1.74pp | -1.99pp | -0.084 |

Main OOS/OOS2 dCAGR was `-2.74pp / -2.53pp`; Concentrated was
`-5.58pp / -4.28pp`. Main 100bp dCAGR was `-0.98pp`; Concentrated was
`-3.04pp`. Added fees at 25bp were `$1,928.49` and `$4,157.86` respectively.
Both portfolios failed Full, OOS, OOS2, 100bp, and turnover-cost gates.

## Operating changes retained

- One canonical same-date sector-relative-strength helper replaces duplicate
  pipeline logic and can create an explicit research sidecar.
- The daily decision frame and six-head audit expose `data_complete`,
  `critical_data_complete`, `neutralized_feature_count`,
  `critical_missing_fields`, and `missing_neutral_applied`.
- Stale prediction suffix collisions fail closed; ordinary stale heads are
  removed and reported before fresh joins.
- The historical diagnostic emits eight independent selection axes, Full/OOS/
  OOS2 21/63/126/252-day outcomes, SPY/QQQ and sector-neutral comparisons,
  selected-versus-matched controls, IC/hit rate, rank stability, and the common
  rejection taxonomy.
- The rejected repair remains sidecar-only and is not called by the daily
  selector.

## Closure and safety

- `do_not_repeat`:
  `canonical_sector_relative_strength+materialize_missing_rs_sector_3m+alphaops_vnext_regenerated_main15_concentrated5+2019-05-31_2026-05-29`.
- Do not lower the cash, trend, quality, name, or sector gates to rescue the
  repair, and do not retune its definition on this window.
- The lane may reopen only under the registry rule: at least five percentage
  points of genuinely new component coverage or a documented semantic change.
- Local evidence:
  `_tmp_tests/p6_candidate_gate_actual_v2_20260720/summary.json`,
  `_tmp_tests/p6_current_score_stack_actual_20260720/manifest.json`, and
  `_tmp_tests/p6_sector_rs_broker_ab_20260720/summary.json`.
- Repository pytest passed `129/129`; full Tier-1 PR validation passed
  `187/187` in `730.57s`.
- Fullrun executed: false. Production enabled: false. Live trading enabled:
  false.
