# Agent Review Packet - PR66 Evidence-Controlled Recovery

Date: 2026-06-15 KST

Audience: Claude Code, ChatGPT Pro, Codex

Purpose: pause implementation after the latest PR66 updates and give other
agents one clear review target before any next code or workflow step.

## Source-Of-Truth Locations

| Tag | Value |
| --- | --- |
| `[LOCAL]` clone | `H:/codex/tmp_r1000_coord_pr` |
| `[LOCAL]` branch | `codex/pr64-coordination-ledger-router-20260615` |
| `[GITHUB]` PR | `https://github.com/wscha231/r1000-quant-engine/pull/66` |
| `[GITHUB]` base | `codex/self-sustaining-loop-20260615` (PR64) |
| `[GITHUB]` head | `codex/pr64-coordination-ledger-router-20260615` |
| `[GITHUB]` code head before this packet | `c20d64e21d1d60de7898d2f6b308996da32bd945` |
| `[GITHUB]` review head | latest `origin/codex/pr64-coordination-ledger-router-20260615` containing this packet |
| `[DRIVE]` role | read-only mirror/research artifact source unless copied into `[LOCAL]` |

Before reviewing, run:

```powershell
# [LOCAL]
cd H:\codex\tmp_r1000_coord_pr
git fetch origin --prune
git switch codex/pr64-coordination-ledger-router-20260615
git reset --keep origin/codex/pr64-coordination-ledger-router-20260615
git rev-parse HEAD
Test-Path docs\AGENT_REVIEW_PACKET_20260615_PR66.md
```

Expected state for this packet: `HEAD` equals
`origin/codex/pr64-coordination-ledger-router-20260615` and the review packet
file exists. The final handoff message that introduced this packet should state
the exact pushed SHA.

## PR Stack

Merge order remains:

1. PR64: `master` <- `codex/self-sustaining-loop-20260615`
2. PR66: `codex/self-sustaining-loop-20260615` <- `codex/pr64-coordination-ledger-router-20260615`
3. PR65: `codex/self-sustaining-loop-20260615` <- `codex/goals-2026-06-15`
4. PR67: `codex/goals-2026-06-15` <- `codex/goals-update-bull-floor-contract-20260615`

Codex and Claude must not merge PRs. The user owns merges.

## Current Objective Wording

PR66 now treats the active objective as governance and evidence-controlled
recovery, not a guaranteed Concentrated CAGR result.

The accepted framing is:

- establish `[LOCAL]`, `[GITHUB]`, `[DRIVE]` source-of-truth discipline;
- keep PR64 interim targets separate from canonical mission targets;
- require 8-year broker-ledger evidence before official promotion;
- close review-only self-correction queue lifecycle;
- run Concentrated recovery A/B as evidence experiments only;
- move only verified candidates to `ready_for_human_review`;
- keep live broker automation forbidden.

This replaces any wording that implies Codex promises to "achieve" a
Concentrated recovery result.

## What PR66 Adds

Review scope:

- `docs/AGENT_LOCATION_DISCIPLINE.md`
- `docs/PR_STACK_EXECUTION_RUNBOOK_20260615.md`
- `docs/PR64_SYSTEM_STATUS_20260615.md`
- `docs/proposals/ledger_reconciliation_20260615.md`
- `tools/run_account_evaluation.py`
- `tools/run_self_correction_router.py`
- `tools/run_ab_result_verifier.py`
- `tools/run_self_correction_queue_closure.py`
- `tools/run_system_acceptance_audit.py`
- `.github/workflows/full_rebuild_manual.yml`
- `cloud_results/performance_ledger/*`
- related smoke tests and `CHANGELOG.md`

Key changes to verify:

1. Target metadata
   - `target_type=interim_operating_gate`
   - `target_contract_status=unresolved_user_decision_required`
   - canonical mission remains Main `35% / -25%`, Concentrated `50% / -25%`
   - PR64 interim gate remains Main `30% / -25%`, Concentrated `50% / -28%`

