# A2 → A0 → A1 read-only connection

`tools/run_a2_a1_readiness.py` reads the incumbent Main's existing
`control_plane/candidate_registry/filing_requests.json`, its immutable references,
an existing owner capture inventory and named checkpoints. No replacement
Registry, collector or scheduler is introduced. Main PR669 owns the existing
filing writer; this tool never imports or edits that writer or writes its store.

The lookup reports `STORED_RESEARCH_REQUEST`, `NOT_FOUND_IN_INSPECTED_STORE` or
`UNKNOWN`. Hash-bound local pending requests are not authenticated current
Registry admission. Price index matches and checkpoint completion claims are
separate observations: a completed ticker can have zero bars. Neither proves
per-session raw/split coverage, identity, licensing, PIT or `DATA_READY`.
Nonmatches apply only to the explicitly inspected store/index, never global
absence or an instruction to collect. V0 filings do not become V1/V2 events.

## Existing producer and A0 interface

1. The trusted caller supplies a bounded `subjects.json`:
   `{"subjects":[{"country":"US","ticker":"MU","security_id":null,"issuer_id":null}]}`.
   Null IDs stay unknown. Do not derive lifecycle/security identity from ticker.
2. Run the tool with `--subjects`, the explicit `--registry-root` (the existing
   agent-board output root), optional `--capture-inventory` and repeated
   `--checkpoint`, and a separate scratch `--output-dir`. Existing bytes are read
   with size/hash/path limits and copied into a content-addressed transport cache.
3. The producer may also supply `--ohlcv-inventory` containing Stage3's original
   events/context/catalog/calendar/policy and sealed references. Their original
   clocks/hashes and the complete existing validator remain required. Lookup
   presence does not fabricate a missing event, source graph, identity or right.
4. Refresh actual GitHub code/control/mission intake AFTER the lookup acquisition.
   Invoke the same tool with `--connect-lookup`, `--canonical-inputs`,
   `--evidence-root` and a distinct scratch `--output-dir`. It binds the derived
   A1 input into the existing materializer and public `run_agent_board` API.
   Existing other-agent requests are preserved; a pre-existing A1 request
   requires reconciliation and is never silently replaced. No source pin, saved
   state or G0 success is synthesized. Missing durable sources remain UNKNOWN.

Outputs are `source_inventory.json`, `request_fragment.json` and the read-only
lookup report; connect emits the existing `agent_task_queue.json` and board
manifest. These are proposed transport artifacts, not a second canonical ledger.
The complete lookup enters the existing A1 task identity so source/input changes
invalidate the task key and old completion. No event input means a BLOCKED A1
diagnostic packet (`READINESS_EVENT_INPUT_MISSING`), zero collection requests.
When a genuine Stage3 input exists, only that validator can propose reuse,
incremental or backfill. Every path remains DRY_RUN and dispatch-ineligible.

Refresh revokes current proposal/report files before reading input. Hash, clock,
subject, request or path conflicts fail closed; failed connects revoke the prior
queue and manifest. Original issuer/publication/price clocks are not advanced by
the new observation time. Old capture windows/budgets are never reused as grants.

## Actual observation and operational boundary

The Oct23 bounded observation uses MU/AAPL/RNG, the incumbent MU filing request
and existing A1 inventory/checkpoints. MU has a stored pending research request;
MU/AAPL match the existing price inventory; RNG is absent only in that inspected
scope. No company has newly authenticated canonical/PIT/consumer readiness.
This is a real lookup/blocked A0 route, not a positive three-company collection
E2E. Current ChatGPT news schedules remain untouched: their machine-readable
output delivery endpoint has not been supplied/verified. This command can consume
an existing structured producer export; it does not scrape chat notifications or
claim that a scheduler/exporter is enabled. KR store/source adapter remains open.

Next inputs are an actual structured V1/V2 event with authenticated identity,
current accepted Registry reference, raw-price/session evidence and named valid
Source scope. Exact-head CI/review, protected merge and any actual bounded
collection/activation gates remain distinct. No ER/BUY/portfolio/book mutation.
