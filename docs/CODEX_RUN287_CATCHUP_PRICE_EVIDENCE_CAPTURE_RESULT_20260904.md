# Run287 Read-Only Catch-Up Price Evidence Capture Result

Date: 2026-09-04
Branch: `codex/run287-catchup-evidence-capture-20260904`
Base master: `ec39d0c17e5459a0a72216095a84c46e38b61cc7`
Status: `MERGED_CAPTURE_EXECUTION_BLOCKED_PRE_DRIVE`

## First merged execution

The first exact-master dispatch was run on 2026-09-05 through completed NYSE
session `2026-09-04`:

- workflow run: `33944035434`
- capture job: `101246758073`
- source SHA: `34bab52743c238c3419db0d03d17a366645459da`
- transactional `refresh` job: `skipped`
- capture result: `failure` before Drive access
- failed step: `Configure temporary read-only rclone for capture`

The pinned rclone ZIP passed SHA-256 verification, but the job-level
`RCLONE_VERSION=1.75.0` installer variable collided with rclone's Boolean
`--version` environment option. The binary rejected `1.75.0` as a Boolean.
Credential cleanup succeeded; Drive download, artifact construction, artifact
upload, migration, quarantine, target/order/ledger mutation, catch-up,
production, and live trading did not run.

The isolated hotfix renames installer version and ZIP-checksum variables under
the `RUN287_CAPTURE_*` namespace. The same causal collision is removed from the
separate read-only recovery preflight under `RUN287_PREFLIGHT_*`. It does not
change rclone bytes, the pinned ZIP hash, `drive.readonly`, evidence validation,
or any state authority. A fresh dispatch is required after merge; the failed
job must not be rerun.

## Outcome

This change supplies the missing read-only evidence step between the verified
2026-07-24 paper terminal and chronological catch-up. It does not run a paper
transaction, migration, quarantine, target build, order build, backtest,
fullrun, production publication, or live trade.

The prior daily artifacts cannot safely fill this gap. They contain a market
snapshot for the latest completed session seen by that run, not a hash-bound
snapshot for every missing session beginning 2026-07-27. The existing
historical `--asof-date` path also selected the final cache row before this
change, so a future row could be relabeled with an earlier requested date.

## Closed capture contract

| Boundary | Enforced result |
|---|---|
| Dispatch | New boolean defaults false; only the separate capture job runs when true |
| Run identity | Exact default-branch SHA, `workflow_dispatch`, and first run attempt only |
| Requested date | Must be the exact latest completed NYSE session and at least 90 minutes after close |
| Drive | `drive.readonly`; only canonical paper and immutable paper heads are copied remote-to-local |
| Paper identity | Canonical manifest and the complete physical immutable-head chain are reverified before and after planning |
| Sessions | Every NYSE session after the canonical as-of date through the requested date is independently enumerated; gaps are rejected |
| Tickers | Union of both effective target books, held positions, pending orders, and SPY/QQQ/SMH/SOXX |
| Prices | Fresh isolated cache; every ticker must have an exact close for every enumerated session |
| Future rows | Rows after each session are excluded before snapshot construction |
| Artifact | Plan, paper selection, source-cache manifest, every session gate/snapshot/report, byte count, SHA-256, and exact file set are closed |
| Consumer | Recomputes the NYSE sequence, validates the whole artifact tree, then materializes only the requested session into a replay-only cache |
| Pattern evidence | The new multi-session artifact is explicitly price-only; a post-launch ledger mark records the exact session as pattern-blocked and keeps all pattern statistics/proposals ineligible instead of using later data |
| Mutation | Drive, ledger, targets, orders, accepted heads, production, and live trading remain unchanged |

The artifact keeps the existing daily artifact name so the already-reviewed
download/provenance path remains authoritative. A root marker forces
`actions/upload-artifact` to retain the full
`outputs/run287_catchup_price_capture/...` namespace rather than flattening it.

## Defects closed

1. `build_daily_market_snapshot.py` now filters cache rows at or before the
   requested as-of date before choosing a price. Strict capture mode blocks
   unless every emitted ticker has that exact session close.
