# Run287 Daily Paper Bootstrap Recovery — 2026-07-14

## Outcome

The latest scheduled `Daily Operating Selection Refresh` reached the operating
review stage but failed with `FileNotFoundError: missing bootstrap account for
main`.  The workflow assumed a historical `outputs/broker_replay/*` account
would always be restored, but neither the GitHub cache nor the configured Drive
restore contained that seed.

The recovery adds an explicit, one-time forward-paper bootstrap.  If no prior
paper state exists, it converts the unchanged Main and Concentrated target
allocations into integer shares at the exact completed-session adjusted close,
using a fixed USD 100,000 research notional.  Residual and target cash remain
cash.  The resulting seed is frozen and all later changes continue through the
existing next-close, 25 bps forward fill ledger.

## Safety boundary

- This is a current-close starting assumption, not a claim of historical fills.
- A prior-session price cannot be substituted for the requested close.
- Existing paper state is never overwritten.
- Partial ledger evidence without its account state blocks recovery.
- No historical broker replay or fullrun is called by the daily workflow.
- Target books, target weights, production state, orders, and live trading are
  unchanged.
- The paper seed and all later fills remain review-only.

## Why this matters for CAGR/MDD research

This repair does not improve the locked historical CAGR or MDD.  It removes the
operational blocker that prevented daily held-name risk observations and their
1/5/21/63/126-session downside/recovery outcomes from accumulating.  Those
outcomes are required before one risk mechanism can be preregistered without
turning the 2026-07-13 shock into hindsight-tuned stop logic.

## Validation target

- exact-close and missing-close fixture paths
- deterministic bootstrap reuse
- integer-share and non-negative-cash accounting
- no reset when partial ledger evidence exists
- compatibility with `BOOTSTRAP_TARGET_ASSUMED_APPLIED`
- workflow assertion that no historical broker replay or fullrun is invoked

All targeted checks passed, followed by full local PR validation: `172/172`
test files passed in `216.31` seconds.
