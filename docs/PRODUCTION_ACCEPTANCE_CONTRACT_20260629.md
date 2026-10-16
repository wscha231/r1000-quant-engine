# Production Acceptance Contract - 2026-06-29

## Purpose

This document records the current governance decision after the Main MDD repair
triage in PR #201.

It does not promote the strategy to production. It defines the acceptance
framework that future research evidence must satisfy before a production
promotion can even be considered.

## Current User Decision

The current mandate is:

- prioritize CAGR improvement;
- keep the system long-only;
- do not add hedge overlays unless explicitly reopened later;
- stop tuning smaller cash/stop/cap/event-defense variants;
- treat MDD as a governance risk cap rather than the primary optimization
  target;
- keep `pit_universe_label_clean=false` as a hard production blocker.

## Why The Contract Changed

PR #201 documents negative broker-ledger evidence for Main MDD repair through
the existing long-only monthly target-book family:

- broad cash and crisis floors;
- stop and parabolic overlays;
- SPY drawdown cash triggers;
- crash-fragility trims;
- blunt Main single-name caps;
- stress-condition caps;
- intramonth event-defense and daily crisis cash target books.

These paths either:

- failed to improve MaxDD enough; or
- improved MaxDD only by damaging CAGR too much; or
- caused severe whipsaw.

Therefore the project should not continue searching small variants of the same
mechanism.

## Production Blockers

Production promotion is blocked unless all of the following are true:

1. `pit_universe_label_clean=true`
   - current constituents / static proxy membership is not production evidence;
   - membership source, `available_from`, survivorship, delisted coverage, and
     ticker-change coverage must be auditable.

2. Official broker-ledger measurement is present
   - metric mode must be `broker_ledger_next_close`;
   - integer-share replay;
   - trading costs included;
   - no legacy weight-level proxy metric as production evidence.

3. Clean research window is present
   - clean 7Y or user-approved equivalent evidence contract;
   - start/end dates and calendar trading-day count must be machine-readable.

4. No live-trading or production mutation occurs without explicit user approval.

## Target Framework

### Primary Optimization Targets

The primary research optimization targets remain:

| Sleeve | CAGR Target | Role |
|---|---:|---|
| Main | >= 35% | primary CAGR target |
| Concentrated | >= 50% | primary CAGR target |

These are still ambitious research targets. They are not production claims while
PIT membership is unclean.

### MDD Governance

The old `-25%` MDD floor is no longer treated as the main optimization target
for the current long-only mandate.

Instead:

- MDD is a risk cap;
- MDD breach triggers governance review, not infinite cash/stop tuning;
- the risk cap should be applied consistently to both Main and Concentrated.

Candidate risk-cap proposal:

| Item | Proposed Rule |
|---|---|
| Main MaxDD | must not exceed about `-28%` without governance review |
| Concentrated MaxDD | must not exceed about `-28%` without governance review |
| `-25%` MaxDD | aspirational / legacy floor unless user explicitly keeps it hard |

The exact number is a governance choice. `-28%` is proposed because current
clean long-only evidence sits around `-26%`, and PIT-clean measurement can move
the frontier. This is not a license to accept uncontrolled drawdown.

## Risk-Adjusted Production Quality Gates

Even if CAGR targets are met, production review should require:

- positive excess CAGR versus benchmark;
- Sharpe floor, proposed `>= 1.20`;
- information ratio floor, proposed `>= 1.0` when benchmark-relative returns are
  available;
- OOS non-collapse;
- no single event, ticker, or era explains the whole result;
- no increase in cash trap behavior;
- no hidden cap breach or concentration rule bypass;
- no forward-return or future-label use in selection.

## Long-Only Boundary

Under the current mandate, future work must stay long-only.

Allowed:

- reweighting selected long names;
- selecting better long candidates;
- holding verified winners longer;
- reducing exposure through bounded cash only when broker evidence justifies it;
- general theme leadership and earnings-revision signals if PIT-safe.

Not allowed unless user explicitly reopens hedge research:

- short positions;
- options overlays;
- synthetic hedge ledgers;
- inverse ETF hedge sleeves;
- leverage or target books with total exposure above allowed caps.

If hedge research is reopened later, it must be a separate opt-in research track
with its own measurement contract.

## CAGR Work Priority

With cheap MDD repair closed, the next work should focus on CAGR:

### Main

Primary candidate:

- AI Capex / generic theme momentum tilt from PR #199.

Interpretation:

- Main CAGR candidate only;
- not an MDD repair;
- should be generalized into a theme-leadership framework rather than hardcoded
  to AI.

### Concentrated

Primary candidates:

1. actual-results-confirmed hold-extension;
2. winner-retention / whipsaw reduction;
3. cap-safe concentration/sizing only if it can pass broker evidence without
   bypassing risk caps.

Rejected or parked:

- broad hold leaders longer;
- cap-safe score-sizing as previously tested;
- broad gross floor;
- broad rescue;
- uncapped sizing as policy candidate.

## Stop Rules

The project should stop a research branch early when:

- applied count is zero;
- only forward-label evidence exists and no PIT live predicate can be defined;
- cheap broker A/B fails mission-quality tradeoff;
- OOS collapses;
- result depends on one ticker, one event, or one era without ex-ante
  justification;
- improvement requires violating the long-only/no-hedge mandate.

Fullrun should not be dispatched until a cheap broker-ledger A/B provides a real
reason.

## Next Implementation Sequence

1. Merge or preserve PR #201 as the negative-evidence ledger for Main MDD repair.
2. Stop Main cash/stop/cap/event-defense variants.
3. Continue Main CAGR candidate work from PR #199 / generic theme leadership.
4. Continue Concentrated winner-retention work only after PIT availability and
   applied-count checks.
5. Continue PIT universe cleanup.
6. Revisit this contract only through explicit governance decision.

## Current Status

This contract is a research governance document. It does not:

- enable production;
- change live trading;
- change target books;
- change scoring;
- dispatch workflows;
- merge any PR.

