# Run287 P0-4 artifact inventory

This is the read-only inventory required by Issue #372, frozen at `2026-08-25T12:06:47.159838+00:00` and bound to `master` `0f34de9a2747059b7bb808cb070a86261e119f95`.

## Outcome

- Dataset classes: `15`
- Model objects: `4`
- Durable-state objects: `8`
- Infrastructure/artifact objects: `19`
- Total normalized Parquet rows: `46`
- Latest aliases verified: `6`
- Latest aliases blocked: `30`

## Current pipeline connection

```text
SEC / earnings / free prices / macro collectors
                    |
                    v
       Drive caches + mutable manifests
                    |
                    v
         Data Readiness Preflight (green)
                    |
                    v
 Daily Operating Selection Refresh (BLOCKED)
                    |
       missing verified risk-outcome parent
                    X
  market snapshot -> target -> paper ledger -> accepted head
```

The latest three operating runs `32801137546, 32545955145, 32440400556` all failed at the same step: `Restore verified risk-outcome accepted head`. Collection, readiness, SEC, smart-money, crisis-monitor, and autolearning jobs were green in the latest observed runs; green sidecars do not clear this state-lineage blocker.

## Highest-impact findings

- **P0 F001** — The official selection-to-paper pipeline is stopped: the latest three scheduled runs fail at the verified risk-outcome parent restore gate.
- **P0 F002** — P0-5 must establish the quarantined legacy risk-outcome parent before normal paper continuation; no automatic or inferred bootstrap is allowed.
- **P1 F003** — The main repository latest full-rebuild alias diverges from its nearest immutable run in scored_latest.csv, so approved-run reproduction is blocked.
- **P1 F004** — Historical R1000 membership is explicitly not PIT-safe and only two 2026 monthly snapshots were observed, creating survivorship risk in backtests and training.
- **P1 F005** — Macro snapshots have three same-path writers, while the crisis monitor has no current-session maximum-age check for long-crisis features.
- **P1 F006** — The free price manifest refreshes 80 tickers with required_ticker_count=0 and exact_operating_universe=false; it is proxy readiness, not selector readiness.
- **P1 F007** — Drive model and feature objects are stale latest-only aliases without immutable training lineage; the scoring metadata is non-strict JSON because it contains NaN.
- **P1 F008** — Drive price-cache enumeration is incomplete (100 returned versus 1048 reported), so duplicate/orphan and full hash claims fail closed.
- **P1 F009** — Every Drive restore/persist path depends on an rclone shared Google Drive client ID that runtime logs warn is being retired during 2026.
- **P2 F010** — Git tracks 6.8GB of full-rebuild artifacts across 10,460 blobs, increasing checkout, clone, review, and CI latency.
- **P2 F011** — A stale Drive source mirror and repeated same-name folders can be mistaken for canonical storage unless folder IDs and parent paths are enforced.
- **P2 F012** — Form 4 storage exposes 36 of 40 numbered shard folders while the completed merge manifest reports 38 source files; the difference needs a signed reconciliation manifest.

## Files

- `dataset_registry.yaml`: data and feature classes, producer/consumer/PIT/hash contracts
- `model_registry.yaml`: model binaries and metadata, including immutable-binding blockers
- `artifact_registry.parquet`: normalized row for every registered object
- `durable_state_registry.yaml`: accepted paper state, ledgers, state chains, and recovery procedures
- `latest_to_immutable_map.yaml`: every discovered mutable alias is either verified or blocked
- `migration_map.md`: ordered remediation without any mutation authority
- `source_inventory_snapshot.json`: frozen GitHub/Drive/local evidence used for deterministic regeneration

## Fail-closed limits

- Google Drive folder listing returned only 100 direct cache_price children while the frozen manifest reports 1048 files; the provider view has no continuation token and remains incomplete.
- Google Drive metadata did not expose provider checksums for most large binaries; blank hashes are not verified hashes.
- GitHub workflow health is a bounded latest-run snapshot, not a complete historical artifact census.
- The local H:/r1000-quant-engine worktree is dirty and user-owned; it was observed read-only and is not canonical evidence.
- Same-name Drive folders outside the canonical root were not treated as canonical by name alone.
- No secret, token, service-account, broker-account, or personally identifying value was collected. Presence classifications only are recorded.
- No Drive upload/move/delete, local cleanup, workflow dispatch, fullrun, target/order/ledger mutation, champion change, production enablement, or live trading occurred.
- A blank hash means it was not available from the bounded provider view; it is never interpreted as verified.

## Rebuild

```bash
python -m venv .venv-p0-4
.venv-p0-4/bin/python -m pip install --requirement docs/run287_p0_4_artifact_inventory/requirements.txt
.venv-p0-4/bin/python tools/build_p0_4_artifact_inventory.py --verify-live-head
.venv-p0-4/bin/python tests/test_p0_4_artifact_inventory.py
```

On Windows PowerShell, use `.\.venv-p0-4\Scripts\python.exe` in place of `.venv-p0-4/bin/python`. The exact dependency pins are part of the frozen bundle.
The protected-publication constant is verifier code: advancing it requires an explicit verifier diff and a new external exact-head Codex review plus the repository review-complete gate; regeneration alone grants no trust.
