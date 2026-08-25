# Run287 P0-4 migration map

Frozen at `2026-08-25T12:06:47.159838+00:00` on `0f34de9a2747059b7bb808cb070a86261e119f95`.
This is a read-only remediation plan; it grants no workflow dispatch, target/ledger write, promotion, production, or live authority.

## P0

### M001 — Complete P0-5 legacy risk-outcome parent acceptance

- Current state: Normal daily operating runs fail closed before market snapshot, target, and ledger processing.
- Required change: Use the separate P0-5 procedure to verify and accept exactly one quarantined legacy outcome parent with explicit one-time owner authorization.
- Acceptance evidence: Verified immutable accepted-head manifest, exact parent/child continuity, one successful scheduled continuation, and no target/ledger/live mutation outside the authorized paper transaction.
- Safety boundary: No automatic dispatch, no genesis bootstrap by inference, no live trading, and no use of folder-name trust.
- Depends on: P0-4 inventory, owner authorization, unexpired exact source artifact evidence

### M002 — Remove expiring-artifact dependence from accepted recovery evidence

- Current state: Catch-up verifies a pinned GitHub artifact digest; GitHub artifacts expire even though derived Drive evidence exists.
- Required change: Publish the exact artifact bytes or a complete content-addressed extraction into immutable durable storage, preserving GitHub run/artifact IDs and API/ZIP digest.
- Acceptance evidence: Offline verifier reconstructs the approved price-only evidence from the durable immutable bundle after GitHub artifact expiry.
- Safety boundary: Price replay only; never inherit target, ledger, promotion, production, or broker authority from a failed source run.
- Depends on: M001

## P1

### M003 — Create immutable run bundle for the divergent scored universe

- Current state: latest_global_alpha_universe differs from its nearest dated run in scored_latest.csv.
- Required change: Assign the exact latest tree a new immutable run/session directory and manifest containing code/config/data/universe/source hashes.
- Acceptance evidence: The latest alias resolves byte-for-byte to one immutable tree and the validator rejects any one-file divergence.
- Safety boundary: No fullrun, strategy change, or target publication is implied.
- Depends on: none

### M004 — Establish PIT universe and identity history

- Current state: Historical membership is a proxy and only March/April 2026 monthly snapshots were observed.
- Required change: Archive licensed or documented membership snapshots with available_from, effective dates, delistings, ticker/CUSIP changes, and universe hashes.
- Acceptance evidence: Representative backtest dates resolve to exactly one hash-bound membership snapshot without current-membership fallback.
- Safety boundary: Do not claim official Russell membership where the source license or history is unavailable.
- Depends on: none

### M005 — Consolidate macro writer authority and enforce current-session freshness

- Current state: Three workflows can overwrite same-date/latest macro files, and crisis availability compares a feature date to itself.
- Required change: Designate one macro writer, use atomic content-addressed daily manifests, record component available_from/provider hashes, and compare maximum age against the actual decision session.
- Acceptance evidence: Stale long-crisis features deterministically yield DEGRADED_DATA; same-date second writes are rejected or create a new immutable revision.
- Safety boundary: The crisis monitor remains advisory and cannot place trades or mutate official targets.
- Depends on: none

### M006 — Separate proxy price readiness from exact selector coverage

- Current state: The free manifest reports 80 refreshed tickers, required_ticker_count=0, and exact_operating_universe=false.
- Required change: Bind price coverage to the exact candidate/target ticker identity set and require per-ticker through-date, provider, adjustment, and content hashes.
- Acceptance evidence: Coverage ratio is bounded 0..1 over exact ticker identities, required_ticker_count is positive, and no stale ticker can pass.
- Safety boundary: Proxy replay may remain available but cannot satisfy the official daily selection freshness gate.
- Depends on: M003, M004

### M007 — Version model and feature bundles

- Current state: Models and features are latest-only April/June objects with missing lineage and non-strict JSON metadata.
- Required change: Create immutable training bundles with finite strict JSON, code/config/data/universe hashes, feature schema, evaluation windows, and rollback pointer.
- Acceptance evidence: A clean environment reproduces scoring from one manifest and rejects NaN/Infinity or an unbound latest alias.
- Safety boundary: No automatic champion promotion; research-only until a separate approval gate accepts the bundle.
- Depends on: M004

### M008 — Replace retiring shared rclone client configuration

- Current state: GitHub logs warn the shared Google Drive client ID will stop working during 2026.
- Required change: Provision a dedicated Google Drive OAuth client/service configuration through approved secret management and test bounded read-only enumeration first.
- Acceptance evidence: Restore and persistence preflights pass without the retirement warning; credentials remain absent from artifacts and logs.
- Safety boundary: Secret values are never committed, printed, or included in the inventory.
- Depends on: none

## P2

### M009 — Move large historical results behind immutable manifests

- Current state: Git tracks 6.8GB of full-rebuild history and duplicate latest copies.
- Required change: After a separately approved migration, retain compact manifests and durable content-addressed artifacts instead of repeated large Git blobs.
- Acceptance evidence: Fresh clone and CI checkout sizes fall materially while every approved run remains reproducible by manifest.
- Safety boundary: No Git history rewrite, deletion, or large-file move is authorized by P0-4.
- Depends on: M003

### M010 — Reconcile SEC shards and duplicate Drive namespaces

- Current state: Shard folder numbering and merge source counts are not explicitly reconciled; stale same-name roots exist.
- Required change: Publish a signed shard index with expected IDs/content hashes and a canonical parent-ID registry; quarantine duplicates by evidence, not name.
- Acceptance evidence: All expected shards are present or explicitly superseded, merge inputs hash exactly, and canonical paths resolve by parent IDs.
- Safety boundary: No Drive rename, move, or deletion without a separate cleanup approval.
- Depends on: none
