# Run287 G0/H1 review and paper-transaction hardening result

Date: 2026-07-21

Scope: Issue #315 G0 and H1 only

Performance impact: none; this is integrity and operating-state hardening

## G0 result

- PR #316 was reviewed, corrected, re-reviewed, and merged as
  `0ab5b2f203ba7efb93ebcbb3ee170040e4b26012`.
- `master` now requires the exact check contexts `validate`,
  `portfolio_guard`, and `review_complete` with strict up-to-date branches,
  conversation resolution, stale-review dismissal, and administrator
  enforcement.
- The custom `review_complete` check is written only by a trusted
  `pull_request_target` workflow. It requires a write-authorized actor to post
  `/review-complete <exact 40-character current head SHA>` after the trusted
  head observation and after clean current-head Codex review evidence.
- A prior attempt to create the bootstrap check with a personal `gh` token was
  rejected by GitHub (`403`, GitHub App required). The result was recorded and
  not bypassed. Protection was enabled in two phases around the reviewed merge.

## H1 implementation result

The paper mark, selected target, account state, and order preview now have one
hash-bound transaction boundary.

- Every preview records the portfolio, mode, as-of date, target effective date,
  exact or rule-based next-close eligibility, accepted account hash, source and
  effective target hashes, normalized target hash, order/weight file hashes,
  and a canonical preview identity hash.
- A mark-only pass produces an explicit `NO_NEW_ORDER` preview with an empty
  order table. Missing output is no longer used to mean no order.
- Existing same-session previews are parity-checked. A missing or stale preview
  is rebuilt from the frozen account mark; a valid rerun is idempotent.
- The preview-only transaction journal is recovered before any state is cloned;
  an abrupt process interruption cannot leave an uncommitted preview visible
  to the next same-session reuse.
- The supported same-session transition is
  `MARK_ONLY -> SELECTED_TARGET -> MARK_ONLY`. The final mark-only pass may
  replace the review preview but leaves durable ledger bytes unchanged.
- The Main and Concentrated public operating target files are staged and
  published in the same rollback-capable bundle as both ledger and preview
  directories. Both public paths are required together.
- `accepted_publication.json` binds source and published target hashes, account
  hashes, ledger-manifest hashes, and preview identities. Repository paths are
  stored portably so restored artifacts are not tied to one runner directory.
- A legacy same-session snapshot without a checksum manifest is accepted only
  once after semantic validation, receives a checksum and acceptance
  attestation, and is byte-identical on the next rerun.
- The always-uploaded failure/evidence artifact excludes public operating
  targets, user order reports, order previews, and paper-ledger state. Those
  files are uploaded and synced to Drive only after the operating step and
  integrity verification succeed.

## Fixture and regression evidence

- Fixture-first failure: the pre-change suppressed path did not produce
  `order_batch_manifest.json`, proving the explicit no-order contract was
  absent.
- The H1 fixture now proves explicit no-order output, same-session transitions,
  stale-preview repair, atomic rollback after `after_publish_2`, public-target
  parity, preview-journal crash recovery, one-time legacy attestation, and
  failure-artifact separation.
- `run287_paper_ledger_transaction_smoke.py`: PASS.
- Workflow YAML parsing and Python compilation: PASS.
- Repository pytest: `129 passed`.
- Full Tier-1 PR validation: `191/191` passed in `591.30s`.

No real daily ledger, public operating target, or Drive archive was mutated by
these tests. No fullrun, production activation, or live order was executed.

## Performance status and next gate

The official historical evidence remains unchanged:

- Main: CAGR `34.4032%`, MDD `-25.3629%` through 2026-07-10.
- Concentrated: CAGR `49.0968%`, MDD `-22.9560%` through 2026-07-10.

These are not 2026-07-17 or 2026-07-20 refreshed performance figures. H2
security-lifecycle correctness must not start until H1 is reviewed, merged, and
the same-session smoke passes on the exact merge SHA. Durable catch-up and any
new CAGR/MDD challenger remain blocked until H1-H4 are complete.
