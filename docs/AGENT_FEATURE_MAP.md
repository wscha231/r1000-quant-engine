# A0 Control Room feature map (AF01 / AF02)

Status: event-driven **foundation**, `RESEARCH_ONLY`. The canonical entrypoint is
`tools/run_agent_board.py`; `research/control_plane/agent_contracts_v2.yaml`
keeps `specialist_dispatch_enabled=false`. A task packet is a proposal, not an
execution or an investment decision. No new scheduler, autonomous specialist,
notification sender, receipt store, or merge authority is introduced.

## Canonical roles

| Agent | Role and entrypoint | Authoritative inputs → outputs | Trigger and reuse identity | Tests / verification | Mutation authority, shortcuts forbidden, escalation |
| --- | --- | --- | --- | --- | --- |
| A0 | State, dependencies, gates; `tools/run_agent_board.py` | Current `system_state-v2`, contracts, verified local artifacts → `agent_task_queue.json`, `board_summary.json`, manifest | An operator or trusted GitHub event consumer supplies current evidence; reuse only for the exact source/input/dependency/config/model/parameter/code identity | `python tests/control_plane_agent_contract_smoke.py`; `python tools/run_agent_board.py --latest-run <verified-run> --output-dir <scratch>` | Proposal outputs only. Never trust worker self-report or dispatch peers; escalate invalid provenance, governance/economic mutation, or review conflict. |
| A1 | Data/PIT; board's A1 packet; reuse `r1000_legacy_input_guard.py` | Verified `source_inventory` → `data_pit` | New available source or invalidation; same exact task key and V2 receipt may skip | Control Plane smoke, input integrity guards; board command above | Read/validate proposal only. Never fill missing with zero or backdate PIT; escalate stale/conflicting/source hash evidence. |
| A2 | Leadership/Event/Discovery; board's A2 packet; reuse `tools/theme_etf_source_bridge.py`, `tools/run_multi_asset_leadership.py` | A1 `data_pit`, `discovery_inputs` → `leadership_events` | New verified discovery or A1 output; same exact identity/receipt may skip | Control Plane smoke and existing leadership smokes; board command | Proposal only, no BUY/SELL. Never elevate RS/theme presence to order authority; escalate failed G0 or dependency/QA mismatch. |
| A3 | ER/Thesis; board's A3 packet; reuse `research/multi_asset_v1/decisions.py` | A1 `data_pit`, A2 `leadership_events`, `thesis_inputs` → `expected_return` | Reviewed thesis/ER input change; same exact identity/receipt may skip | Control Plane smoke and ER contract checks; board command | Proposal only, no weight authority. Never invent missing horizon or validated alpha; escalate unsupported ER or economic logic change. |
| A4 | Macro/Regime; board's A4 packet; reuse `r1000_regime_data.py` | A1 `data_pit`, `macro_inputs` → `regime` | New available macro evidence or A1 output; same exact identity/receipt may skip | Control Plane smoke and regime data checks; board command | Proposal/read only. Never turn regime into automatic liquidation; escalate stale series or conflicting timestamps. |
| A5 | Portfolio; board's A5 packet; reuse `research/multi_asset_v1/decisions.py` | A3 ER, A4 regime, A6 QA, verified `portfolio_context` → `target_proposal` | Verified dependencies and book context change; same exact identity/receipt may skip | Control Plane smoke, `portfolio_system_guard.yml`; board command | Proposal only. No Actual Broker, Paper Book or Target Book write; escalate any weight change, unknown book or risk limit change for human approval. |
| A6 | Independent QA; board's A6 packet; reuse `tools/run_pr_validation.py` | Hash-bound `review_bundle` → `qa_report` | New reviewed artifact bundle, including blocked upstream evidence; same exact identity/receipt may skip | Control Plane smoke, PR Validation Fast; board command | `READ_ONLY`. Never certify unreviewed bytes or approve its own work; escalate unresolved findings, changed head or hash mismatch. |
| A7 | Ops/Publishing; board's A7 packet; reuse `tools/run_run287_daily_research_monitor.py` | A6 QA, `publishing_inputs` → `publication_proposal` | Verified publication inputs and QA change; same exact identity/receipt may skip | Control Plane smoke, publishing/guard checks; board command | Proposal only. No investment judgment or accepted durable publication from a packet; escalate missing manifest or durable state mismatch. |
| A8 | Experiment/Learning; board's A8 packet; reuse `docs/run287_do_not_repeat_registry.json` | A1 data, matured outcomes, failed experiments, A6 QA → `challenger_proposal` | Matured evidence or experiment registry change; same exact identity/receipt may skip | Control Plane smoke and experiment governance checks; board command | Proposal only. Never auto-promote production or erase negative experiments; escalate new alpha logic for reviewed OOS and human approval. |

