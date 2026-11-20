# Actual-Results Hold Screen - 2026-06-29

## Purpose

This document records the next Concentrated CAGR candidate after:

- broad hold-leaders-longer failed;
- cap-safe score-sizing failed;
- uncapped sizing was rejected as a policy candidate;
- Main MDD work moved to governance/risk-cap framing.

The hypothesis is narrower:

> A dropped Concentrated prior holding should sometimes be retained longer when
> it is still a PIT leader and has positive actual-results evidence at the
> decision date.

This is research-only. It does not change target books, scoring, live trading,
or production gates.

## New Tool

Added:

- `tools/run_actual_results_hold_screen.py`
- `tests/actual_results_hold_screen_smoke.py`

Extended:

- `tools/run_hold_duration_leak_screen.py`
  - carries prior `actual_results_score`, `eps_revision_score`,
    `revision_score`, and `event_reaction_score` into drop rows.
- `tools/run_pr_validation.py`
  - registers `actual_results_hold_screen_smoke`.

## Method

The screen reads:

- official target book;
- `entry_exit_timing_audit/premature_sell_counterfactual.csv`;
- prior target-book row fields at the last decision date before a name was
  dropped.

Primary predicate:

```text
actual_results_positive_pit_hold =
  pit_leader_hold_candidate
  AND prior_actual_results_score > 0
```

where `pit_leader_hold_candidate` is inherited from the existing drop-leak
screen:

- prior weight >= 2%;
- holding state was `HOLD`;
- leader tier in `DUAL_LEADER` or `SECTOR_LEADER`;
- 3m and 6m benchmark RS positive;
- price above MA200.

Forward 126d excess is audit label only. It is not used in live ranking.

## Clean7Y Artifact Result

Command:

```powershell
python tools/run_actual_results_hold_screen.py --latest-run artifacts/28074476465/outputs --portfolio concentrated --output-dir artifacts/28074476465/actual_results_hold_screen_20260629
```

Evidence availability:

- `actual_results_score` column present: true
- `actual_results_score` positive rows in target book: 254
- joined drop rows: 190

Primary predicate result:

| Split | Rows | Positive Rate | Mean 126d Excess | Median 126d Excess |
|---|---:|---:|---:|---:|
| full | 52 | 53.85% | +10.39% | +3.45% |
| IS | 40 | 55.00% | +10.87% | +5.50% |
| OOS | 12 | 50.00% | +8.80% | +0.15% |

Verdict:

```text
screen_pass=true
next_action=design_default_off_hook_candidate
```

## Interpretation

This is the first surviving Concentrated CAGR candidate after broad hold and
cap-safe sizing failed.

Why it is different from broad hold:

- broad PIT leader hold had negative mean excess and was rejected;
- this predicate requires positive actual-results evidence at the prior
  decision date;
- it keeps the rule tied to a PIT-observable thesis confirmation rather than
  "leader therefore hold".

Limitations:

- still not broker A/B evidence;
- OOS sample is small at 12 rows;
- forward excess is audit label only;
- the next hook must prove `applied_count > 0` on target-book replay before any
  broker replay or fullrun.

## Next Step

Design a default-OFF hook candidate only if the implementation can use the same
PIT fields during replay:

Potential env:

```text
PHASE_ACTUAL_RESULTS_HOLD_EXTENSION_ENABLED=1
```

Candidate behavior:

- Concentrated only;
- default OFF;
- suppress a drop/replace of a prior held name only when:
  - prior row satisfies `actual_results_positive_pit_hold`;
  - no hard risk exit is active;
  - price remains above MA200;
  - 3m benchmark RS remains non-negative;
  - no explicit event/guidance break is present.

Required before broker A/B:

- target-book replay with env ON/OFF;
- `applied_count > 0`;
- selected ticker set and holding decisions explainable;
- no forward labels read by the hook;
- no live or production mutation.

If applied count is zero, stop and do not run broker A/B.

