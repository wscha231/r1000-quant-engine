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
- The collector pages backward with Telegram's public `before=` view until it
  reaches the durable checkpoint. It is bounded to ten pages per run.
- If the oldest fetched post is still newer than `checkpoint + 1`, the run is
  `BLOCKED_GAP_UNRESOLVED`: checkpoint and event log are not advanced.
- Every normalized event preserves post ID, source URL, Telegram publish time,
  actual collection time, text SHA-256, deterministic relevance categories and
  detected ticker-like symbols. `available_from` is the collection time, not a
  backdated Telegram timestamp.
- The append-only event log and checkpoint are hash-linked. A checkpoint/event
  log hash mismatch, malformed state, duplicate/conflicting post, oversized
  page, invalid channel identity or source interval gap fails closed.

`.github/workflows/telegram_insidertracking_research.yml` is the single source
collector. It runs hourly at minute 17 after merge and also supports a bounded
manual capture on an exact reviewed master SHA. It uses the existing
`RCLONE_CONFIG_GDRIVE` secret and pinned rclone 1.75.0 binary/hash already used
by the project's research paths.

Durable Drive path:

`gdrive:research/telegram_insidertracking/v1`

Each run first writes immutable evidence under
`runs/<github_run_id>-<attempt>/`, downloads it again and verifies exact SHA-256.
Only after that readback passes are these four `latest/` members advanced:

- `checkpoint.json`
- `events.ndjson`
- `a2_discovery_inputs.json`
- `receipt.json`

A gap-blocked run preserves its diagnostic immutable receipt but never advances
`latest`. The workflow has fixed single-writer concurrency. It writes no target,
ledger, broker, champion, selector, current portfolio or repository content.

## A2 trust boundary

Telegram is an unverified secondary discovery source. It is not an economic
fact database. Every emitted A2 row therefore has:

- `verification_status=UNVERIFIED_TELEGRAM_ONLY`
- `score_contribution=0`
- `discovery_only=true`
- `requires_independent_verification=true`
- `a3_er_eligible=false`
- `selector_eligible=false`
- `target_authority=false`
- `order_authority=false`

This deliberately satisfies the fail-closed rule: Telegram can surface a new
company, theme, geopolitical shock, commodity event or counter-thesis for A2
review, but it cannot itself change ranking, expected return or a portfolio.
Primary/authoritative corroboration is a separate reviewer input. A later
corroboration layer may promote a claim to reviewed evidence, but that is a
separate causal change and must not be inferred from a Telegram source label.

## Relationship to existing work

- Reuses the merged Control Plane v2 A2 `discovery_inputs` role; it does not
  create another agent or peer-dispatch path.
- Does not import stale/unmerged PR #459. That PR remains a broader SEC/news
  source-capture stack and was inspected only to avoid duplicating its durable
  source principles.
- Does not change merged Theme/ETF scoring. The bridge can later be consumed by
  A2 alongside Theme/ETF and Multi-Asset discovery after an explicit input
  bundle connection.
- No historical PIT backfill is claimed. The first seed protects continuity
  from the known watcher point forward; any older history needs a separately
  bounded archive import with rights and completeness review.

## Validation

Local isolated source validation before publication:

- `python tests/telegram_event_ingest_smoke.py`: 10/10 PASS
- `python -O tests/telegram_event_ingest_smoke.py`: 10/10 PASS

Regressions cover HTML identity/time/text parsing, HTML void elements, A2
zero-score authority boundary, multi-page gap recovery, unresolved-gap state
preservation, malformed checkpoint rejection, checkpoint/event-log hash mismatch,
event-log/checkpoint ordering, fixed approved-source URL enforcement, and rejection
of future Telegram timestamps.

A local native clone was attempted but the execution environment could not
resolve `github.com`. Publication therefore must use the repository's established
Git-data-object fallback onto a new review branch, preserving current master as
base. This is not a user worktree edit and does not bypass CI/review/merge gates.

## Stop conditions / next action

Stop if Drive credentials are unavailable, Telegram HTML no longer satisfies the
parser contract, the source interval cannot be closed, exact immutable readback
fails, CI is non-green, or exact-head review is missing.

After merge, run one exact-head manual capture before relying on the hourly
schedule. Confirm Drive latest checkpoint, immutable run receipt and a compact
GitHub health artifact. Then update the ChatGPT watcher to treat this durable
checkpoint as the continuity source and use its web access only for semantic
cross-verification and user alerts.
