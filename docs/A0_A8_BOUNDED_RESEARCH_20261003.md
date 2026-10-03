# A0/A8 bounded research — H1 offline admission adapter

TASK_KEY: R1000-A0-A8-BOUNDED-RESEARCH-AUTOMATION-V1-20261003.
Owner: A0/A8. Repository: wscha231/r1000-quant-engine.
Integrated base: master@a53aebc353db8d2d0bcd054415c1181a3ab7eff0.
Original implementation base: master@26b546173c1aafcb8fcc4d2e8e7fe575b52b2a8d.
Branch: h1/a0-a8-bounded-research-20261003.
Standing execution: DISABLED. Research state: BLOCKED / WAIT_DEPENDENCY.

Base-refresh task: R1000-A0-A8-BOUNDED-RESEARCH-BASE-REFRESH-20261003.
The first base refresh integrated master659ded58 at head6d2fe16a, preserving
both the PR570 and A8 preview lesson entries. Its six functional files were
then identical to previous headfe88d270. Independent review5400633185 found
five admission/resource defects; that head is not final approval evidence.
The approved correction below also integrates the subsequent master advance
without rewriting history. Merge to master and activation remain unapproved.

## Approved correction pass work report — 2026-10-04

Task: R1000-A0-A8-BOUNDED-RESEARCH-CORRECTION-20261004. H1 only.
Starting PR head: 6d2fe16a6bdd783c3bd85a41cb7ca3839bb6a00c.
The user approved one correction of the five reproduced review findings,
followed by new-head validation and one independent review. Edits are limited
to bounded_research.py, run_agent_board.py, bounded_research_smoke.py and
the two already-scoped documents. Configuration, workflow and registration
wrapper retain their prior bytes; inherited master work remains outside the
PR's eight-file diff.

| Finding | Correction and regression evidence |
| --- | --- |
| Summary source admission | Reuse native accepted-head false-authority fields; require empty blockers and strict integer counts matching actual event types. Missing/true/mistyped flags and misleading counts reject before artifact admission. |
| Relative intake | One resolver in prewrite checks and prepare uses latest-run for relative paths. Exercise both relative and absolute board invocations; escaping paths reject before any board write. |
| Completed outcome | Require finite values for all nine native required metrics; the three actionable metrics are explicitly null and not_applicable_at_1d only at horizon1. Missing/bool/nonfinite values and contradictory status reject. Missing costs/ER remain unavailable. |
| Aggregate source I/O | Intake, initial source reads and final source rechecks share one allowance. Physical reads never request the former extra sentinel byte. Test 2.5 MB padding, exact aggregate capacity and one-byte-short rejection; failure revokes manifest membership. |
| Native identity | Candidate portfolio must be absent/empty; held portfolio must be nonblank and normalized, with positive marked weight. Reject noncanonical ticker aliases and internally rehashed duplicate candidate units. Preserve separate legitimate held portfolios and the original 24-character identities. |

The focused suite now contains 54 synthetic tests, including 13 added
regressions. CI, the final exact head, review responses and unresolved-thread
readback are recorded in PR573 after publication, without changing the reviewed
tree just to append remote status. Tests establish offline admission behavior;
actual source admission, economic validation, model/experiment execution,
authorized trigger execution and durable research readback remain NOT_RUN.
The unchanged zero-budget config SHA256 is
96d2bcad1358c7335a3e82417deced95c0d0cc470c8a07585576cfb9c2ee7f20.
Stop if new-head CI fails, a new actionable review finding appears, current
source scope conflicts, or the final head changes. Keep Draft until the
separately authorized readiness/review-complete gate is satisfied.

This implements the bounded fallback when current outcome/evaluator/runtime
prerequisites cannot admit an economic experiment. It connects original
forward-outcome records to an offline evaluation artifact and H1 hypothesis,
then exposes the blocked route through the existing A0 board. It does not
complete the model, experiment, independent economic validation or durable
research loop. Unit fixtures are not REAL_INPUT_VERIFIED.

## Reuse map, allowed files and stop conditions

| Existing capability | Classification | Connection |
| --- | --- | --- |
| A0 run_agent_board and agent_task_queue | REUSE / EXTEND | Explicit offline sidecar, original queue preserved |
| completed_tasks V2 and A6 dependencies | REUSE | No synthetic completion or second receipt store |
| run287 forward risk-outcome archive | REUSE | Native 24-character observation identity and original intent |
| do-not-repeat registry and evaluate_candidate | REUSE | Read-only evidence-gap hypothesis check |
| Candidate Registry reference index, merged PR560 | REUSE boundary | No second registry; current immutable reference rules retained |
| Agent Board (Manual) Actions | EXTEND | Empty-by-default input; existing upload only |
| Economic evaluation/A1 admission | BLOCKED dependency | Preview lacks a verified economic input/evaluator receipt; merged code alone does not admit that input |
| Model adapter / paid budget / durable research writer | MISSING / BLOCKED | Zero calls and no Drive writes |
| Standing activation contract | MISSING | No schedule or producer subscription enabled |

