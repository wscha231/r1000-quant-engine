# A5 research comparison: compounding and recovery

Status: research reporting only. This component does not select securities,
change weights, create fills, mutate a book, or grant promotion authority.

## Objective

The current research objective is to maximize repeatable, after-cost long-term
compounding within the existing risk constraints. A fixed 30%, 35%, 40%, or 50%
CAGR is not a research acceptance floor or a ceiling. Historical-window returns
are evidence for comparison, not a claim of attainable future performance.

Use the same universe, decision schedule, initial capital, cash-flow basis,
execution rules, window and costs for a paired comparison. Net terminal wealth
orders CAGR on that matched window. Do not charge costs again when the supplied
NAV already includes them. Report MDD, complete underwater duration, turnover,
and execution sensitivity separately; do not manufacture a fitted scalar score
that hides the tradeoffs.

## Output contract

`tools/evaluate_a5_research_goal.py` now emits policy
`matched_spy_diagnostics_constrained_compounding_v3`.

| Field | Meaning |
| --- | --- |
| `research_objective` | Continuous net-wealth/CAGR measurements, no fixed CAGR acceptance threshold; the existing configured MDD constraint is reported separately. |
| `status` and `status_basis` | Compatibility diagnostic for beating the matched SPY terminal wealth while having no deeper MDD. PASS is not admission or a portfolio risk verdict. |
| `stretch_status` | The old concentrated 40% test is retired. |
| `project_mission` | The configured historical target contract remains visible as a labeled legacy diagnostic; its fixed CAGR status is not the current research objective. |
| `promotion_allowed` | Always false, both at the report root and inside the research objective. |

`PORTFOLIO_MISSION_TARGETS.max_dd` remains the source of the reported risk
constraint. The entire mission identity is retained for provenance. A strategy
can beat SPY's return and MDD while breaching its own MDD limit. That case must
remain visible as `drawdown_constraint.status=BREACHED`. This component does not
evaluate all other admission gates, and a historical MDD below the limit does
not guarantee a future loss limit.

The existing official mission contract and accepted artifact bindings are not
migrated by this report change. A later migration must enumerate official
consumers and preserve their risk and admission checks; do not silently relabel
previously accepted artifacts. Research consumers must not use the legacy fixed
CAGR diagnostic to choose or admit a new strategy.

## Recovery measurements

The existing `recovery_from_worst_trough` keeps its precise old meaning:
calendar days and observed session intervals from the deepest trough to the
next close at its preceding peak. It cannot measure the investor's entire wait.

`drawdown_durations` and `spy_drawdown_durations` additionally report:

- The peak-to-recovery period for the deepest drawdown episode.
- The longest completed peak-to-recovery period, which need not be the deepest.
- The still-open episode, with null recovery duration and an observed lower
  bound. Right-censored duration is never zero or a completed recovery time.

The authenticated anchor is the first observation. Its date is the date in
`America/New_York`, independent of the timestamp's stated offset. Equal highs
reset the peak date so that time spent at the high is excluded. Session
durations count NYSE closes after the peak through the recovery or last
observation. If an episode begins at the anchor, the calendar supplies the
elapsed closes through the first NAV row, without creating marks for those
dates. Tied deepest episodes retain the first one, matching the old trough
diagnostic. Any open tied episode is also reported independently.

For archived result summaries that contain only peak/trough/recovery dates,
one can derive the recorded MDD episode's complete duration. One cannot derive
the longest episode, verify every daily NAV, or claim a new replay from those
summary fields alone. Keep that weaker evidence basis explicit.

## Integrity and validation

The external manifest pin, source/PIT/corporate-action originals, next-close
execution, whole-share policy, cash carry, SPY total return, common grid, and
no-second-fee checks are unchanged. Blocked inputs expose no research objective.

The existing registered `tests/a5_research_goal_smoke.py` covers fixed-target
retirement, exact risk boundaries, an end-to-end SPY PASS with a risk breach,
peak/trough separation, different deepest and longest episodes, equal highs,
tied deepest episodes, timezone-equivalent anchors, multi-session anchor
intervals, and right censoring. Its synthetic fixtures do not establish
real-input or economic validation.
