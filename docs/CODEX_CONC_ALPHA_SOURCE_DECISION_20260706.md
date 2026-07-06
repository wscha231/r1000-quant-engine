# CODEX CONCENTRATED ALPHA SOURCE DECISION 20260706

Status: `user_selected_open_w4_decision_time_source`

This document records the R4 decision from
`docs/CODEX_DIRECTIVE_POST_RUN287_REINFORCEMENT_20260706.md`.

The user chose to proceed with a stronger decision-time source for
Concentrated alpha work rather than accept the current generated-book
Concentrated ceiling as final.

## Decision

Selected option:

- `open_w4_decision_time_source`

Allowed first action:

- audit whether a PIT earnings/guidance, insider/Form4, or 13F source is
  actually available and decision-time usable
- if a source is ready, run an OOS source screen before any hook design

Forbidden:

- further rank/RS/revenue cap-replacement variants
- using forward returns as ranking inputs
- directly restoring one losing run287 month or ticker
- building a Concentrated hook before source readiness and OOS screen pass
- dispatching a fullrun
- production promotion, live trading, or public performance wording

## Current R4 readiness result

Artifact package:

- `outputs/run287_r4_conc_alpha_source/summary.json`
- `outputs/run287_r4_conc_alpha_source/source_readiness.csv`
- `outputs/run287_r4_conc_alpha_source/report.md`

Current decision label:

- `blocked_missing_w4_decision_time_source`

Interpretation:

- W4 code plumbing exists, but the actual PIT earnings/guidance feed is absent
  in this worktree.
- Existing Form4/13F/ETF alternate source files are also absent in this
  worktree.
- Therefore there is no decision-time source ready for a Concentrated alpha
  hook.

## Next Gate

A source can move to OOS screening only after one of these is true:

- `earnings_guidance.research_ready=true`, with coverage-eligible
  `available_from <= as_of` rows
- or an alternate PIT source such as Form4/13F has complete decision-time
  provenance and enough ticker coverage for a source screen

Even then, `candidate_allowed=false` until the OOS source screen passes.
