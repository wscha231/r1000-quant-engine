# SEC 13F H2 Manager Skill Policy — 2026-09-16

Status: `RESEARCH_ONLY` / H2 manager-skill policy candidate.

## Purpose

Replace fame/AUM/seed-priority manager selection with a fail-closed review of
**post-disclosure clone evidence**. This layer does not infer skill from a
manager's current 13F size and does not activate a manager merely because a
well-known investor bought a stock.

The H1 dependency is the corrected 13F evidence chain in #437/#439. The
candidate-universe branch #440 is a separate H1 discovery slice; this H2 policy
is deliberately not allowed to turn event membership into a buy-score bonus.

## Preregistered initial score components

- 36-month post-disclosure clone excess evidence: 35%
- downside/recovery quality: 20%
- incremental new/add-position evidence: 20%
- delayed-entry robustness: 15%
- independent-information/diversification value: 10%

The component values must be supplied by a separately reviewed estimator,
oriented `HIGHER_IS_BETTER`, and available by the decision cutoff. These
weights are an initial preregistered hypothesis, not an optimized production
model.

## Eligibility and turnover controls

- expected manager population must be explicit and PIT-valid;
- at least 8 matured quarters and 20 correlation/overlap-adjusted effective
  independent events are required by the initial policy;
- 12- and 24-month clone-minus-benchmark windows must both be complete;
- 36-month component history must really span 36 completed months;
- monthly and quarterly reviews are monitor-only;
- regular change proposals are limited to June/December reviews;
- minimum normal tenure is 12 months;
- a normal exit requires two consecutive quarterly ranks below 15 plus
  negative 12- and 24-month net relative performance;
- incoming replacement must clear the entry criteria and exceed the outgoing
  manager by at least 10 score points;
- at most two normal replacements may consume a half-year budget, including
  unresolved carry-over decisions;
- a source-integrity critical event can quarantine a manager source for review,
  but does **not** create an automatic stock sale.

## Influence is not a broker allocation

The optional source-influence diagnostic caps one manager at 15% and one
reviewed correlation cluster at 35%. Any residual remains unallocated. These
are information-source influence limits only and never stock weights.

## Initial research-priority registry

The companion registry contains Duquesne, TCI, Pershing, Appaloosa, Viking,
Lone Pine, Coatue, Atreides, Himalaya and Baker Bros. They are research
priorities, **not a measured top-10 ranking**. No score/influence is assigned
until complete clone evidence exists. Challenger managers remain eligible to
replace them after the same evidence gates.

## Explicit non-claims

This slice does not build the historical clone NAVs, certify the video claim of
70% average 24-month returns, change `managers.csv`, change the existing
semiannual workflow, create a stock order, change the target book, run a
fullrun, or enable production/live trading. The next causal slice is a
reviewed clone-evidence builder using H1-correct position events and PIT prices;
only after that evidence exists should the existing June/December scheduler be
switched from legacy AUM-weighted reselection to this policy.
