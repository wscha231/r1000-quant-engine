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
- a successor cache containing only future rows also fails closed instead of
  falling back to account price or cost basis;
- post-cutover preview positions and orders use the verified successor ticker,
  while retaining the predecessor as `logical_ticker` for audit;
- successor-symbol orders aimed at an existing predecessor holding retain a
  separate `ledger_ticker`, so next-close settlement updates the position that
  actually exists while preserving the real execution symbol;
- zero-position successor targets are priced through their logical lifecycle
  link and therefore cannot bypass the exact requested successor close;
- `--target-date` and lifecycle decision-time lookup use the same selected
  target snapshot, so an older replay cannot borrow a later decision timestamp;
- legacy manual sidecar workflows require an explicit UTC decision time for
  lifecycle-aware previews and no longer mask preview failure with `|| true`;
- Phase A/B quick rescore follows the same decision-time contract and no longer
  hides a failed sidecar invocation;
- verified terminal holdings or targets make standalone preview fail closed,
  preventing a last stale predecessor close from becoming a ready order;
- script-style Tier-1 smoke coverage remains dependency-minimal and does not
  assume `pytest` is installed by `requirements_github.txt`;
- restored absolute lifecycle paths may be rebound only through the exact
  repository-relative `data_static` tree and matching SHA-256;
- standalone CLI preview invocations now load the canonical lifecycle file;
  missing exact decision-time evidence blocks rather than bypassing lifecycle;
- verified terminal proceeds are included in the resolved snapshot hash.

## Regression evidence

- Focused H2 suite after review fixes: `52 passed`.
- Exact-successor regression plus the representative H2 pytest subset:
  `51 passed`; standalone account-preview smoke: PASS.
- Repository pytest: `129 passed`.
- Final-review follow-up: account preview PASS, source-bundle `4/4`, daily
  ledger PASS, paper transaction PASS, and workflow artifact smoke PASS.
- Full Tier-1 PR validation: initial `191/191` in `692.56s`; reviewed-head
  revalidation `191/191` in `582.37s`; exact-successor revalidation `191/191`
  in `499.92s`; final CLI/symbol/archive integration revalidation `191/191`
  in `464.10s`.
- Python compilation and `git diff --check`: PASS.
- Additional execution-boundary follow-up: account preview PASS, daily ledger
  PASS (including predecessor-keyed exit settlement), workflow artifact PASS,
  source bundle `4/4`, paper transaction PASS, repository pytest `129/129`.
  The first Tier-1 rerun passed `190/191`; the sole structural failure was
  corrected by keeping the new decision-time input outside the four-field
  fullrun approval block, after which `tests/smoke_test.py` passed `129/129`.
  Exact-head GitHub CI is still required before merge.

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
