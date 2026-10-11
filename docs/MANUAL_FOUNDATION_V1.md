# Manual Foundation V1

This is a C2 docs/control-plane proposal under #448 Manual V1/V2/V3. It reduces
repeated handoff/reuse work across chats, models and computers. Adoption requires
normal exact-head review. AGENTS, operating/domain contracts and existing
authority remain stronger than a playbook. No specialist is invoked.

## Canonical surfaces

- `research/control_plane/manual_playbooks_v1.json`: exactly three current
  playbooks, each with Process / Toolbox / Proof / Learning. Toolbox is a list
  of existing paths; lessons and failed research stay in their existing stores.
- `research/control_plane/manual_task_packet_schema.json`: a non-executable
  manual pinning envelope, including A0 resume jobs. It does not replace
  `task-packet-v2`, board identity or `verification-receipt-v2`.
- `docs/pr_reuse_catalog.json`: the only machine-readable capability catalog.
  PR metadata and Issue requirements are distinct; an Issue has no PR HEAD.
- `tools/manual_foundation.py`: strict offline validation/lookup using existing
  board JSON/hash primitives, authority schema and do-not-repeat evaluator.
- `tests/agent_board_smoke.py`: existing registered CI entrypoint now also runs
  the focused manual suite. No protected runner/Actions/board dispatch change.

## Preparing one task

1. Independently read live master, AGENTS/domain contract, current roadmap and
   actual writer/worktree evidence. Implementation requires an existing approved
   writable clean worktree. Stop on observed overlap or absent authority.
2. Read the current playbook version. Consult the catalog and canonical
   do-not-repeat registry; do not search hundreds of historical PRs again.
3. Supply one independently verified scope object with `base_sha`, `owner`,
   `dependencies` (repository path -> actual SHA256), `allowed_files`, existing
   `authority` booleans and `authority_tier`. `required_dependencies()` lists
   mandatory policy/manual/tool/catalog/schema paths. Include any additional
   actual input/receipt dependency needed by the task.
4. Prepare one ephemeral `manual-task-packet-v1` containing the schema's fields.
   Copy exact Toolbox/Proof/stop requirements from the pinned playbook. Use the
   independently authorized scope, not the packet's own assertions, to validate.
5. Compute `packet_sha256` from the full object excluding that field. Use the
   board's canonical JSON: sorted keys, separators `(',', ':')`, no nonfinite
   numbers, UTF-8. `playbook_sha256` similarly excludes only its own field.
6. Run:

   ```bash
   python tools/manual_foundation.py --packet /path/task.json \
     --scope /path/verified_scope.json --expected-base <live-master-sha>
   ```

The command only prints a preflight result. A consistent supplied scope/hash is
not authentication of human approval or a live GitHub read. The operator must
ground those independently. `VALIDATED_PREPARE_ONLY` means pins match; all job
proofs remain `NOT_RUN`, `completed_task=false`, `worker_invoked=false` and
economic authority is false. This receipt cannot enter A0 completed_tasks or
grant source admission, ER/A5, target, paper/broker, Fullrun, dispatch or merge.
The task's `output_receipt` declares its eventual coordination/verification
format; this tool neither writes it nor verifies completed work.

## Reuse and change rules

`REUSE_NOW` permits reading/reusing current hash-bound capability within a
separately authorized task, not economic promotion. `SELECTIVE_PORT` requires
scoped reconstruction/reconciliation; `HISTORICAL_LESSON` is historical context.
`DO_NOT_REPEAT` resolves existing registry IDs and blocks unchanged rejected
research. `SUPERSEDED` cannot be selected for use. Unknown records, changed
dependency bytes and missing canonical failure references fail closed.

Record `verified_at`, master, original source heads and consumed-path hashes.
Master movement triggers live task-base reconciliation; recheck only affected
catalog/playbook/tool dependencies, preserving historical SHA evidence. Catalog
semantic classifications are reviewed changes, not automatic metadata policy.

For a playbook correction, add a new version, set `supersedes` to the prior
version, retain the prior row as `SUPERSEDED`, and update `current_versions` to
the sole current version. Recompute its hash and rerun affected proofs. Old
packets stop. Learning classifies Process/Toolbox/Proof and proposes the smallest
C2 correction in the canonical shared lessons/tests. C3 strategy/economic/
authority changes keep their existing separate approval gates.

## This slice's limits and next lane

Only L0 resume/handoff, A1 admission-refresh **preparation**, A6 independent QA
manuals are included. A1 actual source collection/pointer publication and A6
reviewer authentication/real proof are later task-specific actions. Existing A0
planning remains proposal-only. No scheduler/framework/dispatcher/backtester,
source collection, strategy threshold, A3/ER/A5, Fullrun, paper/broker, website
or auto-merge change. After this Main writer releases, next Main-lane work is
P1-B frozen all-consumed-source fairness under its exact dependencies/lease.

## Exact-head correction rules

The A6 manual packet and independently verified scope carry review_identity with
repository, PR number and exact implementation HEAD. A6 validation also requires
the independently observed expected review HEAD; a moved PR HEAD invalidates an
old handoff. Non-A6 packets carry a null review identity.

The shared lessons ledger is a common required dependency for all three
playbooks. Allowed-file scope means explicit files only: an existing directory
is rejected, while an explicit not-yet-created file path may be prepared when
the independent scope allows it.

Catalog provenance is structural. Issue rows carry Issue-kind metadata and no
source HEAD. PR rows carry PR-kind metadata and one exact head for every
declared PR. A REUSE_NOW entry must hash-bind every path named by both
current_equivalent and toolbox_refs. SUPERSEDED classification and a successor
declaration must appear together; a superseded row cannot be reused.

Do-not-repeat packets preserve the canonical evaluator contract. The existing
component coverage increase and explicit semantic-change fields may be supplied
and are included in the packet hash. The Manual layer does not redefine the
evaluator's allow/block policy.

Final-review hardening also makes manual succession monotonic: a current
playbook that declares a predecessor must use a strictly greater semantic
version and the predecessor row must already be marked SUPERSEDED. A REUSE_NOW
catalog row with a non-null expiry must carry a valid timezone-aware timestamp
that is still in the future; expired reusable evidence fails closed rather than
remaining selectable.