Allowed files:

- research/control_plane/bounded_research.py
- research/control_plane/bounded_research_v1.json
- tools/run_agent_board.py
- tests/bounded_research_smoke.py
- tests/agent_board_smoke.py
- .github/workflows/agent_board_manual.yml
- docs/A0_A8_BOUNDED_RESEARCH_20261003.md
- docs/AGENT_SHARED_LESSONS_LEDGER.md

Dependencies are a separately refreshed canonical A0 intake, original producer
event bytes and receipt, A1 admission, evaluator integrity, independent A6,
and authorized runtime/storage for further stages. Stop on conflicting
provenance, expired inputs, a concurrent writer, exceeded bounds or output
readback failure. No protected gate, evaluation strategy, Korean repository,
accepted publication, book, secret or promotion path is in scope.

## Entry point and input contract

```sh
python tools/run_agent_board.py --latest-run /scratch/source \
  --output-dir /scratch/board \
  --system-state /scratch/source/control_plane/system_state.json \
  --canonical-inputs /scratch/current/intake.json --evidence-root /scratch/current \
  --bounded-research-intake /scratch/source/research_intake.json
```

Omitting the option preserves the existing board path without loading the
adapter. All board invocations share output ownership, so a default run also
respects a preview writer's lock. Normal single-run default outputs are preserved.
The manual Actions workflow passes these optional arguments to
the existing runner; no new scheduler, model provider or dispatch is added.
It does not create a research intake from legacy metric files or authenticate
canonical data automatically. Both the source root and output root must be
disjoint scratch paths; the caller must supply the existing canonical A0
refresh inputs separately. A blocked sidecar makes the opt-in board blocked.
Relative bounded-research intake paths resolve beneath latest-run; absolute
paths must also be inside that source root. This same rule is enforced before
any board write and when preparing the sidecar.

Intake has schema_version=bounded-research-intake-v1, producer and inputs.
Producer fields: repository, branch, head_sha, workflow, run_id, attempt,
conclusion and artifact_sha256. The allowed declaration is this repository,
master, Daily Operating Selection Refresh, success. The trusted caller must
authenticate these fields from current GitHub evidence; local consistency
checks do not authenticate declarations. Input roles events, summary and
calendar use the existing artifact descriptor (path, sha256, observed_at,
available_at, collected_at, expires_at, status). Calendar sessions must be
the frozen, admitted completed-market-session sequence, not guessed weekdays.

The adapter checks exact byte hashes, event-log binding, source eligibility
and expiry, native event identities, immutable signal snapshots, original
cohort membership, data-class conflicts, event clocks and exact horizon
maturity. It never adds a hindsight security or recreates missing decision
reasons. Candidate rows remain Model Proposal; held account class is UNKNOWN.
Missing security identity, public availability, currency, thesis, ER, costs,
fills and counterfactual policy stay UNKNOWN or NOT_AVAILABLE.

Producer return/drawdown/recovery/maximum-gain values are diagnostic only.
MFE/MAE never become decision features. Net economic metrics and alpha remain
unavailable; no winner definition, automatic exit or replacement rule is added.
One H1 provenance-gap hypothesis may be prepared with alternative explanation,
required data, verification, expected benefit, cost/risk and rejection condition.
No Control/Challenger is admitted or executed. The experiment ledger and
do-not-repeat registry retain their existing authority.

## Bounds, reuse and recovery

Preview limits are 30 seconds, 4 MiB aggregate source bytes, 4 MiB result
bytes and 10,000 events. Model calls, tokens, daily/monthly dollars, I/O
retries and comparisons are zero. No network, arbitrary shell, generated-code
execution, notification or operational credential access exists in the adapter.

Reuse identity binds intake pins, code/config, rejection registry, A0 dependency
identities, task keys, UTC maturity date and expiry clocks. The manifest commits
last after result readback, source-byte recheck and current expiry verification.
Partial scratch writes are inspected and can resume without another result
write. Corrupt cached output revokes acceptance. O_EXCL locks are never stolen;
another process cannot overwrite an active attempt. Input/output overlap,
separately supplied canonical inputs/evidence/state, reparse links, hard-linked
output files and fixed temporary-file aliases fail
before writes. This is trusted local filesystem protection, not an OS sandbox
for executing untrusted code; no untrusted code is executed.

