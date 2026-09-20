# [PROJECT_HANDOFF] Telegram insidertracking -> A2 discovery bridge

Date: 2026-09-21 KST. Repository: `wscha231/r1000-quant-engine`.
Implementation base: master `0140c81eab1ad7ec94eadaef2e03a22892419a7d`.
Scope: H1 research-source continuity and A2 discovery input only.

## Problem

The ChatGPT hourly watcher was enabled, but its prompt-local `[CHECKPOINT]` is not
a durable self-updating state store. A successful run can therefore inspect new
posts without advancing a reusable checkpoint for the next run. The repository
also had Telegram outbound alert utilities but no canonical `@insidertracking`
inbound source path on current master.

## Implementation

`research/telegram_event_v1/ingest.py` and `tools/run_telegram_event_ingest.py`
provide a standard-library-only public Telegram reader for
`https://t.me/s/insidertracking`.

- The first durable seed is post `64207`, matching the last independently
  recorded watcher checkpoint before this change.
- The collector pages backward with Telegram's public `before=` view until the
  fetched archive crosses the durable checkpoint boundary. Normal runs are
  bounded to 10 pages; a no-pointer first/recovery run is bounded to 50 pages.
- Telegram numeric message IDs are not required to be contiguous. Deleted or
  non-public messages can create legitimate holes. The collector therefore
  fails closed only when bounded pagination cannot cross the prior checkpoint
  boundary, not merely because an integer ID is absent.
- Every normalized event preserves post ID, source URL, Telegram publish time,
  actual collection time, text SHA-256, deterministic relevance categories and
  detected ticker-like symbols. `available_from` is the collection time, not a
  backdated Telegram timestamp.
- Each successful run writes only that run's new event delta to `events.ndjson`.
  It never recopies the full historical log. The checkpoint carries a rolling
  `event_chain_sha256` that extends only when a new delta is committed. An
  unchanged run preserves the same event-chain hash; a gap-blocked run also
  preserves the prior chain and cannot become the latest state.
- The source URL/channel, checkpoint schema, event-chain hash, delta hash and
  causal last-post bounds are validated fail-closed. Future Telegram timestamps,
  malformed state, conflicting duplicate posts and oversized pages are rejected.

`.github/workflows/telegram_insidertracking_research.yml` is the single source
collector. It runs hourly at minute 17 after merge, runs once on the merge push,
and also supports a bounded manual capture on an exact master SHA. It uses the
existing `RCLONE_CONFIG_GDRIVE` secret and pinned rclone 1.75.0 binary/hash already
used by project research paths.

Durable Drive root:

`gdrive:research/telegram_insidertracking/v1`

Each run first writes immutable evidence under
`runs/<github_run_id>-<attempt>/`, downloads it again and verifies exact SHA-256.
Only after that readback passes is one `latest.json` pointer advanced. The pointer
binds the exact GitHub run/attempt, source/channel, head SHA and SHA-256 of all
four immutable run files:

- `checkpoint.json`
- `events.ndjson` — this run's delta only
- `a2_discovery_inputs.json`
- `receipt.json`

Restore follows `latest.json` back to that immutable run, verifies all four file
hashes, then validates the run bundle logically: checkpoint/delta bounds, receipt
hashes, rolling event-chain identity and A2 zero-authority rules. This avoids both
partial multi-file latest updates and O(history^2) storage growth.

If no pointer exists, the collector performs a bounded rebuild from seed `64207`
and publishes a pointer only if the public archive interval closes. A missing or
corrupt pointer target, Drive/auth/transport failure, hash mismatch, malformed
prior bundle or unresolved source interval fails closed.

A blocked run may preserve immutable diagnostic evidence, but it never advances
`latest.json`. The workflow has fixed single-writer concurrency. It writes no
target, ledger, broker, champion, selector, current portfolio or repository
content.

## A2 trust boundary

Telegram is an unverified secondary discovery source. It is not an economic fact
database. Every emitted A2 row therefore has:

- `verification_status=UNVERIFIED_TELEGRAM_ONLY`
- `score_contribution=0`
- `discovery_only=true`
- `requires_independent_verification=true`
- `a3_er_eligible=false`
- `selector_eligible=false`
- `target_authority=false`
- `order_authority=false`

Telegram can surface a new company, theme, geopolitical shock, commodity event
or counter-thesis for A2 review, but it cannot itself change ranking, expected
return or a portfolio. Primary/authoritative corroboration is a separate causal
input. A later corroboration layer may promote a claim to reviewed evidence, but
that promotion must not be inferred from a Telegram source label.

## Relationship to existing work

- Reuses merged Control Plane v2 A2 `discovery_inputs`; it does not create another
  agent or peer-dispatch path.
- Does not import/cherry-pick open PR #459. That PR remains a broader SEC/news
  source-capture stack and was inspected only to avoid duplicating its durable
  source principles.
- Does not change merged Theme/ETF scoring. The bridge can later be consumed by
  A2 alongside Theme/ETF and Multi-Asset discovery after an explicit input-bundle
  connection.
- No historical PIT backfill before the known watcher seed is claimed. Any older
  archive import requires a separately bounded rights/completeness review.

## Validation

Local isolated source validation before publication:

- `python tests/telegram_event_ingest_smoke.py`: 18/18 PASS
- `python -O tests/telegram_event_ingest_smoke.py`: 18/18 PASS
- Python compilation: PASS
- Workflow YAML parse: PASS

Regressions cover HTML identity/time/text parsing, void HTML tags, A2 zero-score
authority, multi-page archive-boundary recovery with legitimate ID holes,
unresolved interval blocking, delta-only successive runs, unchanged-run chain
stability, malformed checkpoint/schema/source/chain rejection, future timestamps,
latest-pointer binding/tamper/path validation, and logical immutable-run bundle
verification including delta tamper detection.

A local native clone was attempted but the execution environment could not
resolve `github.com`. Publication therefore uses the repository's established
Git-data-object fallback onto a review branch while preserving current master as
base. This does not bypass CI/review/merge gates.

## Stop conditions / next action

Stop on unavailable Drive credentials, Telegram HTML contract failure, unresolved
bounded source interval, immutable readback/hash failure, malformed prior bundle,
non-green CI or missing exact-head review.

After merge, the new master `push` event performs the first bounded capture; the
hourly schedule then continues from `latest.json`. Confirm that first master run,
its immutable receipt, pointer readback and compact GitHub health artifact before
declaring durable collection operational. The separate ChatGPT watcher remains a
semantic cross-verification/user-alert layer, not the continuity ledger or score
writer.
