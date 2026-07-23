# Run287 H4b workflow/promotion trust result

Date: 2026-07-23

Scope: Issue #315 H4b only
Pull request: #322

## Result

The daily operating path is now fail-closed from the accepted paper
transaction through outcome resolution, scorecard reconstruction, promotion
evaluation, and artifact publication.

- Enforced order: paper transaction -> snapshot integrity -> outcome resolution
  -> runtime scorecard -> promotion gate -> post-gate reports -> accepted
  publication.
- Canonical governance states, thresholds, checks, rollback triggers, and rules
  are immutable at runtime. Malformed contracts produce a structured rollback.
- Runtime counters, evaluability, account pairing, and integrity availability
  reset before every overlay; missing evidence cannot preserve a stale pass.
- The scorecard must equal an independent rebuild from its exact source
  registry and verified paper snapshot. Metric/headline pruning or value
  tampering fails closed.
- Decision/outcome archives are replayed semantically from their append-only
  events, exact paths, source hashes, and frozen contracts. Late-recorded
  signals remain evidence but are excluded from promotion sample counts.
- Initial outcome-cache absence returns an explicit review-only bootstrap state;
  a second resolver pass is required before READY. SKIPPED output uses the same
  complete false safety envelope as READY.
- A single frozen outcome-parent anchor now binds the prior summary, exact
  event-log byte prefix, accepted-manifest identity, and any quarantined legacy
  prefix. The second resolver invocation must also present the exact first-pass
  summary hash, so a same-run suffix cannot be rewritten and resealed.
- Every accepted outcome state is stored under its accepted-publication
  manifest SHA. The manifest graph permits one root and one linear terminal,
  rejects forks, orphans, cycles, multiple roots, and parent-state reseals, and
  checks each child against the actual parent summary/event identity.
- Accepted outcome heads also bind the paper snapshot hash, complete ancestor
  chain, and genesis identity. A head can be installed only when its paper
  snapshot is the current verified ledger or a proven ancestor on the same
  genesis; a different paper fork cannot be grafted by matching only a date.
- Genesis and legacy-outcome migration are separate, mutually exclusive,
  one-time workflow-dispatch authorizations. Both require successful
  authoritative Drive discovery with no committed outcome head. Genesis also
  requires independently proven absence of the mutable legacy summary; a
  present legacy archive is fetched and checksum-compared before its entire
  prefix is quarantined.
- Full hash-addressed accepted-head bundles accumulate in the validated cache.
  This preserves every intermediate head across multiple Drive-offline runs;
  after recovery, the complete linear chain is reverified and each missing
  bundle is uploaded with its manifest last. Corrupt cache bundles are removed,
  while transient Drive discovery failures retain verified cache/local state
  without creating a new root.
- Paper heads now use the same commit-marker rule: payload files are synced and
  checksum-verified first, then `snapshot_integrity.json` is published last.
  Restore ignores marker-free partial directories, so an interrupted first
  bootstrap can resume instead of becoming a permanent false head.
- A pre-H4b integrity-bearing Drive canonical can become the first paper head
  only through an explicit one-time workflow-dispatch input. The migration
  performs full paper semantic replay, rechecks the remote source, commits the
  old canonical head before its local descendant, and preserves a durable
  migration evidence record.
- Accepted event JSON rejects duplicate object keys, missing or duplicate event
  IDs, unknown event types, summary/log count disagreement, unexpected bundle
  files, and symlinks. Accepted-head selection is iterative and has a regression
  chain beyond 1,200 daily heads.
- Paper fills, rejections, pending orders, accounts, positions, fees, realized
  P&L, reserve arithmetic, and equity curves are replayed from immutable
  bootstrap accounts instead of trusting stored totals.
- Every market fill is bound through its event hash to a frozen execution-price
  source inside the paper snapshot. Only the exact next NYSE session close is
  accepted; missing, later-substituted, same-day, future, stale, duplicate, or
  orphan price evidence blocks the atomic transaction.
- Snapshot continuity requires the same genesis, immutable bootstrap files,
  exact append-only fill/rejection/equity prefixes, and semantic replay.
  Self-asserted ancestry metadata alone cannot replace accepted state.
