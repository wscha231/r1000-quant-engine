# Run287 next single A/B readiness result - 2026-07-15

## Outcome

The generated-book substrate is locally ready, but no new historical portfolio
A/B is authorized yet.

- local artifact hashes: `6/6 PASS`;
- official source run: `28725350727`;
- control/core/generated substrate gates: ready;
- SEC filing-quality lane: terminal `REJECT_SOURCE_SCREEN`;
- SEC guidance scout: terminal
  `CLOSED_SOURCE_PRECISION_OR_RECALL_GATE`;
- external PIT source-data gate: missing/not passed;
- external single-source alpha screen: missing/not passed;
- eligible preregistered A/B arms: `0`;
- final status: `BLOCKED_NO_ELIGIBLE_SINGLE_AB`.

The earlier candidate-artifact diagnosis is corrected: the raw candidate book,
SEC-enriched candidate book, selector metadata, target-generation input
manifest, long-crisis payload, and long-crisis thresholds are all present in
the existing local workspaces and exactly match the frozen SHA-256 values.
Concentrated is blocked by the rejected SEC source lane, not by a missing
candidate artifact.

## What was implemented

`tools/audit_run287_next_single_ab_readiness.py` now enforces the research
sequence as a state machine:

1. verify core, control parity, generated substrate, and all six local hashes;
2. preserve the two SEC lane closures as terminal evidence;
3. require an external PIT export to reach `READY_FOR_SOURCE_SCREEN`;
4. require a separate preregistered source screen to return
   `PASS_SOURCE_SCREEN` with exactly one candidate arm;
5. block any exact do-not-repeat match;
6. open only the fixed-book A/B first;
7. open a generated-book A/B only after the matching fixed-book arm passes.

Two simultaneous arms, a missing preregistration field, a hash mismatch, a
terminal-evidence mismatch, or a do-not-repeat match all fail closed.  Forward
63D risk outcomes can open only a mechanism review; they cannot open a
historical A/B or count as seven-year CAGR/MDD proof.

The SEC guidance keyword scout is now registered in the machine-readable
do-not-repeat registry.  Threshold, keyword, or label retuning of the same lane
is therefore blocked by default.

## Relationship to CAGR/MDD

This step does not itself raise the measured CAGR or change MDD.  It strengthens
the improvement process in three concrete ways:

- the original generated candidate pool is reproducible, so any future
  Concentrated replacement can use the real eligible challengers rather than
  reverse-engineering selected names;
- OOS-negative SEC signals and the low-precision guidance heuristic cannot be
  reintroduced under a new name, reducing overfit and MDD/CAGR regression risk;
- the next experiment must show independent single-source alpha before any
  weight mechanism is tested, then must survive fixed-book before generated
  book accounting.

For context, the latest separate 25 bps cost-leak diagnostic remains Main
`34.4032% CAGR / -25.3619% MDD` and Concentrated
`49.0971% CAGR / -22.9552% MDD`.  This readiness audit changed neither result.

The direct numerical path remains narrow: Main needs about `+0.60pp` CAGR and
`+0.36pp` MDD recovery from that diagnostic, while Concentrated needs about
`+0.90pp` CAGR without losing more than roughly `2.04pp` MDD.  Zero-cost replay
upper bounds already exceed both CAGR targets, so execution-cost selectivity is
economically important, but the prior generic partial-resize rule was strongly
negative OOS and remains closed.  Any cost-saving mechanism must therefore be
tied to a newly validated decision-time source rather than a generic turnover
rule.

## Current forward gate

The archived risk cross-section has 26 observations from one decision week.
Its first 1D endpoint is diagnostic only.  The frozen 63D mechanism-review gate
still requires 12 distinct decision weeks, at least 50 warning and 50 normal
observations, 30 tickers, and eight paired week blocks.  No threshold, stop,
exit, cash, or sizing rule can be selected before that gate.

Local machine-readable output is retained at
`outputs/run287_next_single_ab_readiness_20260715_local/`.  It is untracked and
contains no secret.  No backtest, fullrun, target-book mutation, order,
production, or live-trading action was executed.

The complete local PR validation passed `173/173` test files in `230.81`
seconds, including leakage, workflow-artifact, portfolio, and direct-fullrun
guards.