2. Same-named `main/effective_target_latest.csv` and
   `concentrated/effective_target_latest.csv` inputs no longer overwrite one
   another in ticker-source provenance.
3. The multi-session consumer does not trust a manifest alone. It checks the
   exact artifact file set, all file hashes, source workflow identity, first
   attempt, source-cache contract, ticker union, complete NYSE session
   sequence, timestamps, and per-session exact-close summaries.
4. A capture rerun is rejected. A fresh dispatch must create a new run ID and
   artifact digest.
5. The transactional consumer now distinguishes the legacy single-session
   artifact from the new price-only multi-session layout. Legacy pattern
   evidence retains its existing closed validation path. A multi-session
   price slice can advance only the paper mark; the exact session is recorded
   as `price_only_capture_pattern_evidence_unavailable`, and pattern memory
   remains `BLOCKED` and proposal-ineligible. No current data is backfilled as
   historical pattern evidence.
6. The P0-4 protected-publication test pin now matches the exact protected
   causal ancestor `a154552e6f627f1fdc34e0dd7dc53f55475aa4d5`.

## Changed files

| File | Purpose |
|---|---|
| `.github/workflows/daily_operating_selection_refresh.yml` | Isolated read-only capture job and default-off dispatch input |
| `tools/build_run287_catchup_price_capture.py` | Plan and build the closed multi-session artifact |
| `tools/build_run287_catchup_price_evidence.py` | Consume either the new capture or the prior single-session artifact contract |
| `tools/build_daily_market_snapshot.py` | Historical cutoff and strict exact-as-of close gate |
| `tools/validate_daily_close_prices.py` | Collision-free target source identities |
| `tools/verify_run287_catchup_scope_attestation.py` | Require capture mode false for any later transactional catch-up |
| `tools/run_pr_validation.py` | Register the new critical capture smoke test |
| `tests/*` | Producer, consumer, workflow, chronology, pattern fail-closed, protected-lineage, tamper, and compatibility regression coverage |

## Validation

Focused validation passed:

- `daily_market_snapshot_smoke.py`
- `daily_market_close_gate_smoke.py`
- `run287_catchup_price_capture_smoke.py`
- `run287_catchup_price_evidence_smoke.py`
- `run287_github_secret_scope_smoke.py`
- `run287_catchup_drive_readiness_smoke.py`
- `run287_ohlcv_location_timing_workflow_smoke.py`
- `workflow_artifact_smoke.py`
- `run287_paper_ledger_transaction_smoke.py`
- targeted P0-4 protected-publication lineage check
- Python compilation, workflow YAML parse, and `git diff --check`

The earlier complete local registered run finished `217/227`. Its P0-4
protected-publication failure included a stale test pin owned by this change;
that pin is now corrected and its targeted lineage check passes. The remaining
local-only failures cannot reproduce the CI environment in the intentionally
sparse checkout because of missing `aggressive/`, `auto_learning_v2/`, and
`research/` paths and local PyArrow 25.0.1 versus the P0-3 pinned 23.0.1
environment. The authoritative pull-request CI must be fully green on the new
exact head before merge.

## Current operational truth

The last verified paper state remains 2026-07-24 with terminal
`65fa6f5b4b12729811b72a90661fc744320826dfe868ec6da2632768b1ec02a7`.
The earliest pending session remains 2026-07-27. No result from this branch may
be called the current portfolio because the capture, separately approved
migration, and chronological session-by-session catch-up have not run.

## Rollback

Revert this change or remove the default-off capture job. No durable financial
state requires rollback because this change creates no accepted state and has
not been dispatched. Any capture artifact is replay-only evidence and can be
allowed to expire without changing the canonical ledger.

## Next gate

After exact-head review and green PR checks, merge this evidence-only change.
Then dispatch the capture once on exact master for the latest completed NYSE
session, pin its run ID, artifact ID, digest, source SHA, paper terminal, and
session range, and independently consume the 2026-07-27 slice. Only after that
evidence is verified should a fresh migration-only approval packet be
prepared. Migration and catch-up still require their own explicit authority.
Price-only catch-up must leave post-2026-07-29 pattern research blocked until
separately pinned first-attempt pattern evidence exists; that block does not
permit target generation, orders, or pattern proposals.