2. Bull-floor ledger preservation
   - Run `27516185696` is preserved as evidence, not promotion.
   - Ledger verdict is `IMPROVING`.
   - Strengthened gates still fail.

3. Self-correction router/closure
   - Queue items carry `status`, `payload_hash`, `ledger_sha_at_queue`, and
     duplicate/stale metadata.
   - Queue closure maps verifier results to `ready_for_human_review`,
     `rejected`, `measured`, `queued`, or `stale`.
   - No workflow dispatch, production mutation, or live trading occurs in the
     router/closure tools.

4. A/B verifier linkage
   - `run_ab_result_verifier.py` carries `experiment_id`, `payload_hash`,
     `workflow_run_id`, and `dispatch_run_id`.
   - `run_system_acceptance_audit.py` emits those fields in Concentrated A/B
     payloads and includes `post_run_review.verifier_args`.
   - `outputs/ab_result_verifier/` is preserved in workflow artifacts and
     `cloud_results/full_rebuild/<date>/` bundles when present.

5. Concentrated recovery A/B order
   - `conc_continuation_winner_relaxation`
   - `conc_bull_floor_stock_min`
   - `conc_reentry_quality`
   - `conc_theme_leadership_boost`
   - `conc_concentration_cap_relaxation`
   - Era-aware challenger remains review-only.

## Latest Local Validation

These commands passed locally on PR66 before this review packet:

```powershell
# [LOCAL]
python -m py_compile tools\run_system_acceptance_audit.py tools\run_ab_result_verifier.py tools\run_self_correction_queue_closure.py
python tests\system_acceptance_audit_smoke.py
python tests\workflow_artifact_smoke.py
python tests\self_correction_router_smoke.py
python tests\ab_result_verifier_smoke.py
python tests\self_correction_queue_closure_smoke.py
python tests\smoke_test.py --quick
git diff --check
```

`tests/smoke_test.py --quick` reported `32/32 passed`.

Full local `tools/run_pr_validation.py` is not authoritative on this desktop
because the local Python environments are missing some repo-wide dependencies
(`pandas`/`numpy` in the default Python, plus `requests` and a parquet engine in
the bundled Python path). Use GitHub CI as the broad validation source.

## Current CI Caveat

At the time this packet was written:

- `[GITHUB]` PR66 code head before this packet was
  `c20d64e21d1d60de7898d2f6b308996da32bd945`.
- `[GITHUB]` classic commit status API returned `pending` with `total_count=0`.
- Check-runs may still be running or may need to be viewed from the GitHub
  Actions UI.

Do not claim PR66 is merge-ready until the latest head's GitHub checks are
confirmed green.

## Review Questions For Claude / ChatGPT Pro

Please answer these before Codex continues implementation:

1. Does PR66 correctly avoid promising Concentrated CAGR recovery and instead
   frame the work as evidence-controlled A/B candidate selection?
2. Is the PR64 -> PR66 -> PR65 -> PR67 stack order still correct after the
   latest PR66 commits?
3. Are the system acceptance A/B payload identifiers sufficient for the chain:
   payload -> GitHub workflow run -> `run_ab_result_verifier.py` ->
   `run_self_correction_queue_closure.py`?
4. Is preserving `outputs/ab_result_verifier/` in both upload artifacts and
   `cloud_results/full_rebuild/<date>/` enough, or should verifier outputs be
   copied into another run-level directory?
5. Should PR65/PR67 goal YAML be updated after PR66 lands to mirror this exact
   master-objective wording, or is the current stacked docs plan sufficient?

## Stop Conditions

Until the review feedback returns:

- Do not merge any PR.
- Do not dispatch 8-year bootstrap/full rebuild workflows.
- Do not run Concentrated recovery A/B workflows.
- Do not modify production target books.
- Do not enable live trading.
- Do not continue broad implementation beyond review feedback fixes.

Allowed next steps are limited to:

- answer reviewer questions;
- fix reviewer-identified PR66 issues;
- update PR66 documentation if wording is unclear;
- confirm CI status for the latest PR66 head.
