# Codex Work Order — concrete levers that move CAGR/MDD under strict measurement

> Role split: this doc is the **solution + work instruction** (ChatGPT-Pro / Claude review
> side). Codex implements and measures. Companions: `docs/CODEX_MEASUREMENT_PROTOCOL.md`
> (the proof bar — read it; every claim here must clear it; **it lands via PR #162 — merge #162
> before relying on this work order**), `docs/CODEX_RESEARCH_LEADER_CAPTURE.md`,
> `docs/CODEX_DIRECTIVE_CAGR_MDD_ROADMAP.md`, `CLAUDE.md`.
>
> GOAL: produce a **real** CAGR/MDD improvement that survives the strictest measurement
> (`broker_ledger_next_close`, full account ledger, valid window, walk-forward) — not a proxy gain.

---

## 0. Targets, gaps, proof bar

| Sleeve | Target | Current (research) | Gap | Owner lever(s) |
|---|---|---|---|---|
| Main | CAGR ≥35% / MDD ≥−25% | 35.0% / −26.0% | **MDD −1.0pp** | IV (trailing), II/III (faster cut) |
| Concentrated | CAGR ≥50% / MDD ≥−25% | 46.0% / −24.6% | **CAGR +4.0pp** | **I (gross floor)**, II/III (hold winners) |

Proof bar (per `CODEX_MEASUREMENT_PROTOCOL.md`): a lever ships only if, on
`broker_replay/<kind>/metrics.json` over a valid window, with `applied>0`, it moves its gap the
right way without breaking the other sleeve, `theme_leader_capture` non-regress, and the gain
holds out-of-sample. Proxies (PRWV/weight-level/overlay) screen only; the broker ledger accepts.

---

## 1. The solution — 4 concrete levers (code-anchored), ranked by expected impact

### Lever I — Regime-conditional gross floor  ★ biggest Concentrated CAGR lever
- **Why**: Concentrated holds ~21% idle cash in GREEN (`cash_reentry_quality`: green_avg_cash
  0.213, `cash_drag_vs_baseline −6.0pp`). MDD already passes (−24.6, 0.4pp headroom). Deploying
  the GREEN idle cash is the single largest recoverable CAGR source — exactly Concentrated's gap.
- **Code anchor**: gross exposure is set in `apply_vnext_benchmark_guard`
  (`tools/run_alphaops_vnext_policy_replay.py:812`) → `apply_benchmark_risk_overlay`
  (`r1000_market_leader_engine`), env knob **`R1000_CONC_GROSS_CAP_FLOOR`** (already swept by
  `tools/run_lever_sweep.py`). The regime label is available per record: `rec["crisis_state"]`
  (see `apply_concentrated_risk_state_new_entry_cap` line ~847).
- **Mechanism (PIT)**: raise the gross floor **only** when `crisis_state == "GREEN"` AND a
  PIT breadth-strong condition (e.g. market breadth above ma200 ≥ threshold). In
  `WATCH/DEFENSE_REVIEW/CRISIS_*` keep the current gross cut — **the 2022 defensive cash MUST be
  byte-for-byte unchanged** (verify: 2022 concentrated avg cash stays ≈79.8%).
- **env**: `PHASE_REGIME_GROSS_FLOOR_ENABLED` (default OFF) + `R1000_CONC_GROSS_CAP_FLOOR`.
  NOTE: `run_lever_sweep.py` today injects only `R1000_CONC_GROSS_CAP_FLOOR`
  (`tools/run_lever_sweep.py:234`). With the new phase gate, the sweep (or the command) MUST also
  set `PHASE_REGIME_GROSS_FLOOR_ENABLED=1`, or every non-control arm is a no-op — update the
  harness to inject it before sweeping.
- **Expected**: Concentrated CAGR +1~3pp; ΔMaxDD small (GREEN-only exposure, bounded by the
  0.4pp headroom).
- **Strict A/B (two stages)**: (1) SCREEN — `run_lever_sweep.py` conc-gross grid `{0.0,0.7,0.8,0.9}`
  with the GREEN gate ON → per-arm broker metrics to shortlist; **gate-first** (MDD ≥ −25 AND
  CAGR ≥ 0.50). (2) ACCEPT — the sweep does NOT emit `account_evaluation/official_metrics.json`,
  so re-measure the shortlisted arm in a run that DOES (full sidecar/fullrun) and confirm the
  window/leakage gates there. Pass (on the accept run): Conc ΔCAGR ≥ +1.0pp AND ΔMaxDD ≥ −1pp AND
  2022 cash unchanged.

### Lever II — SHAKEOUT_GUARD (A1) — measure once PR #161 is merged
- **env**: `PHASE_SHAKEOUT_GUARD_PROD_ENABLED=1` — the toggle is WIRED by PR #161
  (`holding_state` / `shakeout_guard_prod_enabled`). **Confirm PR #161 is merged to master before
  the A/B**; on a tree without it the flag is doc-only and the treatment is unchanged (no-op).
- **Strict A/B (lean v1)**: ONE config. **First prove `shakeout_guard_prod_applied=True` rows > 0**
  (no-op risk: requires `leader_tier ∈ {DUAL_LEADER, SECTOR_LEADER}` (exact values — not `DUAL`/`SECTOR`),
  `sector_leadership_score>0`,
  `smart_money_evidence_confidence ≥ 0.25` populated on replay rows). Then on broker ledger:
  premature_sell / EXIT_REPLACE 126d excess ↓ (`entry_exit_timing_audit/`), `pct_held_365d_plus`
  ↑, ΔCAGR ≥ +0.5pp, ΔMaxDD ≥ −3pp, `theme_leader_capture` non-regress. Keep persistence-hold OFF
  to isolate.

