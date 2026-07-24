# Run287 H4b workflow/promotion trust result

Date: 2026-07-23 (final hardening validated 2026-07-24)

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
- Historical catch-up is an explicit forced, chronological, replay-only path.
  It may mark the already accepted accounts but cannot recompute targets,
  enqueue orders, resolve same-close decisions, outcomes, scorecards, or
  promotion. Every exact source cache is copied into the paper snapshot and
  recursively hash-bound before the transaction is accepted.
- Catch-up rows are excluded from forward promotion evidence even when they
  extend the equity curve. The durable replay-evidence registry is reverified
  before forward sessions are counted, and the public dashboard labels any
  related fill as `FORWARD_PAPER_REPLAY` instead of presenting it as live
  forward evidence.
- GitHub catch-up artifacts require an exact run ID, artifact ID and API/ZIP
  digest, repository and workflow identity, run state, branch and commit
  lineage, timestamps, and an exact metadata schema. Non-legacy evidence must
  come from a default-branch ancestor of the current exact default head. The
  sole approved legacy artifact is pinned separately and cannot widen the
  exception.
- The GitHub compare contract uses the actual API fields: `base_commit`,
  `merge_base_commit`, `status`, `ahead_by`, and `behind_by`. It does not rely
  on a nonexistent `head_commit` field.
- A common cross-mode cache now retains the full immutable paper-head chain,
  not only the mutable terminal. Normal and catch-up runs therefore recover
  across multiple Drive-offline sessions without creating a fork or losing an
  intermediate accepted state.
- Equity curves and event CSVs append with a frozen header and byte prefix.
  Pandas serialization is not allowed to rewrite accepted floating-point text
  when a later session is added.
- Default-branch sole-writer checks compare the workflow SHA to the current
  remote default head at start, before durable data and marker writes, before
  canonical and accepted-package publication, immediately before cache saves,
  and after final publication. If the branch advances, no subsequent accepted
  artifact or cache is published.
- Normal forward-paper selection now invokes the freshness contract in
  unconditional strict mode before the first paper-ledger transaction.
  `strict_selection=false` cannot bypass the gate. The restored pre-refresh
  score is diagnostic only; it cannot authorize a target mutation.
- The attempt-specific exact scorer owns the mutation coverage contract. Its
  post-lifecycle candidate denominator requires at least 98% complete `px`,
  score, 1/3/6/12-month momentum, relative strength, valuation cutoff, and
  feature-availability data. Ranking eligibility flags remain a separate
  selector contract. Duplicate, placeholder, substituted, unexpected, stale,
  or future rows fail closed.
- The 2% completeness allowance applies only to missing non-price numeric alpha
  fields. An invalid ticker, non-positive/non-finite close, wrong valuation
  date, or future `feature_available_from` is a hard PIT-integrity violation:
  one such row blocks the packet even when aggregate completeness remains above
  98%.
- Legacy exact-scorer v3 and earlier bundles do not contain this declaration and are
  intentionally non-authoritative. They are not silently migrated or reused for
  a same-session target mutation; that session remains blocked unless an
  explicit reviewed migration is added, while the next fresh session uses v4.
- The exact-packet registry consumes the current workflow-attempt upstream
  status and verifies every source-bundle path and declared SHA. It also binds
  the internal DAG by hash: decision to exact score/macro, score stack to
  decision, crisis to macro, and SOXX to crisis. Same-date, same-universe
  manifests from different attempts therefore cannot be mixed.
- The exact-packet chain now freezes one self-hashed code identity containing
  the Git HEAD/tree plus LF-normalized bytes for the daily workflow and every
  upstream, scorer, bundle, registry, producer, selector, and candidate-risk
  builder. Upstream, the immutable source bundle, registry, and producer all
  compare that identity with the current checkout, including immediately
  before READY publication. A same-date bundle from another commit or changed
  builder therefore collides instead of being silently reused.
