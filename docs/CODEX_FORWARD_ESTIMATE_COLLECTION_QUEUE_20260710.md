# Forward Estimate Collection Queue Contract - 2026-07-10

## Purpose

`tools/build_forward_estimate_incremental_universe.py` prepares the bounded
vendor request for the forward-only earnings-estimate archive. It does not call
an API. The queue is research-only, cannot backfill the historical run287
window, treats missing vendor coverage as neutral, and cannot activate
production or live trading.

The authoritative seed is either an exact 993-row current coverage CSV or the
exact 993-row union rebuilt from the tracked latest-run `scored_latest` and
report books. The current contract contains 992 vendor-eligible equity tickers
plus one `CASH` or `__CASH__` placeholder. The placeholder remains in every
audit/checkpoint row but is never emitted to a vendor request. This is a
forward-only current-universe proxy with `pit_universe_label_clean=false`, not
historical Russell 1000 membership.

## Resume and fail-closed behavior

On a valid seed, the builder writes these files beside the durable archive:

- `data_pit/events/earnings_estimates/collection_universe.csv`
- `data_pit/events/earnings_estimates/collection_checkpoint.json`

The workflow cache and Google Drive sync already persist that directory. Later
runs may resume from the canonical file only when it still contains exactly
993 unique accepted rows, exactly 992 vendor-eligible equities and one cash
placeholder, and its SHA-256 matches a checkpoint carrying the same contract.
The older
858-ticker plan or 863-ticker catch-up result is retry-priority input only; it
is never accepted as full-universe identity. If neither an exact seed nor a
valid checkpointed canonical snapshot exists, the builder returns
`blocked_incomplete_universe` before the vendor collector step.

On first deployment, `earnings_estimates_daily.yml` can seed from the tracked
latest-run union when the optional coverage CSV is not restored. It records
all four source-file hashes in the checkpoint. Subsequent runs prefer any
newer exact coverage CSV or tracked latest-run union; otherwise they resume
only from a hash-valid canonical/checkpoint pair.

Fresh rows with `has_forward_estimate=1` are reused. A request CSV contains only
bounded members of these lanes:

- `new_universe`
- `missing`
- `stale_success_due`
- `uncovered_retry_waiting` through the slow rotating retry budget

Each lane limit is non-negative. Zero disables that lane; negative values are
rejected rather than being interpreted as an unbounded request.

The planner records the proposed batch without advancing its durable rotation
counter. The collector acknowledges only tickers it actually reaches; only
those rows receive a new selected timestamp/count. A missing key, runner
failure, or max-error break therefore leaves the unattempted tail at the front
of the next restored queue instead of falsely marking it serviced.

## Output schema

`outputs/earnings_estimates_daily/incremental_universe.csv` is the ticker-only
collector input. An empty file means no collection is due and the collector
step is skipped.

`outputs/earnings_estimates_daily/collection_queue.csv` has one row for each of
the 993 canonical rows. Important fields are:

| Field | Meaning |
|---|---|
| `ticker` | Canonical current-universe identifier. |
| `queue_state` | Fresh reuse, missing, stale, new, uncovered retry, or non-equity placeholder. |
| `queue_action` | `collect`, `reuse`, `wait`, or `exclude`. |
| `eligible_for_vendor_request` | False for the retained cash placeholder. |
| `latest_observed_date` | Latest archived attempt date. |
| `latest_success_date` | Latest archived row with a usable forward estimate. |
| `last_selected_at_utc` | Durable retry-order checkpoint, advanced only after collector attempt acknowledgement. |
| `selection_count` | Number of acknowledged collector attempts retained across runs. |
| `canonical_universe_sha256` | Identity of the exact universe used for this row. |

`collection_checkpoint.json` contains the canonical source provenance,
available/ingested timestamps, canonical hash, snapshot-file hashes, queue
counts, and all per-ticker state rows.

`incremental_universe_summary.json` and `collection_queue_report.md` provide
the auditable run summary. They report total/eligible/placeholder counts,
source and snapshot aggregate hashes, source modification and ingestion times,
fresh successful rows reused, selection counts by reason, and all safety flags.
The archive manifest records hashes for the queue summary, checkpoint, CSV, and
report alongside the estimate snapshot hashes.
