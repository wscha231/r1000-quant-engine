# Claude Governance Note - 2026-06-29

## Purpose

This note preserves Claude's latest governance recommendation for later
comparison with GPT Pro's opinion. It is not yet a final decision record.

The user stated the new direction as:

- prioritize CAGR;
- keep the system long-only;
- do not add hedge overlays;
- stop spending time on smaller cash/stop MDD repair variants;
- consider realistic MDD governance because repeated long-only monthly
  target-book repairs did not move the drawdown target cleanly.

## Claude's Core Interpretation

Claude agrees that the Main cheap-MDD-repair track should be closed.

Reason:

- Codex already tested broad cash, stop, cap, stress-condition cap, and
  intramonth event-defense paths.
- These either failed MDD or repaired it only by damaging CAGR too much.
- Continuing to search small cash/stop variants would likely be audit churn.

Claude further argues that the same logic applies to Concentrated:

- Concentrated is also slightly outside the old `-25%` MDD target.
- It uses the same long-only monthly architecture.
- Therefore loosening MDD only for Main but not Concentrated would be
  inconsistent.

## Proposed Mission Reframe

Claude suggests moving from four simultaneous hard targets:

- Main CAGR;
- Main MDD;
- Concentrated CAGR;
- Concentrated MDD;

to a simpler framework:

- CAGR becomes the primary optimization target.
- MDD becomes a risk cap rather than a hard alpha target.

Claude's proposed candidate governance shape:

| Item | Proposed Role |
|---|---|
| Main CAGR >= 35% | Keep as primary aspiration / target |
| Concentrated CAGR >= 50% | Keep as primary aspiration / target |
| MDD <= 28% | Treat as risk cap, not the main optimization objective |
| Excess CAGR > 0 | Add as production-quality relative return check |
| Sharpe >= 1.20 | Add risk-adjusted quality floor |
| IR >= 1.0 | Add relative consistency floor |

Claude emphasized that these numbers are governance choices, not silent code
changes. They must be explicitly approved and documented before becoming a
production acceptance contract.

## Why This Matters

Under the old target framing:

- Main needed both CAGR lift and MDD repair.
- Concentrated needed both CAGR lift and MDD repair.
- Repeated MDD repair attempts produced poor tradeoffs.

Under Claude's proposed framing:

- the project becomes mostly a CAGR-improvement problem;
- Main needs roughly +1pp CAGR;
- Concentrated needs roughly +3.76pp CAGR;
- MDD stays bounded by a realistic risk cap.

Claude described this as reducing the mission from:

> MDD + CAGR across two sleeves

to:

> CAGR improvement across two sleeves, with MDD capped.

## Proposed Next Work Sequence From Claude

### Main CAGR

Continue evaluating PR #199 style AI Capex / momentum tilt as a Main CAGR
candidate.

Requirements:

- broker-ledger A/B only;
- applied count must be nonzero;
- OOS must not collapse;
- capture metrics must not regress;
- do not treat it as an MDD repair.

### Concentrated CAGR

Claude sees Concentrated CAGR as the main remaining challenge.

Suggested highest-value levers:

1. Concentrated sizing / score-power grid.
   - Directly targets the winner-weighting mechanism.
   - Does not depend on rare guard predicates firing.
   - Needs cap-safe broker evidence.

2. A1 SHAKEOUT / winner hold-duration screen after signal carry-through.
   - Applied count must be nonzero.
   - If it fires, broker A/B can test whether winner holding improves CAGR.

3. Actual-results-confirmed hold-extension.
   - Potentially useful because broad leader hold failed.
   - Must prove PIT availability and broker-ledger delta before promotion.

### PIT Universe Track

Claude keeps Track A as a production-critical path:

- PIT universe membership must be cleaned.
- Survivorship/proxy universe remains a production blocker.
- Final measurement on a PIT-clean universe may lower CAGR and widen the gap.

## Stop Rules

Claude recommends importing the same discipline learned from MDD into CAGR:

- no infinite lever hunt;
- no fullrun without cheap broker A/B reason;
- if PR #199 / sizing / A1-style hold work fail to close the gap on clean
  substrate, then revisit whether absolute CAGR `35/50` is realistic under a
  clean PIT long-only system;
- consider shifting production criteria toward excess return, IR, Sharpe, and
  MDD risk cap if absolute CAGR remains out of reach.

## Suggested Documentation Step

Claude suggested formalizing this as a governance document, for example:

- `PRODUCTION_ACCEPTANCE_CONTRACT.md`

Potential contents:

- MDD risk-cap definition;
- relative/risk-adjusted production gates;
- old target exhaustion table;
- statement that absolute CAGR `35/50` remains aspirational unless the user
  explicitly keeps it as a hard production gate.

## Pending GPT Pro Comparison

GPT Pro feedback has now arrived. It agrees with the negative evidence in PR
#201, but it recommends a different next step from Claude.

## GPT Pro's Core Interpretation

GPT Pro agrees that PR #201 is strong negative evidence:

- Main MDD cannot be repaired cleanly by the tested long-only monthly
  target-book variants.
- Broad cash, stop, fragility, single-name cap, stress-condition cap, and
  intramonth event-defense all failed on broker-ledger evidence.
- PR #201 is still merge-worthy as a research-negative-evidence PR, not as an
  alpha-promotion PR.

GPT Pro further recommends that PR #201's body should be updated before ready:

- mention the actual implemented scope, not only the original triage document;
- include `main_crash_fragility_screen`;
- include `main_stress_window_attribution`;
- include `main_stress_condition_cap_broker_ab`;
- include `main_event_defense_broker_ab`;
- include the full 8-arm event-defense result table;
- explicitly state `No fullrun justified`;
- explicitly state that it is a negative-evidence PR.

GPT Pro's proposed next implementation is different from Claude's:

- build a research-only hedge overlay broker A/B harness;
- do this before governance target relaxation;
- use funded mode first, with total gross <= 1.0;
- do not use options unless PIT-safe historical option chains already exist;
- do not mutate production target books;
- if hedge also fails, then trigger governance review.

## Current Code Reality Check

The current broker replay engine is long-only by construction:

- `tools/run_broker_ledger_replay.py` filters target rows to positive weights;
- it enforces no negative cash / no leverage;
- it sizes positions from positive target weights;
- it blocks target books whose total weight exceeds the reasonable exposure cap.

Therefore a hedge overlay cannot be implemented as a true short position in the
existing official broker replay without changing the measurement model.

The only compatible first-pass hedge form would be:

1. **Funded long inverse ETF style hedge**
   - reduce Main long weights pro-rata;
   - add a positive-weight hedge instrument row;
   - keep total target weight <= 1.0;
   - measure through the normal broker ledger.

2. **Separate synthetic overlay ledger**
   - outside official broker replay semantics;
   - clearly labeled broker-equivalent / research-only;
   - not production-valid unless a formal contract accepts it.

The existing artifact's price-cache manifest only requires `SPY` and `QQQ` as
market tickers. It does **not** list common inverse/hedge ETFs such as `SH`,
`PSQ`, `SDS`, `QID`, `VIXY`, `UVXY`, `TLT`, `IEF`, or `GLD`.

This means GPT Pro's hedge harness is not immediately runnable on the current
artifact unless:

- a valid hedge ticker is already present in the price cache through another
  path; or
- the cache is refreshed/extended for the hedge instrument; or
- the harness first emits `blocked_missing_hedge_price_history`.

## Claude vs GPT Pro: Where They Agree

Both agree on these points:

1. PR #201's negative conclusion is correct.
2. Do not keep tuning smaller cash/stop/cap/event-defense parameters.
3. PR #201 should be treated as a research ledger of failed Main MDD repairs.
4. PR #199 / AI Capex tilt is a Main CAGR candidate, not an MDD repair.
5. Production remains blocked by PIT universe discipline.
6. No fullrun is justified from the PR #201 MDD work.