- Before any network-backed score refresh, the upstream attempt freezes and
  hashes the universe, base context/stack, four model artifacts, OOS frame, and
  lifecycle file. It independently records universe, pre-lifecycle, and
  post-lifecycle ticker-set identities plus every potentially consumed
  historical price-cache file. The scorer validates those anchors before read,
  rehashes them before READY, and the registry cross-checks the scorer manifest
  against the exact attempt preflight. A same-count ticker substitution,
  missing-cache bootstrap, or changed model/cache therefore has an explicit,
  reproducible outcome rather than an implicit fallback.
- Exact-close technical rows advance `feature_available_from` to at least the
  actual scheduled NYSE close, including half days, while preserving any later
  inherited availability. `score_available_from` remains the separate scorer
  completion time. A pre-close decision time, malformed/future holding-watch
  availability, or future inherited feature timestamp blocks selection.
- Relative-strength benchmarks are closed inputs. SPY, QQQ, and SMH must each
  have exactly one hash-pinned macro-audit row and an exact valuation-date
  close; only those three verified files enter an isolated selector cache.
  SOXX remains independently manifest-bound. All source and isolated hashes
  are rechecked after selector/risk evaluation and before producer READY.
- An immutable producer reuse is not a shortcut around validation. Every
  decision, score, crisis, price, macro, SOXX, and price-map transitive output
  is revalidated before `READY_EXISTING`, and every path-bearing producer input
  is rehashed again immediately before either READY status is published. The
  registry must bind the exact producer-contract SHA, and reuse additionally
  binds holding-watch bytes, risk contracts, builders, git head, and selector
  holding inputs through one canonical packet-input identity.
- Producer-generated files are also roots of trust. The selector's exact ten
  declared outputs and the candidate-risk packet's exact three declared
  outputs, including `risk_history.jsonl`, must use their canonical packet
  directory and filename, may not be symlink aliases, and must match recorded
  existence, byte size, and SHA-256. Fresh builds validate before reading the
  comparison, after risk evaluation, and immediately before READY; reuse
  repeats the same checks and preserves the frozen output audit in status.
- Normal-session workflow retries clear prior same-close materializations
  before the chain starts. Upstream, registry, or producer failure writes a
  current BLOCKED marker and cannot leave a restored READY status or target
  artifact available to the summary, decision archive, or artifact upload.
  Catch-up also clears any restored run-local target materialization before
  publishing its replay-only BLOCKED marker.
- Same-close target materialization requires the exact freshness status and
  snapshot manifest for the session, run ID, commit SHA, branch, and artifact.
  It then independently recomputes the attempt-specific 98% contract and
  reconciles the scored-file SHA, expected ticker-set SHA, lifecycle counts,
  decision-context ticker set, valuation date, and score availability. Every
  mutation-bound file receives an unlimited streaming SHA-256 and is rechecked
  immediately before target write, and every just-written target/decision byte
  is rehashed again before READY. A blocked, stale, mismatched, or concurrently
  changed input removes prior run-local target artifacts, writes no new target,
  preserves accepted ledger/canonical state, and cannot reach the second ledger
  transaction.
- The target boundary accepts only producer schema v1 with one of the two exact
  READY statuses and `exact_packet_ready=true`; a legacy, BLOCKED, or forged
  marker cannot authorize target bytes even if its nested file hashes are
  otherwise self-consistent.
- The second paper-ledger transaction receives the exact same-close status SHA
  plus both target-book SHAs. The ledger validates schema/status/safety/date,
  canonical paths, and file hashes before processing and again immediately
  before same-session return or atomic publication, closing the target-to-ledger
  handoff rather than trusting workflow order alone.
- Trust boundary: this workflow is the repository-wide single writer for the
  mutable Drive canonical, enforced by its static GitHub concurrency group.
  Immutable paper/outcome heads are the accepted state; the canonical is only a
  recoverable mirror. Google Drive `rclone` updates are not an atomic CAS against
  an independent external storage writer. Conditional remote pointers,
  signatures, and external checkpoints remain U6 work and H4b does not claim
  storage-writer tamper resistance.

