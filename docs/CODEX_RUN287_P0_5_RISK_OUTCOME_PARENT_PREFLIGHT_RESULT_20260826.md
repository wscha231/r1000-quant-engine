# Run287 P0-5 risk-outcome parent preflight result

Date: 2026-08-26

Scope: issue #357 diagnostic and authorization boundary only

## Decision

P0-5 now emits a durable, read-only receipt before the daily operating
workflow can adopt a legacy risk-outcome parent or create a true outcome
genesis. The scheduled path remains fail-closed with exit code `2`. No
workflow was dispatched or rerun, and no target, order, paper ledger, Drive
canonical, champion, production, or live state was changed.

The original issue hypothesis about remote review/comment drift is rejected.
The actual blocker is the intentional one-time migration boundary.

## Exact corrected evidence

- Failed workflow run/job: `31071342439` / `92519747130`.
- Failed source head: `f28321d011d0705cf8fdd43f1f98647f85557d42`.
- Failed step: `Restore verified risk-outcome accepted head`.
- Exact predicate: `ALLOW_QUARANTINED_LEGACY_OUTCOME_PARENT != true`.
- Exact terminal message:
  `[risk-outcome] BLOCKED: legacy outcome parent requires explicit one-time workflow_dispatch authorization`.
- Exit code: `2`.
- Selector, paper transaction, accepted publication, and accepted persistence
  were skipped.
- The authoritative Drive view had zero committed
  `run287_risk_outcome_accepted_heads` and retained the legacy
  `run287_risk_outcome_archive`.
- Legacy `summary.json`: 668 bytes, SHA-256
  `5a57e4becef19668dce45803eb77185bc6c60bcf9b58522df939e9a48a56654c`,
  as of `2026-07-17`, status `SKIPPED_NO_DECISION_OBSERVATIONS`, review-only.
- The separate paper ledger was a valid six-head chain through `2026-07-24`.
  Its genesis is
  `ef78e63c9e52607a6473ca4c07179cb92a5f29a85eeb43031e8a47cd09b4f267`
  and its terminal head is
  `65fa6f5b4b12729811b72a90661fc744320826dfe868ec6da2632768b1ec02a7`.

The current issue correction is
[issue comment 5413020822](https://github.com/wscha231/r1000-quant-engine/issues/357#issuecomment-5413020822).

## Implemented boundary

`tools/build_run287_risk_outcome_parent_preflight.py` records and validates:

1. authoritative Drive accepted-head discovery completed;
2. committed remote accepted-head count is exactly zero;
3. the remote legacy parent was fetched and checksum-compared, or true legacy
   absence was proved;
4. the legacy summary is the byte-exact registered hash and passes the existing
   review-only safety migration contract;
5. the restored paper ledger has a structurally valid verified integrity head;
6. legacy quarantine and genesis authorizations are mutually exclusive;
7. authorization is accepted only from `workflow_dispatch` with the matching
   one-time Boolean input.

Every receipt carries the source commit, run, attempt, job key, NYSE session,
observed parent/paper identities, blocker, next action, and a complete false
safety envelope. The tool can return READY only to the existing parent-anchor
boundary. It cannot create the anchor or accepted head itself.

The receipt is uploaded by the always-run diagnostic artifact and copied to
the run-addressed diagnostic Drive namespace. It is not a target, order,
accepted paper state, or promotion artifact.

## Failure behavior

The known scheduled state produces:

- status:
  `BLOCKED_ONE_TIME_LEGACY_QUARANTINE_AUTHORIZATION_REQUIRED`;
- blocker: `explicit_workflow_dispatch_authorization_required`;
- exit code: `2`;
- next action: `obtain_separate_user_approval_before_workflow_dispatch`;
- all target/order/ledger/fullrun/production/live/promotion flags: `false`.

Unknown legacy bytes, unconfirmed remote absence, an existing remote accepted
head, missing paper integrity, wrong-mode authorization, and simultaneous
genesis/legacy authorization all fail closed.

## Validation

- Parent-preflight fixtures: `7/7` passed.
- Focused risk-outcome/workflow/ledger/security/fullrun regression: `9/9`
  test files passed.
- Workflow ordering/artifact contract: passed.
- Python compilation: passed.
- Workflow YAML parse: passed.
- `git diff --check`: passed.
- Registered complete PR validation: `222/224` test files passed in
  `754.71s`. The only two failures were the pre-existing Windows checkout
  portability caveat in `run287_ohlcv_location_timing_challenger_smoke.py`
  and `run287_ohlcv_pattern_memory_smoke.py`: the tracked LF contract blob has
  the correctly pinned SHA-256
  `30c1e17224d68f5d006ca4da5fd403f31037efb3c1b7871918fed50329c16202`,
  while global `core.autocrlf=true` exposes CRLF worktree bytes with SHA-256
  `dd8b9a79678a9daf3040e747118ebc2f8cf00670e34a59300cde79be4cb862a6`.
  This exact two-test caveat was already recorded in the shared ledger on
  `2026-08-23`; neither failing path is changed by P0-5.

Publication still requires exact-head review and an explicit decision on the
pre-existing OHLCV contract line-ending portability defect.

## Next gate

This change does not authorize the migration. After the branch is reviewed and
merged, the next state-changing action still requires separate user approval
for one exact `workflow_dispatch` with only
`allow_quarantined_legacy_outcome_parent=true`, on an exact reviewed master
head and intended session. The resulting receipt, parent anchor, accepted
outcome head, paper transaction, and durable publication must all pass before
any chronological catch-up is considered.

Chronological catch-up is a separate authorization and must process one exact
NYSE successor at a time. A successful one-time migration does not authorize
a blind rerun, fullrun, production, or live trading.

- Fullrun executed: false.
- Workflow dispatched or rerun: false.
- Target/order/ledger mutation: false.
- Drive mutation: false.
- Production/live trading enabled: false.
- Automatic promotion enabled: false.
