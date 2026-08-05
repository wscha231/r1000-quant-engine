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

## Official recovery observation

The input was the `run287-u0-census-diagnostic` artifact from research-only
Actions run `31018404151`, bound to master SHA
`f28321d011d0705cf8fdd43f1f98647f85557d42`.

- source candidates: 351
- exact code-head trials: 350
- duplicate aliases: 1
- canonical registry published-attempt lower bound: 53
- conservative historical trial-count lower bound: 403
- unverified assertions: 345
- unverified-ancestry canonical trials: 72
- incomplete changed-path evidence: 13

These figures are official diagnostic evidence, not performance evidence. The
trial floor is dynamic: later exact code heads increase it, so no downstream
gate may hard-code 403.

## Remaining gates

The recovery census deliberately leaves `historical_challenger_allowed=false`.
Canonical acceptance may authorize only the narrower, preregistered research
fit after independently recomputing this census. It still may not authorize a
broker backtest. Remaining work must:

1. merge the U0-v3 acceptance and expected-return multiplicity binding;
2. publish and inspect canonical accepted evidence on the new master head;
3. regenerate the feature store with exact future-label end dates and explicit
   `SPY` / `YF:SPY` provenance;
4. only then request approval for the bounded $100,000 next-close
   broker-ledger backtest.

No fullrun, target/order/ledger mutation, live trading, champion change, or
automatic promotion is authorized here.
