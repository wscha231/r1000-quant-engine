# Run287 U0-v3 Conservative Recovery Design

## Purpose

U0-v2 is the exact-head GitHub collector. It intentionally leaves every
experiment-like branch or pull request unmapped and therefore cannot itself
authorize historical challenger work. U0-v3 adds a classification layer; it
does not turn missing legacy evidence into valid performance evidence.

## Canonical identity and multiplicity

- One exact candidate code-head SHA is one canonical legacy trial.
- Multiple PR or branch records with the same code head are aliases. Exactly
  one primary row receives multiplicity weight 1; aliases receive weight 0.
- Every distinct candidate code head is counted, even when its purpose or
  result cannot be verified.
- Published-attempt lower bounds from the existing canonical registry are
  added separately. Because overlap is unresolved, overcounting is deliberate
  and conservative.
- Missing daily returns are never replaced with zero and summary CAGR/MDD is
  never converted into a return series.

## Missing-evidence treatment

An unmapped historical candidate is classified as `UNVERIFIED_LEGACY` with
`UNVERIFIED_ASSERTION` evidence. PIT, parameter/data hashes, target-book hash,
cash/cost contract, and synchronized daily after-cost returns remain explicitly
missing. Each exact code head receives a do-not-repeat key, but no legacy row
may support a performance claim or promotion.

Registry-linked records retain their existing evidence classification, while
all records sharing the same exact code head inherit the union of registry and
capability-family links. This prevents an alias from losing stronger blocking
evidence attached to another PR with identical code.

## Current diagnostic observation

The input was the `run287-u0-census-diagnostic` artifact from research-only
Actions run `31014230254`, bound to master SHA
`f31a9bb1a9af0d0ca465a8358e7840b51c5c1a84`.

- source candidates: 350
- exact code-head trials: 349
- duplicate aliases: 1
- canonical registry published-attempt lower bound: 53
- conservative historical trial-count lower bound: 402
- unverified assertions: 344
- unverified-ancestry canonical trials: 72
- truncated changed-path sets: 8
- branch-only candidates without recovered changed paths: 5

These figures were produced locally by applying the proposed deterministic
U0-v3 transformer to the official U0-v2 artifact. They are diagnostic until a
merged master workflow publishes the corresponding U0-v3 files.

## Remaining gates

This change deliberately leaves `historical_challenger_allowed=false`.
Separate reviewed work must:

1. publish and inspect the U0-v3 artifact on current master;
2. bind canonical acceptance to the U0-v3 schema and conservative trial count;
3. bind the expected-return runner and later statistical tests to that count;
4. regenerate the feature store with exact future-label end dates and explicit
   `SPY` / `YF:SPY` provenance;
5. only then run the bounded $100,000 next-close broker-ledger backtest.

No fullrun, target/order/ledger mutation, live trading, champion change, or
automatic promotion is authorized here.
