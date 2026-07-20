# Run287 P1 SecurityLifecycle Result — 2026-07-20

## Verdict

`READY_FOR_REVIEW_RESEARCH_ONLY`

P1 now uses one point-in-time `SecurityLifecycle` component for the current
scorer and the transactional forward-paper ledger. A missing quote is no
longer treated as permission to delete a security. Terminal settlement or
symbol continuity is applied only after the event is effective, exactly public
at the decision time, verified, and approved.

## Git boundary

- Base: `5ae494cd769f954ad628c4178ac844ab26563ebd` (`master`, P0 squash merge)
- Branch: `codex/run287-gtls-terminal-lifecycle-20260718`
- Prior stacked implementation preserved locally at:
  `codex/run287-gtls-terminal-lifecycle-20260718-pre-p0-merge`
- Unrelated draft PR #299 research was not imported.

## Lifecycle contract

- Schema: `run287-security-lifecycle-v1`
- Shared component: `tools/security_lifecycle.py`
- Stable security and issuer IDs are separate from current ticker aliases.
- Supported terminal events: cash merger, liquidation, bankruptcy, delisting.
- Supported identity events: ticker change and predecessor/successor mapping.
- Exact `available_from`, effective date, last trading date, source URL,
  stable event ID, source SHA-256, evidence status, and review status are
  mandatory.
- Cash mergers require positive verified consideration. Other terminal events
  require explicit verified delisting proceeds, including an explicit zero
  where recovery is zero. Missing recovery is not silently converted to zero.
- Duplicate active terminal events for one stable security fail closed.
- Events after decision time or before their effective date do not modify prior
  rows or current identity.

## Consumer behavior

### Current scorer

- Uses the shared component to exclude only actionable terminal securities.
- Receives verified ticker aliases from the same snapshot; no real ticker is
  hardcoded in scorer/orchestrator logic.
- Emits the applicable event rows, source hash, snapshot hash, terminal list,
  and provider-symbol mapping in its manifest.
- Keeps `pit_universe_label_clean=false` and
  `survivorship_coverage_claimed=false`.

### Forward-paper ledger

- Resolves the same lifecycle source before exact-close validation and before
  any durable publish.
- A held verified cash-merger security is removed at exact verified proceeds,
  with zero trading fee, cash and realized P&L reconciled, and an append-only
  `LIFECYCLE_SETTLEMENT` event.
- Pending orders for an actionable terminal security are deterministically
  rejected as `lifecycle_terminal_cancelled`.
- Terminal target weight is removed without reallocating it to another stock;
  the residual remains cash.
- A verified ticker change can use the successor quote while preserving the
  logical historical security identity.
- Source-target hash, effective-target hash, lifecycle source hash, and
  lifecycle snapshot hash are all included in same-session reuse validation.
- Weak evidence, missing proceeds, duplicate events, or lifecycle/source drift
  blocks before the P0 directory transaction can publish any durable file.

## Actual pinned evidence

- Source:
  `data_static/run287_exact_packet/security_lifecycle_events.csv`
- Source SHA-256:
  `09e2fd19a127c281dd8f69988d8ac454183133a638752fbb6d7884c947e86f24`
- Decision fixture: session `2026-07-17`, decision time
  `2026-07-17T22:00:00Z`
- Applicable events: 2
- Terminal events: 1 (`GTLS`)
- Identity events: 1 (`IAC` logical identity, `PPLI` provider symbol)
- Snapshot SHA-256:
  `40df35abab0474e2bde6c3cd95350eec654f7a097f49038c34d8c0e6a99e8335`

The event rows are data, not ticker-specific production branches. A regression
test scans the scorer, ledger, and upstream orchestrator for real ticker
branches.

## Generic event tests

- verified cash merger: PASS
- event public after decision time: PASS, no action
- event before effective date: PASS, no action
- duplicate active terminal event: PASS, fail closed
- bankruptcy without verified recovery: PASS, fail closed
- ticker rename: PASS
- predecessor/successor mapping: PASS
- malformed stable ID/source hash: PASS, fail closed
- missing cash proceeds: PASS, fail closed
- ordinary active ticker: PASS, retained
- terminal held position without a future close: PASS, settled from verified
  proceeds
- terminal pending order: PASS, lifecycle cancellation
- event-chain validation after settlement: PASS

## Validation

- Focused lifecycle, scorer, ledger, bootstrap, transaction, upstream, and
  workflow fixtures: PASS
- Full Tier-1 PR validation: `178/178` passed in `617.12s`
- Workflow YAML/static contract: PASS
- `git diff --check`: PASS
- Bounded upstream preflight: lifecycle file/hash PASS; overall status remained
  `SKIPPED_EXACT_PACKET_UPSTREAM_PREREQUISITES` because this local checkout
  lacks the materialized model, price-cache, and static-anchor directories.
  Network requests executed: 0.

## Safety and performance boundary

- Fullrun executed: `false`
- Historical backtest executed: `false`
- Target-book policy changed: `false`
- Production enabled: `false`
- Live trading enabled: `false`
- Historical CAGR/MDD changed: `false`

P1 repairs identity, delisting, and paper-account accounting integrity. It is a
prerequisite for trustworthy same-close selection and risk work; it is not
itself an alpha claim.
