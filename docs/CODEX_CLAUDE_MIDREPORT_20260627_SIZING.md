# Claude Mid-Review Packet - 2026-06-27

## Purpose

This packet summarizes the latest Codex work after PR #191 and the current
follow-up direction. It is intended for Claude/GPT Pro review before any
expensive broker/fullrun work.

## Current System State

Repository: `wscha231/r1000-quant-engine`

Latest master observed locally:

- `d4b532d1 feat: add concentrated sizing ab screen (#191)`

Open PR state observed via GitHub:

- #191 is merged.
- #181 and #186 are docs/roadmap or review packets, green but still draft.
- #166 and #170 are default-OFF alpha infra but have already been measured as
  too small to close the main gaps by themselves.
- Many older 2026-06-17 safety-only drafts remain open. They are not the
  current alpha critical path and should be triaged separately rather than
  mixed with the sizing work.

Clean 7Y artifact used for analysis:

- `artifacts/28074476465/outputs`
- Official metric mode: `broker_ledger_next_close`
- Broker start: `2019-06-03`
- Years: `7.0554`
- Calendar trading days: `1778`
- `ready_for_policy_replay=true`
- `pit_universe_label_clean=false`
- `production_promotion_allowed=false`

Portfolio metrics from `account_evaluation/official_metrics.json`:

| Portfolio | CAGR | MDD | Sharpe | Avg Cash | Latest Cash | Status |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Main | 33.15% | -26.02% | 1.219 | 26.70% | 15.67% | research only, canonical targets not met |
| Concentrated | 46.24% | -25.82% | 1.421 | 42.18% | 6.12% | research only, canonical targets not met |

Interpretation:

- The clean 7Y window work is functionally solved for research evidence.
- Production remains blocked by PIT universe membership discipline.
- Both sleeves still miss the canonical mission after clean 7Y:
  - Main needs MDD improvement and some CAGR lift.
  - Concentrated needs roughly +3.76pp CAGR and MDD repair inside -25%.

## Recent Completed Work

### PR #188 - SHAKEOUT applied screen

Result:

- SHAKEOUT guard was no-op on the clean 7Y artifact (`suppressed_rows=0`).
- No broker A/B was justified.

Lesson:

- The alpha idea may still be valid, but the current production predicates did
  not fire on this artifact. Do not spend a fullrun here until applied-count is
  nonzero.

### PR #189 - Leadership persistence and hold-duration screens

Result:

- Leadership persistence screen found input fidelity gaps:
  missing RS/leader/smart-money fields and missing rejected-by-reason data.
- Broad hold-duration rescue was negative:
  - Main PIT leader candidates: 209, positive rate 45.93%, mean 126d excess
    -2.81pp.
  - Concentrated PIT leader candidates: 83/82 matched, positive rate 48.78%,
    mean 126d excess -4.02pp.

Lesson:

- Broad "hold leaders longer" is not supported. Discard broad rescue.
- Any future hold/rescue work must be narrower and supported by live
  applied-count plus OOS evidence.

### PR #190 - Sizing signal screen

Result:

- Concentrated score-family signals were positive at audit-label level.
- `alphaops_vnext_score` was strongest:
  - Full high-minus-low: +7.34pp
  - OOS high-minus-low: +14.99pp
  - OOS Spearman: 0.278

Lesson:

- Sizing/weight allocation is the best current alpha lead for Concentrated.
- It is still audit-label evidence only, not broker evidence.

### PR #191 - Concentrated sizing A/B target-book screen

Added:

- `tools/run_concentrated_sizing_ab_screen.py`
- `tests/concentrated_sizing_ab_screen_smoke.py`

Scope:

- Research-only.
- Keeps selected names and cash/gross stock exposure fixed.
- Reweights only existing Concentrated target-book stocks using score-family
  variants.
- Uses `period_forward_return` as audit label only.
- Does not run broker replay and does not mutate policy.

Real artifact result on `artifacts/28074476465/outputs`:

