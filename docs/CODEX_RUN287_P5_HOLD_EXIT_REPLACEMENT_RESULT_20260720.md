# Run287 P5 hold, exit, and replacement result - 2026-07-20

## Decision

The single preregistered `leadership_persistence_v2_strict` arm is rejected as
`REJECT_NO_OP`. It retained zero incumbents in both generated books, so it did
not change CAGR, MDD, Sharpe, turnover, or fees. The arm must not be retuned on
this book and window unless required component coverage increases by at least
5 percentage points or the signal semantics genuinely change.

The five-value sell taxonomy is retained as operating integrity
infrastructure. It now follows sell orders from order preview through pending,
filled, rejected, and lifecycle-settlement ledger records. This does not
promote the rejected hold rule or change any current stock target.

## Preregistered arm

- Policy: `leadership_persistence_v2_strict`.
- Strict incumbent evidence: top-decile three-month benchmark RS, price above
  MA200, approved leader tier, positive sector and industry-group strength,
  canonical HOLD state, and no thesis, risk, stale-data, PIT, or lifecycle
  break.
- Challenger: already selected by the frozen selector, evidence-complete,
  lifecycle/risk-clear, trend/RS alive, and no worse concentration.
- Fixed cost-adjusted gap:
  `max(0.22, 1.10 * cross-sectional score sigma) + 0.005`.
- No threshold grid and no forward-return field use.
- Execution: integer shares, next close, 25 bps per side, maximum lag 7,
  DGS3MO cash carry. Sensitivities used 50 and 100 bps.
- Validation: Full/OOS/OOS2, 126-session embargo, 21/63/126-session exit
  counterfactuals, holding duration, 63-session churn, contribution
  concentration, and exact control parity.

## Frozen evidence

- Main target SHA-256:
  `356bac22ec55090b2d2da882c7505b1460973227639a5d0b7a4c59c25c0ccff9`.
- Concentrated target SHA-256:
  `848c1bac00985ab0b132794ee3e1c2942c1561d2f728b0a89778bd6c4e63660e`.
- Candidate artifact SHA-256:
  `7ffa0b27382d303008ffca55878b259ccf7f11beaee28be6f1e4653c30e97989`.
- Restored scored-candidate cache SHA-256:
  `3112bed1e7fdf90934043971f6e4ed322a594fe5d992d1621703c3ea9ef3ed96`.
- DGS3MO SHA-256:
  `d5f8c9bf116a918500107361c971e4de78ddf7835070511745c47a343b693490`.
- Security lifecycle SHA-256:
  `b70dde26b9ad404dfffdf792dcd6e21ed6d16563746ca44c8bc8e3dc6fb76c8a`.
- Candidate cache: 47,435 exact ticker-date rows. The
  `period_forward_return` column was physically excluded before policy use.
- Local machine-readable result:
  `_tmp_tests/p5_hold_exit_actual_v2_20260720/summary.json`.

## Exact result

| Portfolio | Control and treatment CAGR | MDD | Sharpe | Applied holds | Verdict |
| --- | ---: | ---: | ---: | ---: | --- |
| Main | 34.4032% | -25.3629% | 1.2757 | 0 | `REJECT_NO_OP` |
| Concentrated | 49.0968% | -22.9560% | 1.5002 | 0 | `REJECT_NO_OP` |

Control parity passed to `1e-6` for metrics and exactly for trade count, fees,
and trade CSV SHA-256. All Full, OOS, OOS2, embargo, and 25/50/100 bps deltas
were zero. No 21/63/126-session counterfactual event existed because there was
no protected replacement test.

Historical holding diagnostics also expose the intended bottleneck: Main
completed 1,075 lots with median holding 33 days, zero completed lots held at
least 365 days, and 42 exit/re-entry events within 63 sessions. Concentrated
completed 453 lots with median holding 32 days, zero completed lots held at
least 365 days, and 35 such churn events. These are diagnostics, not proof that
blindly extending holds improves returns.

## Root cause and next admissible step

Every changed-book incumbent failed before the leadership test. Main had 506
departures missing `rs_sector_3m` and 19 without an exact scored-candidate row;
Concentrated had 259 and 11 respectively. Missing evidence correctly remained
unprotected and is classified as `EXECUTION_RECONCILIATION`, not a thesis
failure. Substituting another column after observing this result would change
the preregistered signal and is prohibited in P5.

P6 must trace why historical sector RS was not materialized, measure coverage
for every candidate-gate axis, verify finite/nonconstant prediction heads and
stale-column behavior, and make every exclusion reason machine-readable. It
may reopen a hold experiment only after the registry's coverage or semantic
change rule passes; it must not silently impute this missing field.

## Safety and do-not-repeat

- `do_not_repeat`:
  `leadership_persistence_v2_strict+generated_books+2019-05-31_2026-07-10+25bps+dgs3mo`.
- Do not tune the score gap, RS threshold, MA window, or leader tiers to make
  this exact arm fire.
- Do not call missing data a thesis break and do not classify BUY records as a
  sell event.
- Do not infer a candidate pool from the selected book.
- Repository pytest passed `129/129`; full Tier-1 PR validation passed
  `185/185` in `280.63s`.
- Fullrun executed: false. Production enabled: false. Live trading enabled:
  false.
