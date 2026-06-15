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
| Price/universe readiness | `audit_data_readiness.py` now runs before account evaluation in `run_full_rebuild_sidecars.py`; failed readiness makes official verdict invalid | wired |
| ADR automation | `run_adr_candidate_scanner.py` plus monthly workflow generate review-only candidate artifacts | review-only wired |
| Era leadership | `run_era_leadership_sidecar.py` computes era/regime factor IC and top-name contribution for 2019-2021, 2022, 2023-2024, 2025+ | sidecar wired |
| Crisis action wire | `run_daily_crisis_monitor.py` still has `auto_trade_allowed=false`, but emits paper candidates from a strict action whitelist | paper-only wired |
| Self-correction | `run_self_correction_router.py` queues A/B candidates and emits review-ready workflow_dispatch payloads/commands when a ledger leak repeats 2 runs | dispatch-prep wired |
| Full rebuild persistence | `is_attribution`, `era_leadership`, `self_correction_router`, `data_readiness`, and account evaluation are preserved under `cloud_results/full_rebuild/<date>` | wired |

## Not Yet Complete

| Gap | Why it matters for true 8-year CAGR/MDD | Next code or ops action |
| --- | --- | --- |
| 8-year data extension is not proven | The gate rejects short runs, but it does not create missing 2018-era price/universe/cache history by itself | Extend collectors and replay cache/universe to at least mid-2018, then dispatch a full rebuild that passes the new gate |
| Era leadership is diagnostic, not a production model | Production still uses one global model plus post-hoc sidecars; it does not train separate era/regime coefficients | Add an era-aware scoring challenger, then A/B with broker-ledger next-close |
| ADR automation is candidate-only | It finds additions but does not safely merge universe changes | Add an operator-reviewed manifest diff or PR generator for `adr_universe.yaml` |
| Crisis actions are paper-only | This is correct for safety, but paper/live executors do not consume the structured candidates yet | Add a paper executor bridge that writes approval-required order previews |
| Self-correction does not dispatch automatically | Router writes queue and dispatch payload artifacts, but does not call workflow_dispatch by itself | Add a guarded dispatcher that requires user approval before launching A/B |
| Concentrated CAGR still lacks proof of 50% | Latest known headline was 44.43% and IS-CAGR was near 22%; PR64 makes evidence stricter, not higher | Run queued concentrated bull experiments and promote only if IS-CAGR improves and MDD remains within -28% |

## Operational Interpretation

PR64 turns the previous optimistic loop into a stricter evidence loop. After it
merges, a 7-year run that looks good can no longer be called official. The next
milestone is a full broker-ledger rebuild with actual 8-year equity-curve
coverage, ready price/universe data, era/year attribution, and self-correction
queue artifacts.
