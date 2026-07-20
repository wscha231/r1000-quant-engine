# Run287 P9 single promotion and rollback gate result

Status label: `ACTIVE_GOVERNANCE_POLICY`

## Outcome

Run287 now has one machine-readable promotion state and one fail-closed
governance evaluator. The six allowed values are:

```text
RESEARCH_ONLY
SHADOW_OPERATION_READY
FORWARD_PAPER_VALIDATING
FORWARD_PAPER_REVIEW_READY
PRODUCTION_CANDIDATE_USER_APPROVAL_REQUIRED
BLOCKED_OR_ROLLED_BACK
```

The canonical state is `RESEARCH_ONLY`. Historical generated-book performance
is still Main `34.4032% / -25.3629%` and Concentrated
`49.0968% / -22.9560%`, but no challenger has independently passed all
historical gates. PIT membership/delisted coverage is incomplete and 63/126D
forward evidence is unresolved. Workflow or dashboard success cannot change
the canonical state.

## Fixed gates

Historical promotion requires exact control parity, PIT/no-look-ahead,
Full/OOS/OOS2, 126-session embargo, 25/50/100 bps costs, stress,
ticker/sector/era concentration, trusted scorecard, lifecycle/delisted
handling, and no do-not-repeat conflict.

Forward review requires all integrity counts to remain zero, at least 60
completed sessions, 12 decision weeks, and fixed resolved-outcome minimums of
200 at 21D, 100 at 63D, and 50 at 126D. Selection, exit, defense, and re-entry
must all be evaluable. Low signal frequency extends the observation period; it
does not lower thresholds. Until 100 actual 63D outcomes resolve, the 63D lane
is exactly `UNDERPOWERED`.

## Champion and challenger isolation

The generated-book policy is frozen as the canonical champion. A future
official challenger must have a distinct account ID and ledger root and must
match the champion's data, completed-close, cost, Reserve, and lifecycle
contract hashes. It also needs paired decision dates. A ledger collision or
contract mismatch is an integrity error and produces
`BLOCKED_OR_ROLLED_BACK`. Only one official challenger is admitted at a time.

## No automatic promotion

The evaluator reports `maximum_evidence_supported_state` separately from the
actual canonical state. Even a fully passing synthetic fixture supports at
most `FORWARD_PAPER_REVIEW_READY` while leaving the actual state unchanged.
An exact evidence-hash-bound transition authorization only creates a state
change candidate; a separately reviewed canonical pointer commit is still
required. Production activation and live trading are always false in this
gate.

## Rollback

Any integrity error, unknown target/order provenance, structural OOS/forward
degradation, stress-MDD regression, re-entry cash trap, fee exhaustion,
coverage-semantic change, model-head failure, or lifecycle failure immediately
sets the effective state to `BLOCKED_OR_ROLLED_BACK`. The rollback plan restores
the canonical champion policy pointer, requires review of any code rollback,
and preserves every forward account and paper-history byte.

## Operating integration

- The daily workflow evaluates the gate before its operating-review/paper
  processing and archives the result with the daily artifact and Drive copy.
- Restored paper equity curves, fills, manifests, snapshot checksum, and risk
  outcome archive can update observation counts or trigger rollback; they
  cannot alter historical gates or auto-promote.
- The private operating scorecard, public dashboard, and user-current report
  all resolve the same effective state. Legacy component-specific promotion
  labels no longer authorize production.
- The Pages workflow checks out the canonical state and resolver explicitly.

The latest locally downloaded July 16 paper artifact supplied one completed
session, one decision week, and zero resolved 21/63/126D outcomes. Its runtime
overlay remained `RESEARCH_ONLY / UNDERPOWERED` with no rollback trigger. This
is a continuity observation, not current production evidence and not a July 17
performance refresh.

## Approval packet

The gate always emits exact source hashes, champion/challenger historical
metrics, forward observations, stress/cost/concentration/integrity results,
target/Reserve changes, failure modes, rollback plan, unresolved limitations,
and requested scope. The current packet is `NOT_ELIGIBLE`; user approval is
false and cannot activate orders.

No fullrun was executed. Production and live trading remain disabled.

Verification: repository pytest `129/129`; full Tier-1 `190/190` in
`260.48s`; P9 governance fixtures `9/9`.
