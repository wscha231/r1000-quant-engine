# PR Stack Execution Runbook - 2026-06-15

This runbook is the shared next-step contract for Claude Code, Codex, and
ChatGPT Pro. It uses the location tags from `docs/AGENT_LOCATION_DISCIPLINE.md`.

## Master Objective

Stabilize AlphaOps vNext governance and evidence-controlled recovery workflow
before any further production promotion.

The objective is not to promise a Concentrated CAGR recovery result. The
objective is to make sure every agent can safely run and review evidence with
the right label: dirty runs are `DO_NOT_USE`, clean 7-year broker-ledger runs
may drive Alpha Plane audit/A-B research, and only robust or official evidence
can become promotion review material.

Scope:

1. Enforce shared `[LOCAL]`, `[GITHUB]`, and `[DRIVE]` source-of-truth
   discipline for Claude Code, Codex, and ChatGPT Pro.
2. Safely organize the stacked PR sequence: #64, #66, #65, #67. Codex and
   Claude must not merge; the user owns merges.
3. Treat PR64 Main `30% / -25%` and Concentrated `50% / -28%` as interim
   operating gates only. Canonical mission remains Main `35% / -25%` and
   Concentrated `50% / -25%` until explicit user approval.
4. Enforce evidence tiers. Clean 7-year broker-ledger evidence is usable for
   research/A-B and daily preview; Tier 3/4 evidence is required before
   promotion review.
5. Close the self-correction queue lifecycle: `queued -> dispatched -> measured
   -> rejected / ready_for_human_review / closed`, with duplicate suppression,
   stale payload detection, payload hash, and A/B result verifier linkage.
6. Run Concentrated recovery A/B as evidence experiments only. Priority is
   continuation winner / hysteresis, bull-floor stock exposure, reentry
   quality, theme leadership boost, concentration-cap relaxation, and
   era-aware challenger as review-only.
7. Allow paper actions only as approval-required previews. Live broker
   automation remains forbidden.

Non-goals:

- No live trading.
- No automatic production mutation.
- No whole Claude branch merge.
- No legacy/proxy metric promotion.
- No target-contract rewrite without user approval.
- No headline CAGR-only promotion.

## Current Stack

| PR | Purpose | Base | Head | Required before merge |
| --- | --- | --- | --- | --- |
| #64 | Integrated evaluation control loop: 8-year gate, sidecars, review dispatch, paper-only safety | `master` | `codex/self-sustaining-loop-20260615` | CI green, user review |
| #66 | Coordination discipline, bull-floor ledger preservation, target metadata, queue closure | `codex/self-sustaining-loop-20260615` | `codex/pr64-coordination-ledger-router-20260615` | CI green, PR64 still same base SHA or rebase |
| #65 | Review-only goal proposal | `codex/self-sustaining-loop-20260615` | `codex/goals-2026-06-15` | PR64 landed or base retargeted correctly |
| #67 | Bull-floor verdict and target-conflict update for goals | `codex/goals-2026-06-15` | `codex/goals-update-bull-floor-contract-20260615` | PR65 landed or base retargeted correctly |

Merge order is #64, #66, #65, #67. Codex and Claude must not merge these PRs;
the user owns merges.

## Pre-Merge Checks

Before any merge decision:

1. `[LOCAL] git fetch origin --prune`
2. `[LOCAL] git rev-parse origin/master`
3. `[GITHUB] Confirm the PR base/head SHAs and CI status.`
4. `[GITHUB] Confirm no PR was silently retargeted.`
5. `[LOCAL] If reviewing code, switch to a local branch that tracks the exact
   PR head SHA.`

If `[LOCAL]` and `[GITHUB]` disagree, use `[GITHUB] origin/*` as branch truth
after fetch.

## Post-Merge Sequence

After #64 and #66 land on `master`, run the evidence loop in this order.

## Evidence Tier Policy

All agents must use `tools/evidence_policy.py` and
`outputs/evidence_policy/evidence_status.json` when deciding what a run may be
used for.