- `candidate_count=6`
- `next_action=design_broker_sizing_ab`
- Recommended variant:
  - signal: `alphaops_vnext_score`
  - variant: `blend75_rank_power1_5`
  - full audit-label CAGR proxy delta: +0.548pp
  - full audit-label MDD proxy delta: -0.897pp
  - OOS audit-label CAGR proxy delta: +7.621pp
  - OOS audit-label MDD proxy delta: -0.447pp
  - max single weight observed: 36.34%

Interpretation:

- This is enough to justify a default-OFF broker sizing A/B hook.
- It is not enough to claim performance improvement.
- The recommended variant can exceed the current 30% Concentrated single-name
  cap, so it must stay research-only until broker MDD and drawdown composition
  are measured.

## Current Follow-Up PR Direction

Branch:

- `codex/concentrated-score-sizing-reweight-20260627`

Code touched:

- `tools/run_alphaops_vnext_policy_replay.py`
- `tests/alphaops_vnext_policy_replay_smoke.py`
- this report file

Implemented hook:

- `PHASE_CONCENTRATED_SCORE_SIZING_REWEIGHT_ENABLED`
- default OFF
- Concentrated only
- Runs after existing final caps/filters and before final row emission
- Preserves selected tickers and gross stock exposure
- Does not alter cash exposure
- Reweights by:
  - signal: `alphaops_vnext_score`
  - blend: `0.75`
  - rank power: `1.5`
- Emits telemetry:
  - `pre_concentrated_score_sizing_reweight_weight`
  - `concentrated_score_sizing_reweight_status`
  - `concentrated_score_sizing_reweight_signal`
  - `concentrated_score_sizing_reweight_blend`
  - `concentrated_score_sizing_reweight_rank_power`
  - `concentrated_score_sizing_reweight_delta`
  - `concentrated_score_sizing_reweight_cap_exceeded`

Validation already run:

- `python tests/alphaops_vnext_policy_replay_smoke.py`
- `python -c compile(...)` for touched Python files
- `python tools/run_pr_validation.py --only alphaops_vnext_policy_replay_smoke`

Attempted but intentionally stopped:

- Running full policy replay on the artifact with `--skip-broker-replay` took
  longer than 3 minutes and was killed. This path is still much cheaper than a
  fullrun, but not cheap enough to use casually while iterating.

## Review Questions for Claude

1. Is a post-cap, default-OFF Concentrated reweight hook the right place to
   translate PR #191's target-book result into a broker A/B candidate?
2. Should the research hook allow cap breaches up to the observed ~36.3%, or
   should the broker A/B first test a capped version that respects the 30%
   single-name cap?
3. Is the current telemetry sufficient to detect whether the sizing lever
   actually fired and whether cap breaches are driving any apparent edge?
4. Should the next broker A/B compare exactly one variant
   (`blend75_rank_power1_5` / `alphaops_vnext_score`) or include the safer
   `blend50_rank_power1_5` variant as a second arm?
5. Should a cheap replay harness be added specifically for this sizing hook,
   rather than using the full `run_alphaops_vnext_policy_replay.py` path?

## Recommended Next Step

If this PR passes CI:

1. Keep it default OFF on master.
2. Add a lightweight broker A/B harness or use an existing broker replay path to
   compare:
   - baseline
   - `blend75_rank_power1_5` / `alphaops_vnext_score`
   - optionally `blend50_rank_power1_5` as a lower-cap-pressure variant
3. Acceptance must be broker-ledger only:
   - Concentrated CAGR improvement should be meaningful toward the +3.76pp gap.
   - MDD must not worsen beyond gate; current Concentrated is already -25.82%.
   - OOS must not collapse.
   - `pit_universe_label_clean=false` continues to block production promotion.

## Non-Negotiables

- No live trading.
- No production mutation.
- No proxy 8Y/10Y work.
- No partial-year annualized 2026 proof.
- No promotion claim until PIT universe membership is clean and broker-ledger
  evidence passes the agreed contract.