All A1–A8 requests originate with A0. A1/A2/A4/A6 can be marked
`dispatch_eligible` when their packet is READY and their mode is read/proposal.
Eligibility is a deterministic *future* candidate, not dispatch. A3/A5/A7/A8
remain ineligible. The global switch stays false.

## A0 decisions and worker handoff

The existing packet and receipt express **Task → Work → Evidence → Confidence →
Next Action**: A0 issues a task packet; a specialist/worker performs research,
code or tool work outside this board; the existing `completed_tasks` receipt
binds outputs, runtime checks, focused tests, CI and dependency hashes. Optional
`confidence` and `next_action` are worker metadata and proposals. Neither is
verification evidence or an authoritative transition. A0 decides the next
state from verified bytes and independently checked current-head GitHub facts;
DONE additionally requires an attested merge and post-merge verification.

| A0 decision | Existing state or action |
| --- | --- |
| ROUTE | Issue a READY proposal to an eligible specialist; dispatch remains disabled |
| SKIP | SKIP_UNCHANGED after identity and output verification |
| VERIFY | READY_FOR_ATTESTATION or POST_MERGE_VERIFY |
| RETRY | CORRECTION_REQUIRED after a bounded corrective change |
| ESCALATE | HUMAN_APPROVAL_REQUIRED |
| BLOCK | BLOCKED |
| WAIT | WAITING_CI or WAITING_REVIEW, with no AI polling |
| READY | READY_TO_MERGE only after the separate `review_complete` gate |

A0 does not implement a specialist's code or research task. A worker's success
report, high confidence, or proposed next action cannot produce DONE.

## AF02: one completed_tasks receipt, version 2

`system_state_schema.json` extends each existing `completed_tasks` row. A
successful reuse must bind `task_key`, full task identity, source and input
SHA-256 per role, dependency task keys and output hashes, code SHA, config hash,
model name/version (provider when applicable), parameter hash, output artifact
descriptors, runtime verification, focused tests, CI identity/head/result,
evidence availability, side effects, reviewed head when applicable,
created/available times, and verification status. The board recomputes identity and hashes, reads output
bytes, checks freshness and causal timestamps, and validates A6's reviewed
scope. Missing, conflicting, stale or tampered matching receipts become BLOCKED;
an absent receipt remains READY and cannot be called DONE. `SKIP_UNCHANGED`
requires all identity dimensions, evidence binding and valid output bytes.
Each runtime, focused-test and CI record retains its run/test `reference` and
head; its `identity` is the SHA-256 of the evidence kind, reference, task key,
complete packet identity (including inputs/dependencies), code head, and the
complete output descriptors by role (path, SHA-256, availability, collection,
expiry, observation and status), plus the evidence availability time. Every
evidence result must postdate output collection and predate receipt creation.
A copied reference or digest from another task/head fails verification. Receipt
declarations are **not authenticated GitHub checks** or merge permission; the
current head CI and review must be read independently from GitHub.

The board writes its existing manifest and queue. It does not write a second
receipt store. Old `completed_tasks` rows lacking V2 fields fail the schema;
they need fresh verification, not automatic migration or grandfathering.

The same receipt records `execution_mode`, `ai_invoked`, model/provider/version
when AI is used, and `ai_invocation_reason`. A deterministic or reused result
records `ai_invoked=false` and no AI reason; an AI mode requires a reason and
provider. These fields document cost provenance, not verification evidence.

## Autonomy risk tiers

Existing read/proposal mode and authority flags remain the packet's execution
boundary. A0 classifies the requested operation, never a worker's claimed tier:

| Tier | Meaning | Boundary |
| --- | --- | --- |
| T0_READ | Read-only inspection | Deterministic automation after input checks |
| T1_COMPUTE | Reproducible computation | Automation after hash/dependency checks |
| T2_PREPARE | Draft or proposal preparation | Verified preparation, no accepted write |
| T3_REVERSIBLE_WRITE | Reversible repository write | Existing CI, review and `review_complete` governance |
| T4_ECONOMIC_MUTATION | Fullrun, target/paper/broker or risk decision | HUMAN_APPROVAL_REQUIRED |
| T5_IRREVERSIBLE_OR_PROTECTED | Production/live activation, protected evidence/hash/review gate | HUMAN_APPROVAL_REQUIRED |

