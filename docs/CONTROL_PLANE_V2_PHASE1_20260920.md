# [PROJECT_HANDOFF] Control Plane v2 — Phase 1

## 2026-11-09 - A5 model preparation and account prerequisites (#537)

The existing A5 request accepts `parameters.portfolio_mode`: omitted means
`ACCOUNT_REBALANCE`; explicit values are `ACCOUNT_REBALANCE` and
`MODEL_PORTFOLIO`. Unknown, null and non-string values fail closed. The task's
authority remains `PROPOSAL_ONLY`; A5 dispatch is always false.

MODEL uses the existing `portfolio_context` role and the strict
`a5-portfolio-context-v1` definition in `system_state_schema.json`. It binds one
completed NYSE session/cutoff, the complete requested security roster, original
A3 packet/result references, a bounded private artifact inventory and an explicit
GENESIS. Existing model incumbents remain blocked until their domain verifier is
bound; actual broker holdings cannot substitute for model state.

Preparation replays the incumbent Candidate Registry, requires an unexpired A3
reference and linked original ER for every requested candidate, and compares the
rebuilt index with A3's exact `expected_return` output. The original A4 request
and native inputs are consumed by `market_analysis_engine.load_report`; its
current READY report must equal A4's exact `regime` output. Existing A3/A4/A6
completion receipts and independent QA must cover the role inputs plus all
original inventory members. A batch/performance receipt is not native risk-input
readiness. A3 files keep4MiB each/32MiB total; only exact path/hash/kind matches in
the pinned A4 request use the existing engine's kind-specific and64MiB aggregate
limits. These separate bounds can total96MiB; hash verification and replay may
read original files more than once. Provider/wire I/O is not measured by those
limits. The256-entry inventory is not entire820-security readiness evidence.

Only exact materializer-backed account-source reasons are scoped out of MODEL
and its A2/A3/A4 research dependencies. Missing prior model data is optional only
for an explicitly bound GENESIS. Unknown reasons, data/PIT/G0/freshness failures,
candidate/reference failures and independent QA remain blocking. Canonical
source/book statuses are retained; global thesis or model-allowed flags are not
candidate evidence. ACCOUNT keeps its existing prerequisites and default path.

`READY` means A0 task preparation only. Derived `parameters.a5_preparation` keeps
`economic_input_admission=BLOCKED`, current-A3-review admission false and all
dispatch/write/account authority false. The Registry's current-selection,
independent-domain/economic blockers and runtime
`CURRENT_A3_REVIEW_ADMISSION_REQUIRED` are unchanged. This slice does not compute
weights, run a model/backtest, initialize a book or complete #499/#526/#537's
remaining domain connection.

Date: 2026-09-20 UTC. Repository: wscha231/r1000-quant-engine.
Audited master: `3f8986dbad6d590ae97e7276e01f59766e91d8b0`.
Branch: `codex/control-plane-v2-phase1-20260920`.

## Verified starting state and decision

AGENTS.md, the operating standard, shared lessons, CURRENT_STATUS and issue465's
latest PROJECT_HANDOFF were inspected against live GitHub. The existing clean
worktree matched master; no new worktree was created. Input-integrity #463,
Theme bridge #464 and Multi-Asset #466/#467 are already merged. Do not repeat them.
CURRENT_STATUS's operating snapshot remains 2026-08-23; its September source
note does not refresh its book/data/performance evidence.

Open #451 is a separate cross-chat candidate-packet/registry proposal, not a
merged dependency. Its source and old snapshots were inspected, not cherry-picked.
Open #460/#461 implement metric/precheck and compute work; this change neither
imports their stack nor installs another compute scheduler/cache engine. #446's
review-gate change is unmerged. Current exact-head Codex review remains required.

## Actual implementation

- `research/control_plane/agent_contracts_v2.yaml`: A0–A8 role, input/output,
  dependency and authority contracts. JSON-compatible YAML, strict parsing.
- `research/control_plane/task_packet_schema.json`: non-executable task proposals
  routed from/to A0; explicit identity, dependency evidence and blocked reasons.
- `research/control_plane/system_state_schema.json`: explicit operator snapshot,
  time/code/context, input references, model/parameters and completion receipts.
- `tools/run_agent_board.py`: replace obsolete May A0/A2/A3/A4/A5/A6/A7/A10
  assignments/baselines with v2 planning. Reuse existing command, output names,
  artifact-only control boundary and manual workflow entrypoint.
