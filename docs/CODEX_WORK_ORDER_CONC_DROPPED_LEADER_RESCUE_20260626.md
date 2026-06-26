# Codex Work Order: Concentrated Dropped-Leader Rescue Candidate

## Status

Research-only candidate design. Do not treat this as production promotion, target
mutation, live trading, or a claim that the CAGR/MDD target has been achieved.

Clean 7Y baseline remains the reference:

- Run: `28074476465`
- Main: `33.15% CAGR / -26.02% MDD`
- Concentrated: `46.24% CAGR / -25.82% MDD`
- Metric mode: `broker_ledger_next_close`
- Production blocker: `pit_universe_label_clean=false`

The current priority is Concentrated CAGR. The gap is about `+3.76pp` to the
`50%` target, while MDD is already close but slightly outside the `-25%` target.

## Why This Candidate

The merged fusion review pipeline now has real producer compatibility:

- `right_tail_drop_counterfactual_audit/drop_counterfactuals.csv` is loaded.
- `right_tail_drop_counterfactual_audit/segment_summary.csv` is loaded.
- `used_forward_return_in_ranking=false`
- `policy_eligible=false`

Local replay of run `28074476465` after the compatibility fix produced:

- fusion review candidates: `83`
- Concentrated fusion candidates: `30`
- segment review candidates: `15`
- Concentrated cap/replacement + drop-counterfactual overlap: `4`

The raw name overlap is not strong enough to ship:

| ticker | predicate overlap | 126d excess vs SPY |
| --- | --- | ---: |
| NVDA | cap/replacement miss + drop high signal | `+20.51%` |
| QRVO | cap/replacement miss + drop high signal | `+21.47%` |
| DXCM | cap/replacement miss + drop high signal | `-19.29%` |
| ON | cap/replacement miss + drop high signal | `-35.81%` |

Therefore this work order must not hardcode any ticker, date, sector, or theme.
The valid candidate is a forward-blind rule shape that must be selected on an
in-sample window and validated on an out-of-sample window.

## Candidate Shape

Implement one default-OFF research lever:

`PHASE_CONC_DROPPED_LEADER_RESCUE_ENABLED`

The lever may only affect the Concentrated portfolio. It may not change Main,
cash policy, production gates, workflow dispatch, universe membership, target
mission thresholds, or live trading.

The candidate should rescue a previously dropped or missed Concentrated leader
only when the name still has PIT-visible leadership at the decision date.

Minimum ex-ante predicate:

- portfolio is `concentrated`
- candidate has a prior drop/miss event in the current replay state
- candidate rank percentile at decision date `>= 0.80`
- signal stack count at decision date `>= 7`
- 3-month benchmark relative strength `> 0`
- 6-month benchmark relative strength `> 0`
- price is above the relevant trend filter when available
- risk-entry block is not active
- stale mega-leader block is not active
- no future return, realized PnL, or winner label is used in live ranking

The lever should act as a narrow replacement/cap rescue, not a broad score
bonus. Prefer one of these mechanics:

1. replacement-gap credit for qualifying dropped leaders, capped and telemetry
   visible; or
2. a small cap-overflow review slot that can only admit a qualifying dropped
   leader when it beats the weakest held name by the normal effective gap.

Do not use broad gross-floor, broad cash reduction, broad sector boost, or broad
alphaops score bonus in this work order.

## Segment Selection Discipline

Do not hardcode `Capital Goods - Machinery`, `Construction & Engineering`,
`bear`, or any observed winning segment into the policy.

Instead, if segment scoping is used, it must be selected from training-only
diagnostics and frozen before OOS measurement.

Allowed segment screen for an IS-only training fold:

- subset is `high_signal`
- observations `>= 3`
- completed 126d rows `>= 3`
- positive 126d excess rate `>= 0.66`
- average 126d excess vs SPY `> 0`

Then evaluate the frozen segment rule on the OOS fold. The OOS report must show
whether the selected segment screen generalizes. If no segment survives the
training screen, the lever must emit `status=no_segment_candidate` and remain
inactive.

## Required Outputs

Add telemetry to the target/replay outputs so a no-op cannot pass:

- `conc_dropped_leader_rescue_enabled`
- `conc_dropped_leader_rescue_applied`
- `conc_dropped_leader_rescue_reason`
- `conc_dropped_leader_rescue_candidate_rank_percentile`
- `conc_dropped_leader_rescue_signal_stack_count`
- `conc_dropped_leader_rescue_segment_allowed`
- `conc_dropped_leader_rescue_replacement_gap_credit`
- `conc_dropped_leader_rescue_selected_segment_source`

The A/B verifier must be able to count applied rows. `applied_count == 0` is a
no-op and must not be interpreted as a failed alpha result.

## Measurement Protocol

Use only clean 7Y research evidence. Do not run a new fullrun until cheap local
screens show applied rows and target-book deltas.

Step 1: cheap target-book screen

- default OFF reproduces baseline target books exactly
- env ON produces `applied_count > 0`
- env ON changes Concentrated target books
- Main target books remain unchanged
- no future return columns are read by the live predicate

Step 2: broker-ledger A/B screen

- metric mode is `broker_ledger_next_close`
- run OFF and ON from the same artifact/source cache
- report Concentrated CAGR, MDD, Sharpe, turnover, and replacement count
- report Main unchanged or explicitly outside scope

Step 3: acceptance gate

- Concentrated CAGR improves by at least `+0.50pp`, or a smaller gain is
  accompanied by clear winner-capture improvement and no MDD degradation.
- Concentrated MDD does not degrade beyond `-0.50pp`.
- turnover increase is explained and not broad churn.
- applied rows are not concentrated in a single ticker or a single date.
- winner capture and theme-leader capture do not regress.

Step 4: overfit guard

- IS-trained segment screen must be measured on OOS.
- A result that only works in one segment, one ticker, or one event is a review
  signal, not a ship signal.
- OOS/IS and leave-top-winner-out are audit triggers, not automatic rejection,
  but skill-vs-luck evidence must be shown before any ready-for-human-review
  label.

## Explicit Rejections

Do not implement these under this work order:

- ticker-specific rescue for `NVDA`, `QRVO`, `DXCM`, `ON`, `VRT`, `GEV`, `WCC`,
  or any other observed name
- date-specific exception
- segment hardcoding from the full 7Y outcome table
- broad score bonus
- broad gross-floor/cash change
- production promotion
- live trading
- proxy 8Y/10Y work

## Expected Interpretation

This is a Concentrated CAGR candidate. It is not expected to fix Main MDD.

If this lever fails, keep any useful telemetry and discard the policy. The next
candidate should be selected from the same fusion queue, not by adding another
broad safety gate or lowering cash indiscriminately.
