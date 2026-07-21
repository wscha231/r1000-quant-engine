# Run287 H2 security-lifecycle correctness result

Date: 2026-07-21

Scope: Issue #315 H2 only

Performance impact: none; this is point-in-time identity, settlement, and
evidence-integrity hardening

## Result

The scorer, exact-packet source bundle, paper ledger, and order preview now use
one shared `SecurityLifecycle` contract for terminal events and verified
predecessor/successor links.

- A ticker change or security successor records the predecessor last trading
  date and successor effective date. Historical predecessor prices are used
  through the last trading date; verified successor prices are used only
  afterward.
- An identity event is rejected if the successor effective date does not
  strictly follow the predecessor last trading date.
- On delayed catch-up, pending orders eligible before a terminal event are
  resolved first. Only remaining ineligible pending orders are cancelled when
  terminal settlement is applied.
- Cash merger, liquidation, bankruptcy, and delisting proceeds require exact
  verified evidence. Non-USD proceeds fail closed with the dedicated status
  `BLOCKED_NON_USD_LIFECYCLE_PROCEEDS`; no implicit FX conversion is allowed.
- If terminal filtering removes the last stock target, the materialized target
  becomes explicit `CASH=1.0` rather than retaining a partial residual weight.
- Same-session paper reuse requires both lifecycle source and resolved snapshot
  SHA-256 values. Exact-packet source-bundle creation also re-hashes the source
  file and rejects a missing, changed, or mismatched lifecycle identity.
- The former fixed `989` selection-context assumption is removed. The scorer
  requires the independent upstream plan's expected pre-lifecycle count, then
  the scorer and decision frame enforce the dynamic invariant
  `pre_lifecycle = excluded + post_lifecycle` and require unique post-lifecycle
  tickers.
- The shared component remains generic. No actual ticker-specific branch was
  added.

## Fixture-first evidence

Before the fixes, focused fixtures reproduced four concrete failures:

1. delayed catch-up settled a terminal position without first filling an
   earlier eligible order;
2. a ticker-change mark used the predecessor close (`80`) instead of the
   verified successor close (`120`);
3. removing the final stock left an effective target at only `CASH=0.5`;
4. same-session reuse accepted a bundle without a lifecycle source hash.

The completed fixture set now also proves:

- predecessor price on the last predecessor session and successor price on the
  next session;
- rejection of an overlapping identity cutover;
- dedicated non-USD terminal-proceeds blocking;
- changed lifecycle source bytes block exact-bundle creation;
- no fixed `989` literal remains in the scored-latest or decision-frame
  lifecycle count contracts.
- a lifecycle-linked scorer retains predecessor rows through the last trading
  date and accepts successor rows only from the effective date;
- an empty source target blocks rather than synthesizing `CASH=1.0`, and a
  missing successor cache cannot fall back across the verified cutover;
- a successor cache containing only pre-effective or pre-session rows is
  rejected; a lifecycle-linked preview requires the exact requested successor
  close after cutover;
- verified terminal proceeds are included in the resolved snapshot hash.

## Regression evidence

- Focused H2 suite after review fixes: `52 passed`.
- Exact-successor regression plus the representative H2 pytest subset:
  `51 passed`; standalone account-preview smoke: PASS.
- Repository pytest: `129 passed`.
- Full Tier-1 PR validation: initial `191/191` in `692.56s`; reviewed-head
  revalidation `191/191` in `582.37s`; exact-successor revalidation `191/191`
  in `499.92s`.
- Python compilation and `git diff --check`: PASS.

The tests used temporary fixtures. No durable paper account, public operating
target, downloaded artifact, Drive archive, or existing untracked output was
modified. No fullrun, production activation, or live order was executed.

## Performance status and next gate

Official historical evidence remains unchanged:

- Main: CAGR `34.4032%`, MDD `-25.3629%` through 2026-07-10.
- Concentrated: CAGR `49.0968%`, MDD `-22.9560%` through 2026-07-10.

These are not refreshed 2026-07-17 or 2026-07-20 figures. H2 must receive a
clean current-head review, merge, and exact-merge smoke before H3 risk/Reserve
correctness begins. Durable catch-up and any new CAGR/MDD challenger remain
blocked until H3 and H4 are also complete.
