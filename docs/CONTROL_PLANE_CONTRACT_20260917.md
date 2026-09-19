# Control Plane Contract — 2026-09-17

## Decision

The next integration work is not a new alpha module. It is a shared control-plane contract that makes existing Theme/ETF, 13F/Form4, company-quality, earnings/consensus, macro, commodity and KR research interoperable without granting trade authority.

## Layering

1. Candidate / Leadership — discovery and priority only.
2. Expected Return / Thesis — investment merit and price.
3. Regime / Risk Overlay — aggregate exposure only.

## Four separate company decisions

Every company evaluator must preserve four distinct states:

1. Is it a good company?
2. Is it a good stock?
3. Is the current price attractive?
4. Does it fit the current portfolio risk/reward?

A positive answer to one cannot silently imply the others.

## Book authority

The five books remain separate:

1. Research Signal
2. Target Book
3. Simulated Execution
4. Paper Book
5. Actual Broker Book

Fact priority is `Actual Broker > Approved Target > Verified Paper > Simulation > Research`.

## Reproducibility completion criterion

A research result is reproducible only when the same immutable inputs, code SHA, config hash and decision cutoff reproduce the same semantic output. A changed decision must point to changed data, price, thesis, regime or model/config evidence.

## Merge strategy while Codex review quota is exhausted

- Implement low-risk contracts and fixtures in the isolated `research_only/control_plane/` path.
- Do not modify selectors, workflows, schedulers, target writers, accepted ledgers or broker paths.
- Keep PRs draft/unmerged while current v2 review-complete requires Codex exact-head evidence.
- After review-gate v3 is validly merged, classify the low-risk contract slice under the new policy rather than bypassing the current gate.