### Lever III — Earnings state gate (A2): hold earnings-strong, cut earnings-broken
- **Why**: `eps_revision_score`, `phase9_c3_eps_turn_positive`, `ni_loss_narrowing_4q`, and the
  consecutive-negative-`revision_score` streak feed SCORE only — not the hold/exit STATE. So we
  TRIM earnings-strong leaders and keep earnings-broken ones.
- **Code anchor**: `holding_state(...)` in `tools/run_alphaops_vnext_policy_replay.py`. Mirror the
  A1 wiring pattern:
  - hold-extend: strong `eps_revision_score`>0 / `phase9_c3_eps_turn_positive` / `ni_loss_narrowing_4q`
    → suppress a transient TRIM/WARNING for one cycle (like SHAKEOUT, but earnings-driven).
  - exit-accelerate: negative-revision streak ≥ N → escalate WARNING→EXIT one cycle earlier.
- **PIT precondition**: confirm these columns actually carry onto the vNext prior-holding row
  (they are computed upstream in `r1000_pipeline.py` for scoring; if not present on the replay row,
  the gate is a NO-OP — add them to the carry-through and prove `applied>0`). SEC-accepted-timestamp
  PIT, `available_from ≤ t`.
- **env**: `PHASE_EARNINGS_STATE_GATE_ENABLED` (default OFF).
- **Expected**: CAGR (hold winners through earnings) + MDD (cut deteriorating earnings faster).

### Lever IV — Main trailing stop (Main MDD −1pp)
- **Code anchor**: `tools/run_broker_position_risk_grid_sweep.py` (PR #158, **account ledger** —
  not the PRWV proxy). Wide-trailing grid already wired.
- **Strict measurement**: gate-first champion (MDD ≥ −25 AND CAGR ≥ 0.35); firing evidence is
  `risk_exit_count` in the broker replay artifacts (this is a replay-stage lever — it does NOT
  write a target-book `applied` column). Robustness bar: **total exits > 2 AND benefit active in
  ≥2 stress eras** (do NOT require an exit in every era — quiet bull eras may have 0). The −35%
  champion fired only 2× in 7y → treat as thin until this bar + OOS hold. Pass: Main MaxDD ≥ −25
  AND ΔCAGR ≥ −0.5pp.

---

## 2. Execution order & decision tree

1. **Lever II now** (coded): lean A/B. If `applied=0` → fix carry-through of leader_tier /
   smart_money_evidence_confidence first, do not interpret metrics.
2. **Lever I next** (biggest CAGR): implement the GREEN-gated gross floor; sweep + gate-first.
3. **Lever III**: earnings state gate (verify columns on row → `applied>0` → broker delta).
4. **Lever IV**: Main trailing via the broker-style grid; per-era robustness.
5. **Combine winners → ONE final-proof fullrun** (or research_7y_tolerance) on the broker ledger:
   Main ≥35/≥−25 AND Conc ≥50/≥−25 simultaneously, ship gate + generalization, leakage 0.
- After each lever, if it does not clear the proof bar, record the blocker and move on — do not
  keep grinding one lever. Concentrated CAGR is carried mostly by Lever I; Main MDD by II/III/IV.

## 3. How we know the gain is real (not a proxy)
- Accept only on `broker_replay/<kind>/metrics.json` + `account_evaluation/official_metrics.json`
  (valid window: gate emits `valid_7y` or machine-readable `research_7y_tolerance` — not a manual
  call; trading_days ≥1764 BOTH sleeves — fix the concentrated calendar-day count;
  `ready_for_policy_replay=true`; leakage 0). See `docs/CODEX_MEASUREMENT_PROTOCOL.md`.
- Firing proof before reading any delta — via the channel matching the lever: selection/state
  levers (I gate, II, III) → target-book `<lever>_applied>0`; replay-stage levers (IV trailing) →
  `risk_exit_count>0` in broker artifacts.
- Walk-forward OOS + per-era contribution (`trade_attribution/`); risk levers must not rest on
  1–2 events.
- `theme_leader_capture` must not regress (no buying CAGR/MDD by abandoning leader capture).
- Reminder: the PRWV proxy said −13% MDD; the broker ledger said −25%. Trust only the ledger.

## 4. Guardrails
PIT-only; env-gated default OFF; new feature columns → `build_feature_store.keep_cols` +
`hard_sanitize` + phase zero-placeholder (else silently 0.0); CI smoke in the same commit; no
live / production mutation / T3 / recovery / proxy 8Y-10Y; `pit_universe_label_clean=false` keeps
production promotion blocked (research baseline is the goal).

---

### TL;DR
Concentrated +4pp CAGR ≈ **Lever I (deploy GREEN idle cash via regime-gated gross floor)** +
hold-winners (II/III). Main −1pp MDD ≈ trailing (IV) + faster cut (II/III). Every lever: env-gated,
`applied>0`, measured on the **broker ledger**, OOS + capture-safe. 2022 defensive cash is sacred —
do not touch it. Proxy gains do not count.
