# Codex Execution Directive — 2026-07-03 (post run #239, all-engine synthesis)

> Synthesizes: `GOVERNANCE_DECISIONS_W0_20260702.md` (binding), GPT-Pro system-hardening review,
> `SUSTAINMENT_OPERATING_BLUEPRINT_20260703.md`, and fresh facts from fullrun **28616190134** (#239).
> The governance questions are RESOLVED — do not re-ask any engine. Execute.

## 0. New facts from run #239 (long-only, crash-inclusive, dispatched 2026-07-02)

- Artifacts VALID (`latest_global_alpha_universe` updated; dated dir `20260703_28616190134_...`); job itself
  ended `failure` at a post-artifact step → needs a 1-line postmortem (T8), not a blocker.
- **Broker verdict: Main REJECT 30.61% / −26.02% (both gates fail) · Concentrated PARTIAL 44.53% / −23.27%.**
- **⚠️ TRIPLE-CONFOUNDED — do NOT attribute the regression to long-only:** this run differs from #238 by
  (a) hedge OFF, (b) a NEW nondeterministic scored book (W1 unsolved), (c) the July semi/storage crash now
  INSIDE the window (fresh drawdown mechanically cuts CAGR and deepens MDD). Separating (a) requires T1.
- **The July rebalance answer to the crash (2026-07-02 book)** — the system did NOT freeze:
  - Concentrated: **BE fully exited** (21.5→0), **SNDK trimmed 39→27.8**, **WDC cut 20→7.1**, CIEN/LITE exited,
    **CASH tripled 6.2→16.8**, rotated into MU 30 / AMD 10.3 / UMC 8 (relative strength within the theme).
  - Main similarly rotated (FLEX/NXT/RKLB/HPE/QCOM entries; storage concentration reduced).
  - This is the process behaving as designed: exit thin-cushion names (BE), trim winners, raise cash, rotate —
    NOT panic-liquidation, NOT freezing. Record it as the first live crash-response evidence in the ledger.

## Binding decisions (already made — implement, never re-ask)
1. `broker_ledger_next_close_cash_carry` = official research baseline (DGS3MO, 1BD PIT lag, ACT/365, 50bps,
   max(cash,0)); zero-yield always side-by-side; production still blocked by `pit_universe_label_clean=false`.
2. MDD contract: canonical **−25% both sleeves**; remove interim −28% language; resolve
   `target_contract_status`.
3. Main policy: **long-only**; SH hedge → opt-in backlog (#211); Main MDD may not be quoted long-only until T1.

## Non-negotiables (unchanged)
No production promotion · no live trading · no fullrun until a replay-stage candidate passes AND user approves ·
no falsified-lever revival (bull-floor / broad hold-delay / cap-safe sizing) · no regenerated selection A/B
acceptance before W1 · no public display · current holdings = process outputs, not forward promises · all new
logic review-only, default OFF, backend artifacts only (Telegram/push deferred until deployment).

---

## Execution queue (strict order; WIP ≤ 2)

### T1 — Hedge-OFF fixed-book Main baseline replay [FIRST — #239 made this MORE urgent, not less]
`tools/run_main_hedge_off_baseline_replay.py`: take the **official #238 (28436307420) Main book**, zero the SH
rows (2 dates, max 7.5%), replay with `--replay-end-date 2026-06-29 --official-baseline-end-date 2026-06-29`,
BOTH zero-yield and cash-carry modes. Output `outputs/main_hedge_off_baseline/{metrics.json,report.md,
hedge_on_vs_off.csv}` with hedge_on/off CAGR·MDD deltas, `end_date_matches_official=true`,
`quote_long_only_allowed`. **This isolates (a) from #239's confounds.** If hedge-off MDD breaches −25 on the
SAME book → `status=governance_reopen_required` and surface the measured trade-off to the user.

### T2 — Contract updates (execute Decision 1+2)
Cash-yield section into the data contract (promote the draft); target-contract language → canonical 35/−25 and
50/−25, remove −28; `run_local.py` baseline notes → cash-carry numbers (pending T1 for Main). Re-baseline rule:
all future A/B under cash-carry mode, both arms.

### T3 — Snapshot hash idempotency: VERIFY (largely done in `4c54e630` "split forward service snapshot hashes")
Confirm: volatile fields (generated_at, local paths) excluded from hash inputs; `public_snapshot_hash` /
`target_snapshot_hash` / `broker_state_hash` separated; `snapshot_schema_version` present. Add
`tests/forward_service_snapshot_idempotency_smoke.py`: same fixture twice → identical hashes; holdings change →
broker_state_hash changes; generated_at change alone → public_snapshot_hash unchanged.

### T4 — Merges + P0 triage index
Merge **#217** (docs/planning history; W0/W7 docs are the active layer) and **#201** (negative evidence; body
already records the hedge divergence — now resolved by long-only). **#211 → closed/opt-in backlog.**
#208/#209 → `unproven_adjacent_to_falsified_cash_deployment`. Produce
`outputs/branch_triage_20260702/{open_pr_triage.csv,report.md}` with the agreed columns/classifications; no
automatic closes — user approval per the report.

### T5 — S1 sustainment wiring (backend-only; folds GPT-Pro's "daily risk engine + shock guard" into ONE tool)
`tools/run_alphaops_alarm_evaluator.py` + `tools/update_forward_service_ledger.py`:
- Inputs: latest_price_date_audit, coverage gate, daily snapshot, weekly evaluation, user_current, forward
  snapshot.
- Health metrics (daily ledger append): rolling 12m excess vs SPY-TR, DD-budget consumption, pick hit-rate,
  cluster HHI, signal→action lag, turnover/cash/position drift, freshness, (post-W1) book hash match.
- **Shock rules (config, REVIEW-only, from the GPT-Pro spec):** WATCH 1d≤−8% or 3d≤−12%; SHOCK_REVIEW 1d≤−12%
  or 3d≤−18% or gap≤−10% w/ vol z>2; TRIM_TO_CAP_REVIEW weight>25% AND shocked; EXIT_REVIEW thesis/trend break
  (dual-MA fail + 3m RS<0). **No auto-trades, ever** — outputs are `outputs/alerts/alerts_latest.json`,
  `outputs/alerts/UNRESOLVED_<date>.md` (2-trading-day human SLA), ledger rows, `outputs/system_health/summary.json`.
- Alarm levels 0–3 per the blueprint §2 (level changes = ledger rows; de-risk by ALLOCATION only).

### T6 — Weekly cron empty-input fix (T2-tier automation; previously deferred — now service-critical)
Schedule-event inputs default correctly (`fast_mode`→'true', `universe_mode`→'global_alpha_universe', etc.);
missing input → `blocked_missing_input` summary, never a crash; `system_health.weekly_evaluation_status` wired.

### T7 — W1 control-repro root cause (parallel with T1–T6)
Bisection: ① env parity FIRST (CatBoost `task_type` GPU/CPU — auto-select at `r1000_pipeline.py:9295` is
suspect #1; record task_type + lib versions + threads in run_manifest; repro mode forces CPU) → ② input
snapshot hashes (candidate/SEC-enriched/cache manifest/macro/append date) → ③ same-machine double run.
Acceptance (numeric, no "near zero"): 0/0/0 mismatch dates; `max_weight_delta_abs ≤ 1e-9`, or ≤ 0.001 only
with a documented floating-path exception. Until pass: regenerated selection A/B = diagnostic only.

### T8 — Run #239 postmortem + first live W3 evidence (cheap, high value)
- One paragraph: which step failed after valid artifacts (safety audit? preflight? wall-clock?) — feeds W5.
- **W3 counterfactual is now LIVE-measurable:** compare (i) June raw-scored rotation (AMD/AMAT/GLW), (ii) June
  operating book (held SNDK/BE/WDC through the crash), (iii) July-02 actual rotation — broker-replay all three
  through July. This answers "was hysteresis too sticky?" with real crash data, and quantifies the cost/benefit
  of the rotation latency. Output: `outputs/rotation_latency_counterfactual/report.md`.

### Deferred (do NOT start): EPS/guidance feed (W4), thesis-damage engine (needs W4 feed — the revision proxy is
an OOS counter-signal), AI-capex replacement hook, regenerated selection A/B, any fullrun (next fullrun only
after T1–T8 land + a candidate passes + user approves).

## Verdict gates (Claude will check)
T1: `end_date_matches_official=true`, hedge-off deltas isolated on the SAME book, long-only quote decision.
T5/T6: alarms fire on fixture shocks; cron survives empty inputs; ledger rows append-only with hashes.
T7: numeric acceptance met or a root-cause table naming the layer. T8: three-way counterfactual with broker
metrics, not narrative.
