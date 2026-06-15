# PR64 System Status - Integrated Evaluation Control Loop

Branch/PR: `codex/self-sustaining-loop-20260615`, PR #64.

This note updates the older `SYSTEM_INTEGRATION_ANALYSIS_20260615.md` with the
current PR state. It is intentionally ASCII-only so future agents can read it
without encoding loss.

## Target Contract Status

PR64 currently uses an interim operating gate in code:

| Contract | Main | Concentrated | Status |
| --- | --- | --- | --- |
| Canonical mission (`CLAUDE.md`) | 35% CAGR / -25% MaxDD | 50% CAGR / -25% MaxDD | final mission target until the user explicitly changes it |
| PR64 interim operating gate (`PORTFOLIO_GOAL_TARGETS`) | 30% CAGR / -25% MaxDD | 50% CAGR / -28% MaxDD | evidence-control gate only; unresolved user decision |

Rule: do not treat the interim gate as a mission rewrite. No official gate,
handoff, or goals proposal may claim the mission target changed until the user
approves that change explicitly. The strengthened IS/OOS gates and 8-year
broker-ledger window remain promotion blockers under both contracts.

`tools/run_account_evaluation.py` now emits this distinction as machine-readable
metadata: `target_type=interim_operating_gate`,
`target_contract_status=unresolved_user_decision_required`, active gate targets,
and canonical mission targets. This keeps `target_pass` math unchanged while
making the target contract visible in `official_metrics.json`,
`account_evaluation_summary.json`, the CSV, and the report.

## Wired In PR64

| Requirement | Current implementation | Status |
| --- | --- | --- |
| Main target contract | `PORTFOLIO_GOAL_TARGETS["main"] = 30% CAGR / -25% MaxDD` | wired |
| Concentrated target contract | `PORTFOLIO_GOAL_TARGETS["concentrated"] = 50% CAGR / -28% MaxDD` | wired |
| Anti-OOS-lottery gate | Tier-2 IS-CAGR / OOS-IS ratio / Sharpe / cash / recent-MDD gates remain active | wired |
| OOS holdout lock | `run_oos_lock_audit.py` recomputes locked IS/OOS broker-ledger windows from equity curves using `research/oos_lock.yaml`; `run_system_acceptance_audit.py` hard-blocks official evidence if the lock artifact is missing or fails | hard-gated |
| 8-year broker-ledger gate | `run_account_evaluation.py` requires 8.0 years, >=2016 actual equity-curve trading days, and data-readiness evidence | wired |
| 8-year readiness artifact | `check_10y_backtest_readiness.py --min-years 8` writes `outputs/eight_year_backtest_readiness/` with price, target-book, broker-ledger window blockers, review-only bootstrap/rebuild dispatch payloads, and a machine-readable `data_extension_plan`/task CSV for the exact missing window | wired |
| Price/universe readiness | `audit_data_readiness.py` now runs before account evaluation in `run_full_rebuild_sidecars.py`; failed readiness makes official verdict invalid | wired |
| Cash contract realism | `validate_target_book_cash_contract.py` validates explicit CASH rows and broker cash-ledger drift; `run_system_acceptance_audit.py` now hard-blocks official evidence when this contract is missing or failing | hard-gated |
| Attribution package | `run_system_acceptance_audit.py` now hard-blocks official evidence unless IS/year leak attribution, era top-name contribution, trade MDD per-name attribution, and MDD trough holdings are all present | hard-gated |
| ADR automation | `run_adr_candidate_scanner.py` runs in full rebuild sidecars and in the monthly workflow to generate review-only candidate CSV/Markdown, JSON update manifest, and YAML addition fragment; `apply_adr_universe_update.py` can apply a fully reviewed manifest with explicit approval and placeholder checks | guarded apply wired |
| Era leadership | `run_era_leadership_sidecar.py` computes era/regime factor IC and top-name contribution for 2019-2021, 2022, 2023-2024, 2025+ | diagnostic wired |
| Era-aware scoring challenger | `run_era_aware_scoring_challenger.py` converts era buckets into review-only broker-replayable target books under `outputs/era_aware_scoring_challenger/`, runs optional broker replay, writes goal-contract verdicts, and emits a disabled `era_aware_approved_target_policy_candidate.json` template for human review without replacing operating books | review challenger wired |
| Crisis action wire | `run_daily_crisis_monitor.py` emits whitelisted paper candidates and `run_crisis_paper_order_bridge.py` turns them into approval-required paper order previews; `run_system_acceptance_audit.py` hard-blocks unknown crisis action types and any portfolio preview that is not paper-only/user-approved | paper-order bridge hard-gated |
| Operational order bridge | `run_account_order_preview.py`, `run_live_trading_safety_audit.py`, and `run_live_trading_risk_controls.py` connect operating target books to sell-first/buy-second paper order manifests; `run_system_acceptance_audit.py` now blocks production evidence if this path is missing or unsafe | hard-gated |
| Self-correction | `run_self_correction_router.py` queues A/B candidates and emits review-ready workflow_dispatch payloads/commands when a ledger leak repeats 2 runs; bull underinvestment maps to exposure experiments, flat alpha maps to era-aware challenger review, and OOS lock failures map to manual robustness review tasks with no workflow dispatch; router payloads now require the official 8-year rebuild plan unless the latest run already has an `official_eight_year_ready` readiness artifact, and dependency-blocked shell commands are commented out; full rebuilds run `run_review_dispatcher.py` dry-runs for both `outputs/self_correction_router/workflow_dispatch_payloads.json` and `outputs/system_acceptance_audit/workflow_dispatch_payloads.json`; system acceptance now verifies the self-correction dispatcher summary stayed dry-run, dispatched zero workflows, and selected the same payload ids | guarded dispatch wired |
| A/B result verifier | `run_ab_result_verifier.py` compares completed Concentrated recovery A/B runs against a baseline, requires broker-ledger next-close, 8-year validity, target + strengthened gate pass, direct OOS lock pass, attribution/system-acceptance evidence, carries optional queue-closure metadata (`experiment_id`, `payload_hash`, `workflow_run_id`, `dispatch_run_id`), and keeps `production_activation_allowed=false` | review verifier wired |
| Self-correction queue closure | `run_self_correction_queue_closure.py` joins router queue artifacts with verifier summaries, maps `promote_candidate_review_only` to `ready_for_human_review`, rejection/invalid decisions to `rejected`, blocked evidence to `measured` with follow-up required, and writes `outputs/self_correction_queue/{summary.json,queue_state.jsonl,deduped_queue.json,stale_payloads.json,closure_report.md}` without dispatching workflows or mutating production | review closure wired |
| System acceptance audit | `run_system_acceptance_audit.py` aggregates official metrics, OOS holdout lock, 8-year readiness, data readiness, broker realism, cash contract, attribution package, era challenger, crisis bridge, self-correction, ADR automation, and guard evidence into one PASS/FAIL/WARN matrix; it also emits review-only workflow dispatch plans for 8-year bootstrap/rebuild and Concentrated recovery A/B when those blockers are present, plus `manual_review_tasks.json` for OOS robustness tasks that must not dispatch workflows | wired |
| Full rebuild persistence | `oos_lock`, `eight_year_backtest_readiness`, `cash_contract`, `mdd_cash_overlay_research`, `is_attribution`, `era_leadership`, `trade_attribution`, `era_aware_scoring_challenger`, `self_correction_router`, `system_acceptance_audit`, `review_dispatcher`, `review_dispatcher_self_correction`, `data_readiness`, `adr_candidates`, and account evaluation are preserved under `cloud_results/full_rebuild/<date>` | wired |

