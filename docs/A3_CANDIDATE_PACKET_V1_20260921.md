# A3 Candidate Packet V1 — cross-market research aggregation

[PROJECT_HANDOFF]

- Date: 2026-09-21 KST
- Mode: RESEARCH_ONLY
- Purpose: bind reviewed Methodology V1, Moat V2, market/valuation, evidence graph and scenario research into one candidate artifact without inventing validated ER.
- No selector, target, portfolio, broker/order or production authority.

## Key boundary

Bull/Base/Bear research scenarios and validated expected return are different objects.

A 12/24-month scenario bridge may state bear/base/bull returns and assumptions, but it may **not** contain probabilities. Without a separately reviewed `WALK_FORWARD_VALIDATED`, net-of-costs ER artifact, the packet status remains `SCENARIO_RESEARCH_COMPLETE` and `scenario_research_is_expected_return=false`.

Only a validated ER artifact may populate 1/3/6/12-month expected return, benchmark expected return, expected alpha, downside probability and expected drawdown. The ER benchmark must match the reviewed market snapshot.

## Required reviewed artifacts

1. Investment Methodology V1 result
2. Market / valuation snapshot with 20/60/120/240D asset and benchmark returns/RS
3. Reviewed source graph
4. Moat V2 result for company/securities where competitive advantage is applicable
5. Optional validated ER evaluation

Every artifact reference is checked against resolved immutable bytes and SHA-256. Artifact availability must be no later than packet `as_of`, and asset/issuer identity is bound where applicable.

## Market snapshot identity

The market artifact must use a completed trading session and disclose its return
basis. For 20/60/120/240 trading-day horizons the validator recomputes relative
strength as:

`log(1 + asset return) - log(1 + benchmark return)`

This matches the existing strict multi-asset leadership path rather than
accepting a manually supplied RS number.

## Research workflow

whole universe -> quantitative/leadership shortlist -> Methodology/Moat evidence -> market/valuation snapshot -> 12/24m scenario research -> optional validated ER -> A5 portfolio competition

This packet does not itself make an asset selector-eligible. It is an A3 evidence container.

## Safety

Outputs always declare:
- historical_pit_certified=false
- selector_eligible=false
- portfolio_weight_effect=0
- target_book_write_allowed=false
- orders_allowed=false
- production_authority=false

A scenario-only packet is never described as validated expected return.