- `tests/control_plane_agent_contract_smoke.py` and existing
  `tests/agent_board_smoke.py`: new boundaries run through the already registered
  Tier-1 entrypoint. Frozen runner and workflow files are unchanged.
- `requirements_github.txt`: JSON Schema validator for the checked-in schemas.
- `tools/package_research_handoff.py` and its existing smoke: restore instructions
  explicitly require a fresh v2 state and its referenced artifacts before the board command.
- Shared lessons and this handoff record the causal change and remaining boundary.

Mission: Main net CAGR >=35%, MDD loss <=25%; Concentrated >=50%, <=25%.
The existing config operating gate is separately read as Main CAGR .30/max_dd
-.25 and Concentrated .50/-.28. No investment config or calculation is edited.
These are goals/gates, not accepted performance. May hard-coded baselines are
not a current promotion authority and no longer appear in generated packets.

## Input/output and invocation

The unchanged CLI accepts `--latest-run DIR --output-dir OUT --run-url URL`.
Add `--system-state FILE` or place the schema-conforming state at
`DIR/control_plane/system_state.json`. Input and completion artifact paths are
relative to DIR; traversal and symlink escapes are rejected. The schema and
synthetic smoke fixture are the executable examples; no fabricated live snapshot
is committed.

Only explicitly requested specialists are planned. Each request must name the
exact input roles from its contract. All dependent tasks need matching successful
completion receipts with actual output bytes; a queued task is not completion.
Every dependent input role must match its upstream output reference, hash and
metadata. A valid upstream receipt cannot authorize unrelated downstream bytes.
A completion output must become available no earlier than collection of every
causal input/dependency result; pre-input output receipts cannot be reused.
A1 and A6 can diagnose G0 failures. A6 is read-only and has no prerequisite-success
requirement, so it can inspect failed work independently. Every result returns to
A0; peers cannot dispatch. Phase 1 invokes no specialist/model/workflow/API. Missing data_as_of permits only
A1/A6 diagnostic work. A6 bundles and reports carry exact reviewed artifact
identities; PASS QA can support A5/A7/A8 only when all their non-QA inputs are
covered. FAIL or unrelated QA remains diagnostic and blocks downstream proposals.

A task key binds agent + input hashes/metadata, dependency output receipts,
context/G0/master identity, code SHA, actual control/config bytes plus dirty tracked
and untracked source bytes, model name and
version, and parameters. Same identity plus valid successful result bytes yields
SKIP_UNCHANGED. Changed context/code/config/model/parameters/input/dependency
invalidates reuse. Missing, stale, future or changed result bytes block reuse.
This is local exact-result reuse for proposals, not an authenticated economic
result, investment approval or independent review of a self-declared receipt.

Missing state is BLOCKED/exit2, including the old workflow's historical metrics
folder default. No new scheduler or workflow input is added in this phase. Supply
a v2 state before expecting useful task proposals. Final `manifest.json` lists
only current output members and hashes. It is revoked before input reads; failures
cannot leave a prior success receipt. Old v1 Pro packets are not manifest members
and are obsolete. No empty or blocked board certifies strategy readiness.

## Validation and limits

Focused smoke: 33 distinct synthetic unittest cases, including CLI integration,
strict schemas/JSON, time/identity, A0-only routing, read-only QA, dependency
completion, all cache dimensions, corruption, missing state and interrupted build.
The existing handoff/agent-standard/lesson smokes are also run through Tier-1.
Remote exact-head CI and review are recorded in the PR; local passing tests alone
are not merge evidence. No live collection, broker/target/paper mutation, ranking,
fullrun, OOS performance, model promotion or Drive accepted-state write occurred.

## Next P0 and stop conditions

Connect the existing complete US equity universe (1,000+) and Multi-Asset candidates
to the same evidence-bound ER1/3/6/12m flow, reusing current producers. Preserve
missing evaluations; do not infer global ranking/BUY_CONSIDERATION from seed
coverage. Check issuer/ADR/corporate action, source availability, calibrated model,
benchmark/cost and complete universe coverage before portfolio integration.

Stop on G0 failure, stale/conflicting source/code/context, incomplete dependency,
invalid receipt, non-green CI or missing exact-head review. Actual book, current
accepted target/thesis, durable Drive history, global ER and current performance
remain unverified by this phase. Confidence is limited to tested control-contract
boundaries. Commit/PR/CI/review/merge and artifact links belong in the final PR
PROJECT_HANDOFF; never relabel a pending gate as completed.