T0–T2 are eligible only when verification conditions pass and a future dispatch
switch is explicitly enabled; this PR leaves it false. Explicit protected
actions override any lower tier. An explicit action is safe only when it is
`read` (T0), `compute` (T1), `prepare` (T2), or `reversible_repo_write` (T3
with the matching declared effect); incompatible tier/action claims block.
Unrecognized actions and unknown side effects require human approval even
when a worker supplies a lower tier. An absent action means no operation was
requested by this GitHub state event.
These tiers do not authorize execution or mutation from a packet.

## A0 event reducer and boundaries

`lifecycle_state(packet, event)` is a deterministic reducer in the existing
board module. An event consumer must obtain CI/check conclusions, review threads,
review head, `review_complete`, and merge evidence from GitHub at the *current*
head before passing them in. A worker report is ignored. The board does not
query GitHub, poll, send notifications, invoke an LLM, or publish a decision.
Existing `pull_request`, `workflow_run`, `issue_comment`, and `push`/merge
events are appropriate wake-ups for a future read-only consumer. The present PR
does not add an event workflow or automatic specialist dispatch.

States: `QUEUED`, `READY`, `RUNNING`, `WAITING_CI`, `WAITING_REVIEW`,
`CORRECTION_REQUIRED`, `READY_FOR_ATTESTATION`, `READY_TO_MERGE`,
`POST_MERGE_VERIFY`, `DONE`, `BLOCKED`, `HUMAN_APPROVAL_REQUIRED`,
`SKIP_UNCHANGED`. Current-head `validate` and `portfolio_guard` green,
zero unresolved findings, clean current-head review and verified receipt are
needed for attestation readiness. `review_complete` at the current head is an
additional requirement for READY_TO_MERGE. Neither state bypasses the existing
repository governance gate or authorizes this PR's merge.

The state may name `review_pr_number`; packets then carry the repository/PR
scope independently of the event. The trusted GitHub event consumer must bind
review facts, a current authenticated GitHub ruleset observation and
`review_complete` to that exact scope. Without it, no review-based readiness
transition is available. Supply the complete current required-check set with
context and integration ID, ruleset identity and observation time, PR head and
current base SHA. The strict-policy base must be verified in PR ancestry, and
every required check from that observation must pass on the exact head under
the required app identity; `review_complete` is evaluated separately after review.
The pure reducer cannot authenticate GitHub itself: the trusted caller must fetch
the live ruleset and base together, not accept a worker-provided subset or old observation.

After merge, the trusted event consumer must supply `merged=true`, the actual
`merge_sha`, its observed `default_branch_head`, and `merged_pr_head` from the
PR. The structured `post_merge_verified` record needs `status=PASS`, a nonempty
verification `identity`, a matching `pr_head_sha`, `merge_sha`, and
`default_branch_head`. DONE requires the PR head to equal the packet code SHA,
the merge observation and post-merge PASS to match the packet repository/PR
scope, and all four merge/default SHA values to be the same valid current merge SHA.
A boolean, string, old merge, or failed check stays at POST_MERGE_VERIFY. The reducer does not
fetch GitHub; the caller must authenticate these observations at evaluation
time rather than accepting a worker's event claims.

Fullrun, actual broker, paper/target book, production/live activation, new
alpha economic logic, ER weight changes, risk limit or review gate relaxation,
and protected evidence/hash changes stop at `HUMAN_APPROVAL_REQUIRED`.
Only BLOCKED, HUMAN_APPROVAL_REQUIRED, CORRECTION_REQUIRED, READY_TO_MERGE,
DONE, data integrity failure or unexpected regression are notification-worthy.
WAITING_CI, WAITING_REVIEW and SKIP_UNCHANGED never request polling or a user
notification. The reducer returns flags; no delivery mechanism is activated.

The reducer returns `ai_invocation_required=false` for every deterministic
state evaluation, including CI waits, SHA/dependency/hash checks and unchanged
identity. This is a no-dispatch contract.

Usage priority: DETERMINISTIC_CODE → VERIFIED_EXISTING_ARTIFACT →
SKIP_UNCHANGED → GENERAL_CHATGPT → manual WORK for multi-file code,
complex incidents or large research/backtests → one final exact-head CODEX
review only when repository policy requires it. CI waiting, SHA comparison,
receipt verification and status checks use deterministic code.