| Tier | Label | Allowed use | Blocked use |
| --- | --- | --- | --- |
| Tier 0 | `do_not_use` | diagnostics only | audit/A-B, daily preview, human review, promotion |
| Tier 1 | `research_7y` | Alpha Plane audit and A-B research | official promotion |
| Tier 2 | `operating_candidate` | daily operating preview and `ready_for_human_review` | official promotion |
| Tier 3 | `robust_candidate` | stronger human review after 8Y or proxy_10y robustness | automatic promotion |
| Tier 4 | `official_promotion` | promotion review with human approval | automatic/live trading |

Tier 0 applies regardless of length when data readiness is false, the universe
is starved, official broker metrics are missing, current/order preview is
invalid, or only legacy/proxy metrics are present. `valid_for_production=false`
continues to block Tier 4 promotion, but it does not by itself invalidate clean
Tier 1 research evidence.

## Latest Local Readiness Probe

`[LOCAL]` A non-committed probe against
`cloud_results/full_rebuild/latest_global_alpha_universe` on 2026-06-15 returned
`status=not_ready`.

Key evidence:

| Field | Value |
| --- | --- |
| target_start_date | `2018-06-12` |
| target_end_date | `2026-06-12` |
| selected_target_book_ticker_count | `417` |
| main_target_book_ticker_count | `372` |
| concentrated_target_book_ticker_count | `269` |
| hard_blocker_count | `7` |

Hard blockers:

- `price_cache_window`
- `price_cache_ticker_count`
- `main_target_book_window`
- `concentrated_target_book_window`
- `main_broker_replay_window`
- `concentrated_broker_replay_window`
- `pit_universe_label`

Generated review-only dispatch order:

1. `bootstrap_free_data_for_eight_year_window`
2. `full_rebuild_eight_year_official_window`

The second payload depends on the first. Do not bypass this dependency with a
hand-written `gh workflow run` command.

Dispatcher dry-run verification:

| Field | Value |
| --- | --- |
| status | `dry_run_blocked` |
| ready_count | `1` |
| blocked_count | `1` |
| dispatched_count | `0` |
| ready payload | `bootstrap_free_data_for_eight_year_window` |
| blocked payload | `full_rebuild_eight_year_official_window` |
| blocked reason | `unmet_dependencies:bootstrap_free_data_for_eight_year_window` |

### 1. Generate 8-Year Readiness

Run on the merged default branch:

```powershell
# [LOCAL]
git fetch origin --prune
git switch master
git pull --ff-only origin master
python tools\check_10y_backtest_readiness.py `
  --latest-run cloud_results/full_rebuild/latest_global_alpha_universe `
  --min-years 8 `
  --output-dir outputs/eight_year_backtest_readiness `
  --ref master `
  --repo wscha231/r1000-quant-engine
```

Expected artifacts:

- `outputs/eight_year_backtest_readiness/summary.json`
- `outputs/eight_year_backtest_readiness/workflow_dispatch_payloads.json`
- `outputs/eight_year_backtest_readiness/data_extension_plan.md`
- `outputs/eight_year_backtest_readiness/data_extension_tasks.csv`

Do not call a run official unless `official_window_ready=true` or the later
account evaluation passes the 8-year broker-ledger gate.

### 2. Dry-Run Dispatch Plan

```powershell
# [LOCAL]
python tools\run_review_dispatcher.py `
  --payloads outputs/eight_year_backtest_readiness/workflow_dispatch_payloads.json `
  --output-dir outputs/review_dispatcher_eight_year `
  --repo wscha231/r1000-quant-engine
```

The dispatcher must stay dry-run unless the user explicitly approves execution.
The exact approval token is `APPROVE_REVIEW_WORKFLOW_DISPATCH`.

### 3. Execute Bootstrap/Rebuild Only With Approval

If the user approves dispatch, execute only ready payloads:

```powershell
# [LOCAL] review generated commands first
Get-Content outputs\review_dispatcher_eight_year\dispatch_commands.sh
```

The usual order is:

1. `bootstrap_free_data_for_eight_year_window`
2. `full_rebuild_eight_year_official_window`

If the rebuild payload depends on the bootstrap plan, pass the completed plan
id to the dispatcher after the bootstrap workflow has completed and artifacts
have been inspected.

