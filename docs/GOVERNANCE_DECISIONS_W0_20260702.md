# W0 Governance Decisions — 2026-07-02 (user-approved)

> Recorded by Claude Code (web) from explicit user answers, 2026-07-02. These three decisions were the
> blocking gate (`target_contract_status="unresolved_user_decision_required"`) for the W0–W7 program in
> `docs/CODEX_SYSTEM_AUDIT_AND_MASTER_PLAN_20260702.md`. They are now RESOLVED and binding until the user
> explicitly revisits them.

## Decision 1 — Cash-carry: ADOPTED as the official research baseline
- `broker_ledger_next_close_cash_carry` (DGS3MO, 50 bps haircut, ACT/365, PIT available_from) is the
  **official research baseline** going forward.
- Conditions attached: zero-yield numbers stay reported side-by-side; every future A/B runs BOTH arms under
  the same cash-carry mode; `ALPHAOPS_DATA_SYSTEM_CONTRACT` gains an explicit cash-yield section (promote the
  draft `CODEX_CASH_CARRY_ACCOUNTING_CONTRACT_DRAFT_20260701.md`).
- Consequence: research-baseline metrics become **Main 35.11% / −23.99%** and **Concentrated 48.83% / −23.79%**
  (pending Decision 3 re-measurement for Main). Concentrated remaining mission gap: **+1.17pp CAGR**.
- Production promotion remains BLOCKED by `pit_universe_label_clean=false` regardless of this adoption.

## Decision 2 — Concentrated MDD contract: CANONICAL −25% KEPT
- The mission bar stays `max_dd >= -25%` for both sleeves. No interim −28% operating cap.
- Rationale: both sleeves currently measure inside −25 (−23.79 / −23.99 under cash-carry); relaxing gains
  nothing and duplicates standards.
- Action: resolve `target_contract_status` in `run_account_evaluation.py` / config — active gate = canonical
  mission (Main 35/−25, Conc 50/−25); remove the interim −28 gate language.

## Decision 3 — Main policy: LONG-ONLY CONFIRMED (SH hedge removed)
- Official policy is long-only. The fast-crash SH hedge is removed from the official path; #211 moves to
  closed/opt-in backlog; the hedge stays available only as explicitly reopened research.
- **Required artifact before quoting Main MDD as long-only:** fixed-official-book **hedge-OFF replay** —
  take the official 28436307420 Main target book, remove/zero the SH rows (2 fire dates, max 7.5%), re-run the
  broker ledger with identical end-clamp (2026-06-29), in BOTH zero-yield and cash-carry modes →
  `outputs/main_hedge_off_baseline/{metrics.json,report.md}` with deltas vs hedge-ON.
- Until that artifact exists, Main numbers are labeled `hedge_on_baseline_pending_long_only_remeasure`.
- If hedge-OFF Main MDD breaches −25%, this decision returns to the user with the measured trade-off.

## Immediate execution queue (Codex, in order)
1. **Hedge-OFF Main baseline replay** (Decision 3 artifact) — cheap, fixed-book, no fullrun.
2. **Contract updates**: cash-carry section into the data contract; target-contract resolution (Decision 2);
   re-baseline docs (`run_local.py` CURRENT_BASELINE notes) to cash-carry numbers once (1) lands.
3. **Merge #217 and #201** (both verified `mergeable_state=clean`; #201 body already records the hedge
   governance divergence — now resolved by Decision 3).
4. **Snapshot-hash idempotency fix** (content-addressed hash excluding volatile fields + `snapshot_schema_version`
   + regeneration-idempotency smoke) before the forward ledger consumes hashes.
5. Proceed with the sanctioned P0 (branch triage index) / P1 (control-repro root cause, GPU task_type first) /
   P3 (forward paper ledger seed) — unchanged.

## Unchanged non-negotiables
No production promotion (`pit_universe_label_clean=false`); no live trading; no fullrun until a replay-stage
candidate passes gates + user approval; falsified levers stay closed (bull-floor, broad hold-delay, cap-safe
sizing); forward returns audit-only; current holdings are process outputs, not a forward CAGR promise.