Scratch result/manifest hashes are not durable Drive receipts, authenticated
producer evidence or A1/A6 completion. No second queue, registry or accepted
namespace is created. The proposed future caps (one concurrent research,
three weekly hypotheses, one named comparison, two I/O retries, 300 seconds)
are under activation_proposal_only and are not applied. enabled=true is rejected.

## Observed evidence and remaining blockers

- Base master26b54617 includes merged Candidate Registry PR560. The active
  evaluation changes in another checkout were preserved; the user explicitly
  approved this isolated worktree.
- Daily run37103143806, attempt1, head30915e05, job111146459932 failed at the
  paper/selector transaction: BLOCKED_SESSION_GAP, prior2026-07-27,
  expected_next2026-07-28, requested2026-10-02. Outcome resolution, accepted
  publication and paper persistence were skipped. Diagnostic artifact11268112206
  has digest e6418abce51446aa8c08472c9f1c7a60467e86f5498c5d106e4c13c041621e76.
  This task did not rerun or resume that transaction.
- History run37010733011, attempt1, head30915e05, job110849559520 was cancelled
  during collection/persistence/clean consumption. Diagnostic artifact11235450188
  has digest645b95c9554b6eb111470e5e17cb256859147e6874e63562d986c33af2d0f8e4.
- Existing Drive discovery used docs/RESEARCH_DATA_ACCESS.md. The latest listed
  commit was14c67c8299ea6e4315d5fe84c30d701ac1fd2af71a6438e219991a37416fdb2e;
  listed execution receipts preceded it. Catalog/pack/linked-receipt bytes were
  not successfully verified. No long-history rows were admitted.
- A preserved local accepted-outcome summary had zero observations. It cannot
  substitute for current accepted source admission.
- Actual model/Actions authorization and durable research-output readback:
  NOT_RUN. No paid budget or research-writer authorization is supplied here.

Validation is registered through the existing agent_board_smoke Tier-1 entry;
the protected run_pr_validation runner is unchanged. Focused regressions cover
54 synthetic cases, including native summary/metric/identity admission,
aggregate source-read accounting, relative-intake isolation,
separate-process exclusion, partial-save resume,
expiry/maturity/dependency changes, output/time budgets, malicious instructions,
original intent, label maturity and default-disabled behavior. Run both
python tests/agent_board_smoke.py and python -O tests/agent_board_smoke.py.
Run proportionate validation with --only agent_board --only agent_shared_lessons
--only run287_do_not_repeat_registry --only workflow_artifact. CI and exact-head
review evidence belongs to the PR; it does not certify a research runner.
Local A0, lessons and rejection-registry validation passed. The broader workflow
suite failed its unchanged daily capture-config Windows path assertion ('/'
versus '\\'); that transactional path is outside this causal scope. No claim of
all repository checks passing is made. The new adapter suite passed normal and
optimized Python; exact-head review and remote CI are recorded with the PR.
Local Python was 3.14.4. The bundled 3.12 interpreter lacked jsonschema, so
its smoke was NOT_RUN; the configured CI installs dependencies on Python3.12.
Independent review of the initial head found separate-input overlap, a default
writer bypassing the new lock, causally inverted outcome recording and the
native skipped-summary timestamp gap. These were corrected with regressions;
all descriptor clocks are also checked before any source bytes are read. Final
exact-head review remains distinct from a future economic A6 receipt.
The subsequent review reproduced a Windows device/extended namespace alias
that referenced the source directory through a different spelling. Such paths
are rejected before writes; ordinary paths are canonicalized. A native Windows
regression pins event bytes to the would-be overwritten manifest and checks
that the input remains unchanged.

## One activation packet, held pending prerequisites

Requested future scope: a single research-only preview through the existing
Agent Board (Manual) workflow, with a trusted, currently verified producer
intake and existing canonical A0 refresh. Bind reviewed PR head and exact
bounded_research_v1.json bytes; inputs are the explicitly named read-only
source/calendars, outputs only outputs/agent_board and its existing diagnostic
GitHub upload. No Drive writer, model, public alert or accepted book side effect.
Caps: one invocation, 30 seconds adapter time, 4 MiB source/result, 10,000 events,
zero model/tokens/dollars/retries/comparisons. Consume once, expire 24 hours
after approval, disable by omitting bounded_research_intake. Standing repetition,
a new model provider or a durable research path requires a later reviewed
implementation and exact scoped authorization.

This packet is prepared but not authorized or executed. Current prerequisite
state remains BLOCKED_MODEL_RUNTIME / WAIT_DEPENDENCY; do not label the full
research automation or automatic operation complete. Merge, real input,
economic validation, final holdout, actual trigger and durable readback are
separate gates. Broker/paper/target/Champion/risk/public/secret state is unchanged.
Work requests0, research model API calls0, paid data calls0. The implementation
chat and an explicitly requested independent review have account cost UNKNOWN.