## Not Yet Complete

| Gap | Why it matters for true 8-year CAGR/MDD | Next code or ops action |
| --- | --- | --- |
| 8-year data extension is not proven | The gate rejects short runs and the readiness artifact now emits a concrete extension plan. Applied to current `latest_global_alpha_universe`, it requires target start `2018-06-12`, 417 selected target-book price tickers, target books currently start `2019-05-31`, and broker replay currently starts `2019-06-03` | Run the generated bootstrap payload, then the 8-year full rebuild payload; do not treat any run as official until `data_extension_plan.hard_blocker_count == 0` and account evaluation passes the 8-year window gate |
| OOS lock must be re-proven on the next full run | Historical broker metrics had IS/OOS windows, but older published runs do not have the standalone `outputs/oos_lock` artifact now required by system acceptance. Backfilling the current `latest_global_alpha_universe` flags the same robustness issue: Main OOS/IS `3.34x`, Concentrated `5.97x`, both above the `3.0x` lock | Let the next official rebuild generate `outputs/oos_lock/oos_report.json`; any missing or failed lock keeps the run non-promotable |
| Era-aware scoring is not promoted | The challenger now emits broker-replayable books plus a disabled promotion policy candidate, but production still uses the existing AlphaOps vNext operating books until an A/B proves IS-CAGR improvement and a human enables the policy | Run the challenger on an 8-year-ready rebuild, inspect `era_aware_approved_target_policy_candidate.json`, then approve only portfolios with strengthened broker-ledger pass and exact target-book SHA |
| ADR automation still requires reviewed metadata | It now creates candidate artifacts and a guarded apply path, but placeholder scanner output is intentionally blocked until name/country/sector/listed_since/themes are filled | Review the ADR manifest, run the updater dry-run, then apply on a branch with approval and PR review |
| Live execution is intentionally absent | This is correct for safety; order previews, safety audit, and risk controls are hard-gated, but no tool submits broker orders | Add a live executor only after paper-mode evidence and explicit user approval |
| Self-correction dispatch still requires approval | Router and system audit write queue artifacts, `run_review_dispatcher.py` can launch selected workflow_dispatch payloads only with explicit approval token, and queue closure can only move measured candidates to review states | Use dispatcher dry-run first, execute selected payloads after reviewing dependencies and run cost, then close the queue with `tools/run_self_correction_queue_closure.py` against the completed verifier summary |
| Concentrated CAGR still lacks proof of 50% | Latest known headline was 44.43% and IS-CAGR was near 22%; PR64 makes evidence stricter, not higher | Run the generated `system_acceptance_audit` Concentrated recovery A/B payloads, then run `tools/run_ab_result_verifier.py` against each completed candidate; promote only if the verifier returns `promote_candidate_review_only` and a human approves a separate PR |

## Operational Interpretation

PR64 turns the previous optimistic loop into a stricter evidence loop. After it
merges, a 7-year run that looks good can no longer be called official. The next
milestone is a full broker-ledger rebuild with actual 8-year equity-curve
coverage, ready price/universe data, era/year attribution, and self-correction
queue artifacts.
