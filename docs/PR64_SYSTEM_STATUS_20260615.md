# PR64 System Status - Integrated Evaluation Control Loop

Branch/PR: `codex/self-sustaining-loop-20260615`, PR #64.

This note updates the older `SYSTEM_INTEGRATION_ANALYSIS_20260615.md` with the
current PR state. It is intentionally ASCII-only so future agents can read it
without encoding loss.

## Wired In PR64

| Requirement | Current implementation | Status |
| --- | --- | --- |
| Main target contract | `PORTFOLIO_GOAL_TARGETS["main"] = 30% CAGR / -25% MaxDD` | wired |
| Concentrated target contract | `PORTFOLIO_GOAL_TARGETS["concentrated"] = 50% CAGR / -28% MaxDD` | wired |
| Anti-OOS-lottery gate | Tier-2 IS-CAGR / OOS-IS ratio / Sharpe / cash / recent-MDD gates remain active | wired |
| 8-year broker-ledger gate | `run_account_evaluation.py` requires 8.0 years, >=2016 actual equity-curve trading days, and data-readiness evidence | wired |
| 8-year readiness artifact | `check_10y_backtest_readiness.py --min-years 8` writes `outputs/eight_year_backtest_readiness/` with price, target-book, broker-ledger window blockers, and review-only bootstrap/rebuild dispatch payloads | wired |
| Price/universe readiness | `audit_data_readiness.py` now runs before account evaluation in `run_full_rebuild_sidecars.py`; failed readiness makes official verdict invalid | wired |
| Cash contract realism | `validate_target_book_cash_contract.py` validates explicit CASH rows and broker cash-ledger drift; `run_system_acceptance_audit.py` now hard-blocks official evidence when this contract is missing or failing | hard-gated |
| Attribution package | `run_system_acceptance_audit.py` now hard-blocks official evidence unless IS/year leak attribution, era top-name contribution, trade MDD per-name attribution, and MDD trough holdings are all present | hard-gated |
| ADR automation | `run_adr_candidate_scanner.py` plus monthly workflow generate review-only candidate CSV/Markdown, JSON update manifest, and YAML addition fragment; `apply_adr_universe_update.py` can apply a fully reviewed manifest with explicit approval and placeholder checks | guarded apply wired |
| Era leadership | `run_era_leadership_sidecar.py` computes era/regime factor IC and top-name contribution for 2019-2021, 2022, 2023-2024, 2025+ | diagnostic wired |
| Era-aware scoring challenger | `run_era_aware_scoring_challenger.py` converts era buckets into review-only broker-replayable target books under `outputs/era_aware_scoring_challenger/`, runs optional broker replay, and writes goal-contract verdicts without replacing operating books | review challenger wired |
| Crisis action wire | `run_daily_crisis_monitor.py` emits whitelisted paper candidates and `run_crisis_paper_order_bridge.py` turns them into approval-required paper order previews | paper-order bridge wired |
| Operational order bridge | `run_account_order_preview.py`, `run_live_trading_safety_audit.py`, and `run_live_trading_risk_controls.py` connect operating target books to sell-first/buy-second paper order manifests; `run_system_acceptance_audit.py` now blocks production evidence if this path is missing or unsafe | hard-gated |
| Self-correction | `run_self_correction_router.py` queues A/B candidates and emits review-ready workflow_dispatch payloads/commands when a ledger leak repeats 2 runs; bull underinvestment maps to exposure experiments, flat alpha maps to era-aware challenger review; `run_review_dispatcher.py` can dry-run or explicitly approved-dispatch those payloads while enforcing no production mutation | guarded dispatch wired |
| System acceptance audit | `run_system_acceptance_audit.py` aggregates official metrics, 8-year readiness, data readiness, broker realism, cash contract, attribution package, era challenger, crisis bridge, self-correction, ADR automation, and guard evidence into one PASS/FAIL/WARN matrix; it also emits review-only workflow dispatch plans for 8-year bootstrap/rebuild and Concentrated recovery A/B when those blockers are present | wired |
| Full rebuild persistence | `eight_year_backtest_readiness`, `cash_contract`, `mdd_cash_overlay_research`, `is_attribution`, `era_leadership`, `trade_attribution`, `era_aware_scoring_challenger`, `self_correction_router`, `system_acceptance_audit`, `data_readiness`, and account evaluation are preserved under `cloud_results/full_rebuild/<date>` | wired |

## Not Yet Complete

| Gap | Why it matters for true 8-year CAGR/MDD | Next code or ops action |
| --- | --- | --- |
| 8-year data extension is not proven | The gate rejects short runs and the readiness artifact will identify missing price/target-book/broker-ledger coverage, but it does not create missing 2018-era universe history by itself | Extend collectors and replay cache/universe to at least mid-2018, then dispatch a full rebuild that passes the new gate |
| Era-aware scoring is not promoted | The challenger now emits broker-replayable books, but production still uses the existing AlphaOps vNext operating books until an A/B proves IS-CAGR improvement | Dispatch an era-aware A/B against broker-ledger next-close and promote only if Tier-2 gates improve |
| ADR automation still requires reviewed metadata | It now creates candidate artifacts and a guarded apply path, but placeholder scanner output is intentionally blocked until name/country/sector/listed_since/themes are filled | Review the ADR manifest, run the updater dry-run, then apply on a branch with approval and PR review |
| Live execution is intentionally absent | This is correct for safety; order previews, safety audit, and risk controls are hard-gated, but no tool submits broker orders | Add a live executor only after paper-mode evidence and explicit user approval |
| Self-correction dispatch still requires approval | Router and system audit write queue artifacts, and `run_review_dispatcher.py` can launch selected workflow_dispatch payloads only with explicit approval token | Use dispatcher dry-run first, then execute selected payloads after reviewing dependencies and run cost |
| Concentrated CAGR still lacks proof of 50% | Latest known headline was 44.43% and IS-CAGR was near 22%; PR64 makes evidence stricter, not higher | Run the generated `system_acceptance_audit` Concentrated recovery A/B payloads and promote only if IS-CAGR improves and MDD remains within -28% |

## Operational Interpretation

PR64 turns the previous optimistic loop into a stricter evidence loop. After it
merges, a 7-year run that looks good can no longer be called official. The next
milestone is a full broker-ledger rebuild with actual 8-year equity-curve
coverage, ready price/universe data, era/year attribution, and self-correction
queue artifacts.