- Same-session continuity is permitted only for a direct, replay-clean
  `MARK_ONLY` -> `SELECTED_TARGET` descendant whose economic account state and
  historical ledgers are unchanged and whose only ledger extension is the
  exactly reconciled pending-order enqueue. Same-date reseals and divergent
  descendants remain blocked.
- Advancing a restored ledger preserves its existing fill-CSV header order, so
  a schema-equivalent descendant cannot be rejected as a false prefix rewrite.
- A pre-manifest legacy Drive snapshot can enter a one-time quarantine only
  when no verified cache or immutable head exists. It must pass structural and
  schema/safety checks for both portfolios, contain no stale acceptance
  metadata, receive semantic attestation during a mark-only replay, and be
  replaced through compare-and-swap by a newly verified immutable head.
  Partial account state, unsafe historical-replacement or live-approval flags,
  and non-mark-only migration attempts fail without mutating the ledger.
- Legacy mark-only replay may resolve already-pending or lifecycle events but
  may enqueue no new order. Same-session legacy state is normalized to an
  integrity-bound mark-only parent before the selected-target child; an
  unchanged selected target is valid and produces no unnecessary order.
- Legacy source-tree provenance becomes an immutable file inside the paper
  snapshot, remains bound through the selected-target pass, and is included in
  accepted artifacts, caches, and Drive state. Matching immutable heads remain
  recoverable after local-cache loss.
- Equity curves may omit prior daily marks without invalidating a later
  accepted snapshot. Persisted rows must still be unique, ordered NYSE
  sessions ending at the accepted as-of date; omitted sessions reduce the
  completed-session count instead of creating false promotion evidence.
- A newly observed outcome ticker with no restored price-cache file now emits
  the explicit review-only bootstrap state and complete price universe before
  the bounded cache builder reruns the resolver.
- Drive persistence writes a content-addressed immutable head before canonical
  publication, rechecks the canonical anchor before and after sync, validates
  head-folder/hash identity, and blocks divergent heads instead of overwriting
  them.
- Accepted GitHub artifacts, state caches, and accepted Drive packages publish
  only after canonical paper persistence/CAS succeeds (or its explicit
  no-Drive no-op succeeds), preventing a failed candidate cache from becoming
  the next continuity anchor.
- The accepted-publication manifest binds the gate step hash, every gate-read
  file, target/account/preview identities, scorecard, outcomes, and the complete
  paper snapshot. Reverification recursively checks every snapshot file.
- Accepted GitHub and Drive packages contain the decision archive and complete
  risk price cache, so the downloaded package can be independently reverified.
- Automatic champion replacement, state advancement, production activation,
  and live trading remain disabled.
- Trust boundary: this workflow is the repository-wide single writer for the
  mutable Drive canonical, enforced by its static GitHub concurrency group.
  Immutable paper/outcome heads are the accepted state; the canonical is only a
  recoverable mirror. Google Drive `rclone` updates are not an atomic CAS against
  an independent external storage writer. Conditional remote pointers,
  signatures, and external checkpoints remain U6 work and H4b does not claim
  storage-writer tamper resistance.

## Validation

- Promotion gate adversarial smoke: `35/35` PASS.
- Accepted-publication manifest smoke: `13/13` PASS.
- Immutable accepted-outcome head smoke: `21/21` PASS, including a
  three-generation offline/recovery chain and a 1,305-head longevity case.
- Daily simulated fill ledger: PASS.
- Paper-ledger transaction and real descendant installation: PASS.
- Paper snapshot continuity: PASS.
- Risk outcome archive and replay price cache: PASS.
- Runtime operating scorecard: PASS.
- Workflow artifact/order contract: PASS.
- Python compile and `git diff --check`: PASS.
- Full Tier-1 PR validation: `194/194` PASS in `372.36s`.

## Safety and next gate

H4a merged as PR #321. H4b is integrated with that master state and is ready
for exact-head PR checks and review. Durable chronological catch-up remains a
separate P0 operation after H4b merges.

- Fullrun executed: false.
- Durable catch-up executed: false.
- Production activation allowed: false.
- Live trading enabled: false.