## Real artifact and chronological replay validation

The final code was exercised against four exact GitHub artifacts in temporary
local storage. This was a non-durable rehearsal: it did not mutate GitHub,
Drive, production, or the live/paper canonical.

| Session | Run | Artifact | ZIP SHA-256 | Tickers | Anomalies |
|---|---:|---:|---|---:|---:|
| 2026-07-17 | 29625744031 | 8424009573 | `703c34ffbbca84221c2c4448d1f95e75d696d6c52323435cd267429364793242` | 53 | 2 |
| 2026-07-20 | 29801446668 | 8484210406 | `dbfea52e2011c6e15213bc16fb85aa5f90d682ed91ba510d2cd654f017f5192d` | 24 | 0 |
| 2026-07-21 | 29891348660 | 8518649969 | `5d234b34b452ebedfc848cfb2f076b20e27d4d9891cb4f0c92d972c9c2c05d11` | 24 | 0 |
| 2026-07-22 | 29979802627 | 8553065730 | `15df41d43c698d3990c3acdc986ba62bbdab210d8fd703f6ed889fd1fb891c99` | 24 | 0 |

- The approved 2026-07-17 legacy tree had 20 files and exact tree SHA-256
  `8d8b39e1a9e49b27e5a16bee0c511b5e5627eb8a5443911e7ad5de2539fc204a`.
- The same-session legacy revision audit found no economic revision:
  main maximum relative difference
  `1.963096399367302e-16`, concentrated `0.0`, zero revised tickers, and no
  remark. Both are below the 1 bp (`0.0001`) gate and preserve the accepted
  mark.
- The source contains two 2026-07-17 reference-OHLC anomalies: ATO open
  `176.0399932861328` is below low `176.8800048828125`, and DTM open
  `148.07000732421875` is above high `147.6199951171875`. Raw values and anomaly
  codes are preserved, while those opens are explicitly ineligible for
  execution. Exact close remains usable only for replay mark/next-close fill.
- Sequential results were `LEGACY_SCHEMA_UPGRADE` for 2026-07-17 followed by
  three `RESTORED_CONTINUATION` sessions. Every session suppressed new orders;
  enqueued orders and resolved fills were both zero.
- The four-head chain passed semantic descendant verification and full-chain
  reconciliation. Its selected terminal is
  `f2c95d8c1ca3b1f1fe1fd76f25a65be42734ab5238722222d02a6b8d88b79ebf`
  as of 2026-07-22.
- Both portfolios reported four excluded replay observations and only one
  eligible pre-existing forward observation, proving catch-up cannot satisfy
  the 60-session promotion threshold.
- Final temporary validation evidence:
  `H:\codex\_tmp_run287_h4b_v2_real_replay_20260724_01`.

## Validation

- Promotion gate adversarial smoke: `36/36` PASS.
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
- Workflow YAML: 48 steps parsed; Git Bash syntax: 34 run blocks PASS.
- Final read-only security audit: no blocking finding.
- Full Tier-1 PR validation: `196/196` PASS in `857.13s` on the final
  code-lineage, generated-output, and target-to-ledger handoff tree.

## Safety and next gate

H4a merged as PR #321. H4b is integrated with that master state and is ready
for exact-head PR checks and review. Durable chronological catch-up remains a
separate P0 operation after H4b merges.

The master-only `run287-paper-durable` GitHub environment now exists and the
daily job declares it. One operational residual cannot be completed from source:
a rerun of a pre-H4b workflow uses its historical YAML while the two Drive
credentials remain repository-level secrets. Before durable catch-up, rotate
and add `GOOGLE_SERVICE_ACCOUNT_KEY` and `RCLONE_CONFIG_GDRIVE` to the
environment, verify their timestamps, then delete the repository-level copies.

- Fullrun executed: false.
- Durable catch-up executed: false.
- Production activation allowed: false.
- Live trading enabled: false.