## Official 8-Year Acceptance

After the 8-year full rebuild completes, inspect the committed or downloaded
run artifacts:

```powershell
# [LOCAL]
python tools\run_account_evaluation.py --help
```

Required evidence in the run directory:

- `account_evaluation/official_metrics.json`
- `broker_replay/main/equity_curve.csv`
- `broker_replay/concentrated/equity_curve.csv`
- `eight_year_backtest_readiness/summary.json`
- `data_readiness/summary.json`
- `is_attribution/summary.json`
- `system_acceptance_audit/summary.json`
- `oos_lock/summary.json`

Promotion remains blocked if any of these are missing, if either portfolio is
`invalid_window`, if `production_activation_allowed` is not false in review
artifacts, or if OOS/IS lottery gates fail.

## Concentrated Recovery A/B

Only start these from Tier 1 or better evidence. Do not run them from Tier 0
evidence. Promotion review still requires Tier 3/4 evidence or explicit user
approval of an alternative evidence contract.

Priority order:

1. `conc_continuation_winner_relaxation`
2. `conc_bull_floor_stock_min`
3. `conc_reentry_quality`
4. `conc_theme_leadership_boost`
5. `conc_concentration_cap_relaxation`

Use router/system-acceptance payloads, not hand-written workflow inputs, unless
the payload is stale and has been regenerated.
System-acceptance A/B payloads must carry `experiment_id`, `payload_hash`, and
`post_run_review.verifier_args`; use those values directly when running the
verifier so queue closure can join results back to the review queue.

```powershell
# [LOCAL]
python tools\run_review_dispatcher.py `
  --payloads outputs/self_correction_router/workflow_dispatch_payloads.json `
  --output-dir outputs/review_dispatcher_self_correction `
  --repo wscha231/r1000-quant-engine
```

## A/B Result Verification

For every completed candidate run:

```powershell
# [LOCAL]
python tools\run_ab_result_verifier.py `
  --baseline-run cloud_results/full_rebuild/latest_global_alpha_universe `
  --candidate-run cloud_results/full_rebuild/<candidate_run_dir> `
  --portfolio concentrated `
  --experiment-id <experiment_id> `
  --payload-hash <payload_hash> `
  --workflow-run-id <github_actions_run_id> `
  --dispatch-run-id <plan_id> `
  --output-dir outputs/ab_result_verifier/<experiment_id>
```

Positive verifier decisions are tiered: `measured_research_7y` is research-only,
`ready_for_human_review` / `robust_candidate_review_only` allow human review,
and `promote_candidate_review_only` is the only promotion-review decision. None
of these decisions mutates production.

## Queue Closure

After verifier summaries exist:

```powershell
# [LOCAL]
python tools\run_self_correction_queue_closure.py `
  --queue-path outputs/self_correction_router/router_queue.json `
  --verifier-dir outputs/ab_result_verifier/<experiment_id> `
  --output-dir outputs/self_correction_queue
```

Status meaning:

| Status | Meaning |
| --- | --- |
| `ready_for_human_review` | Candidate passed verifier gates; user review and separate PR required |
| `rejected` | Candidate failed or had invalid evidence |
| `measured` | Evidence exists but is blocked, usually by OOS/system acceptance |
| `queued` | No matching verifier summary yet |
| `stale` | Payload was generated against stale ledger/base evidence |

## Target Contract Rules

- Canonical mission remains Main `35% / -25%`, Concentrated `50% / -25%`.
- PR64 interim operating gate is Main `30% / -25%`, Concentrated `50% / -28%`.
- Do not rewrite official mission targets without explicit user approval.
- Bull-floor run `27516185696` is a partial pass and evidence input only:
  strengthened gates still fail.

## Forbidden Shortcuts

- Do not whole-merge `origin/claude/analyze-updated-code-OfEbu`.
- Do not mark 7-year evidence as official 8-year evidence.
- Do not enable live trading.
- Do not mutate production target books from a verifier or queue closure result.
- Do not bypass dispatcher dependencies with hand-written workflow commands.
- Do not call a candidate promoted without verifier, system acceptance, OOS lock,
  attribution, and broker-ledger evidence.
