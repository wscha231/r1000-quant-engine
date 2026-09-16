# SEC 13F H2 Manager Event Scorecard — 2026-09-16

Status: `RESEARCH_ONLY`.

This slice aggregates only **matured** rows from the clone-event evidence layer.
It reports manager-level 63/126/252/504-session event outcomes, new/add
subsamples and 2/5-session delayed-entry robustness over a preregistered 36-month
review window.

It intentionally does **not** convert an average event return into account CAGR.
`event_study_not_account_nav=true`, `continuous_clone_nav_built=false` and
`manager_skill_rank_built=false` are part of the artifact contract.

Eligibility in this artifact only means the descriptive horizon sample meets
minimum event/ticker counts. It does not mean the manager is eligible for H2
production ranking. The scorecard sets `outcome_overlap_adjusted=false` and
`correlation_adjusted_effective_sample_built=false`; PR #442 must remain blocked
from consuming these descriptive scorecards as verified manager skill until a
later overlap/correlation-adjusted evidence slice exists.

No active manager roster, candidate score, stock position, portfolio target,
order, paper/broker ledger, champion or live-trading state is changed.