## Claude vs GPT Pro: Main Disagreement

The disagreement is the next step after PR #201.

| Question | Claude | GPT Pro |
|---|---|---|
| Keep long-only? | Yes, per user decision | Hedge overlay allowed as research |
| Next Main MDD step | Governance / MDD risk-cap realism | Research-only hedge overlay |
| MDD target | Convert to risk cap, e.g. around -28% | Test hedge before relaxing |
| Optimization priority | CAGR first | Still try to repair MDD via separate hedge sleeve |
| Fullrun | Not until CAGR candidate passes cheap broker A/B | Not until hedge A/B passes |

The conflict is not technical. It is a governance decision:

- If the user wants to keep the system strictly long-only with no hedge, Claude's
  path is consistent.
- If the user wants to keep `Main MDD >= -25%` as a hard target, GPT Pro's hedge
  path is the next structurally coherent experiment.

## Synthesis Recommendation

Given the user's latest stated direction:

> CAGR priority + MDD bar realism + long-only + no hedge

the hedge overlay should **not** be implemented now.

Instead:

1. Keep GPT Pro's hedge harness as an escalation/backlog option only.
2. Update PR #201 body/documentation as a negative-evidence PR.
3. Formalize a production/governance contract:
   - long-only only;
   - no hedge overlay;
   - MDD becomes a risk cap rather than the primary alpha target;
   - old `-25%` hard target is either retired or marked aspirational;
   - absolute CAGR `35/50` remains the primary improvement target unless the
     user changes it.
4. Move implementation focus to CAGR:
   - Main: PR #199 AI Capex / generic theme momentum tilt.
   - Concentrated: actual-results-confirmed hold-extension and/or another
     cap-safe winner-retention mechanism.
   - Continue PIT universe cleanup.

## What To Reflect Immediately

### Reflect from GPT Pro

Yes:

- Update PR #201 body before ready/merge.
- Label PR #201 as negative evidence.
- Include the full 8-arm event-defense table.
- State that no fullrun is justified.
- State that small cash/stop/cap variants are closed.

Backlog only:

- `run_main_hedge_overlay_broker_ab.py`
- `run_main_mdd_governance_packet.py`

These are useful if the user re-opens hedge research or insists on the old
`Main MDD >= -25%` hard target, but they conflict with the current no-hedge
direction.

### Reflect from Claude

Yes:

- Write a governance/acceptance contract.
- Reframe MDD as a risk cap.
- Focus on CAGR levers.
- Keep both sleeves consistent; do not loosen Main MDD while keeping
  Concentrated on the old hard cap.
- Add stop rules to prevent infinite CAGR lever hunting.

## Proposed Decision Record

Recommended wording:

> PR #201 exhausts cheap long-only Main MDD repairs. The project will not
> implement a hedge overlay unless the user explicitly reopens hedge research.
> Under the current long-only mandate, MDD is converted from a hard optimization
> target into a governance risk cap. The next implementation focus is CAGR:
> Main generic theme/AI Capex momentum tilt, Concentrated winner hold/retention,
> and PIT universe cleanup.

## Proposed Next Codex Work

1. Prepare PR #201 body update text:
   - actual scope;
   - full result table;
   - negative-evidence label;
   - no-fullrun statement.

2. Draft `PRODUCTION_ACCEPTANCE_CONTRACT.md` or equivalent:
   - long-only mandate;
   - MDD risk-cap proposal;
   - relative/risk-adjusted gates;
   - PIT universe blocker;
   - old hard target transition note.

3. Continue CAGR work:
   - do not revisit rejected cap-safe score-sizing as-is;
   - use PR #199 Main AI Capex result as Main CAGR candidate;
   - implement the next Concentrated candidate only if it proves PIT
     availability and applied-count first.

4. Keep hedge overlay as an explicit opt-in branch only:
   - only if user reverses the no-hedge decision;
   - must start with hedge-ticker price coverage preflight;
   - must use funded long inverse ETF form if measured by official broker
     replay.

