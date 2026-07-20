# Run287 P0 Forward Paper Ledger Transaction Result

Date: 2026-07-20
Scope: issue #306 P0 / draft PR #300 only
Fullrun: not executed
Production/live trading: disabled

## Outcome

The forward-paper ledger now computes both portfolios in isolated candidate
directories and publishes the state as one checksummed directory transaction.
Any validation or injected publication failure restores the prior state and
preview directories. Same-session retries preserve the first verified mark and
do not rewrite the root summary or checksum.

The genesis contract records deterministic account IDs, seed dates, starting
capital, both seed target hashes, bootstrap hashes, execution policy hash,
next-close/integer-share/25 bps settings, sell-before-buy, nonnegative cash, and
the maximum fill lag. A missing canonical account after its genesis date returns
`BLOCKED_MISSING_PERSISTENCE_AFTER_GENESIS` instead of creating a new seed.

Every new-session snapshot includes `snapshot_integrity.json`. Restore and save
paths verify its exact file set and SHA-256 values. Google Drive persistence
first uploads and checks a run-specific recovery copy, then replaces and checks
the canonical archive.

## Focused verification

- `tests/run287_paper_ledger_transaction_smoke.py`: PASS
  - 20 consecutive business sessions without reseeding
  - same-session full-state hash equality
  - second-portfolio stale-close failure with zero durable changes
  - injected partial-publication rollback with zero state/preview changes
  - duplicate client-order-ID and negative-cash rejection
- `tests/daily_simulated_fill_ledger_smoke.py`: PASS
- `tests/run287_daily_paper_bootstrap_smoke.py`: PASS
- `tests/replay_price_cache_smoke.py`: PASS
- `tests/run287_holding_risk_watch_smoke.py`: PASS
- `tests/workflow_artifact_smoke.py`: PASS
- workflow YAML parse: PASS

Focused PR validation: `6/6` passed in `26.25s`.
Full Tier-1 PR validation: `177/177` passed in `475.61s`.

## Boundaries

- No historical CAGR/MDD, target weights, selector, alpha, dashboard, or live
  order path was changed.
- A legacy snapshot without the new checksum may be semantically validated once
  and is attested only after a successful transactional session. An invalid
  checksummed snapshot is never silently overlaid with another source.
- P1 SecurityLifecycle remains blocked until P0 review and merge approval.
