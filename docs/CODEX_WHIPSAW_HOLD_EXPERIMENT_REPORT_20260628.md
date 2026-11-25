# AlphaOps vNext Whipsaw Hold Experiment Report — 2026-06-28

## Verdict

`W-AUDIT` confirms a large sell/rebuy whipsaw drag, but the first broad
`earnings-confirmed hold` hook is rejected.

Keep the audit. Do not ship or merge the broad hold hook.

## Context

Current mission target remains unchanged:

- Main: CAGR >= 35%, MDD >= -25%
- Concentrated: CAGR >= 50%, MDD >= -25%

Production promotion remains blocked while `pit_universe_label_clean=false`.
All results below are research evidence only.

## Evidence 1 — Whipsaw Cost Is Material

Using clean 7Y artifact `artifacts/28074476465/outputs`, the new whipsaw audit
found that the system often sells a leader and later rebuys the same name at a
higher price.

Audit output location:

- `artifacts/28074476465/whipsaw_cost_audit_20260628/summary.json`

Key results:

| Portfolio | Events | Positive rebuy share | Median rebuy premium | Recoverable ceiling |
|---|---:|---:|---:|---:|
| Main | 189 | 84.66% | 19.22% | 14.03 pp/year |
| Concentrated | 68 | 92.65% | 20.70% | 19.67 pp/year |

Interpretation:

- The problem is not only stock selection.
- The system often identifies future leaders, exits them, and later re-enters
  at worse prices.
- This is a material diagnostic, but it is a ceiling estimate, not a promised
  CAGR improvement.

## Evidence 2 — Broad Earnings-Confirmed Hold Hook Was Rejected

An unpushed local experiment implemented a default-OFF
`PHASE_EARNINGS_CONFIRMED_HOLD_ENABLED` hook:

- Concentrated only
- Prior holdings only
- `actual_results_score > 0`
- `leader_tier in {DUAL_LEADER, SECTOR_LEADER}`
- 3M relative strength positive
- above MA200
- no guidance/revision deterioration
- no crisis block

The first implementation protected score-band TRIM only. Target-book screen:

- Protected prior-holding rows: 117
- Actual TRIM/WARNING suppression: 0

This showed that the whipsaw was not mainly from score-band TRIM. It was mostly
from replacement pressure.

The hook was then extended to replacement-gap protection. Target-book screen:

- Protected/evaluated rows: 131
- Replacement protection actually changed target book: 17 retained rows

Cheap broker replay was then run on the generated Concentrated target book:

- Target book:
  `artifacts/28074476465/earnings_confirmed_hold_target_screen_20260628/official_concentrated_target_book.csv`
- Price cache:
  `artifacts/28074476465/cache_prices`
- Replay output:
  `artifacts/28074476465/earnings_confirmed_hold_broker_ab_20260628/concentrated/metrics.json`

Broker replay result:

| Metric | Baseline clean 7Y | Broad hold hook |
|---|---:|---:|
| CAGR | 46.24% | 45.22% |
| MaxDD | -25.82% | -27.51% |
| Sharpe | 1.421 | 1.260 |
| Avg cash | 42.18% | 30.94% |

Verdict:

- `reject_mdd_worse`
- `reject_no_cagr_edge`
- Do not fullrun.
- Do not merge this hook.

## What We Learned

The audit diagnosis is right, but the first remedy was too broad.

The broad hook kept some leaders that should have been replaced. It lowered cash
and raised exposure at the wrong times, which worsened MDD and reduced CAGR.

Therefore the next valid direction is not:

- broad hold-duration extension
- "actual_results_score > 0" as a standalone hold rule
- relaxed replacement thresholds for all confirmed leaders

## Next Candidate — Incumbent vs Challenger Replacement Quality

The next hook must decide whether the replacement itself is genuinely better
than the incumbent, using PIT features only.

Required design:

1. Keep the whipsaw audit as the diagnostic source.
2. Add a cheap replacement-quality screen before broker A/B.
3. For every would-replace event, compare incumbent vs challenger on PIT fields:
   - relative strength 3M/6M
   - leader tier
   - sector or industry leadership
   - actual results / revision confirmation
   - price trend intactness
   - overextension or late-entry risk
   - crisis/regime state
4. Protect the incumbent only when:
   - the challenger wins on raw score but not on thesis quality, and
   - the incumbent thesis is intact, and
   - the candidate would otherwise create a sell/rebuy whipsaw risk.

Acceptance gate:

- target-book applied count > 0
- Concentrated broker CAGR improves by >= +0.50pp
- MaxDD does not worsen
- OOS does not collapse
- no target/production/live mutation
- `pit_universe_label_clean=false` still blocks production promotion

If the screen cannot separate winners from losers, discard it.

## Implementation Rule

Do not create another broad hold hook.

The next PR should be a measurement-first screen:

- `tools/run_replacement_quality_whipsaw_screen.py`
- default OFF if it later becomes a policy hook
- no fullrun until cheap target-book and broker replay show a real edge

## Status

- W-AUDIT PR: keep.
- Broad earnings-confirmed hold hook: rejected, not pushed.
- Next work: replacement-quality whipsaw screen.
