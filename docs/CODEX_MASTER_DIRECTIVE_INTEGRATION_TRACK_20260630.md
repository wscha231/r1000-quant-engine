# Codex Master Directive — Integration Track: state, ordered actions, acceptance gates

> Author: Claude Code (web), 2026-06-30 16:05 KST. Single entry point for the integration track.
> Branch of record: `codex/integration-main-conc-target-hooks-20260629` (PR #212) and the review branch
> `claude/pr146-review-analysis-6dkvd8` (PR #213 + work-order docs).
> Companion docs (already committed, read when you reach that step):
> - `docs/CODEX_DIRECTIVE_CASH_CARRY_ACCOUNTING_20260629.md`
> - `docs/CODEX_WORK_ORDER_CONC_CAGR_BULL_FLOOR_20260629.md`
> - `docs/CODEX_MEASUREMENT_PROTOCOL.md`

---

## 0. TL;DR

Run **28360773460** is a **completed full 7Y rebuild** (Pipeline OK, 198 min), not a crash — its GitHub
"failure" was a post-pipeline `--strict` preflight exit. Headline broker-ledger result:
**Main 35.28% / −24.25% (both canonical targets met)**, **Concentrated 46.66% / −24.12% (MDD met, CAGR −3.34pp
short)** → **PARTIAL**. The next integration fullrun is **blocked by a real data-readiness guard**: the
fast-crash hedge ticker **`SH` is missing from the price cache**. Fix the collection path, do NOT dispatch a
fullrun until `fullrun_readiness=true`. Concentrated CAGR remains the single unsolved alpha gap; production
stays blocked by `pit_universe_label_clean=false` regardless of metrics.

---

## 1. Current state (verified)

- **Result evidence (latest_full_rebuild_broker, run 28360773460):**
  - Main: CAGR 35.28% / MaxDD −24.25% / Sharpe 1.268 — canonical 35% / −25% both met (headline only).
  - Concentrated: CAGR 46.66% / MaxDD −24.12% / Sharpe 1.401 — MaxDD met; CAGR **−3.34pp** short of 50%.
  - Window 2019-06-03 → 2026-06-26, 7.064y; overall **PARTIAL**.
- **Why the GitHub job read "failure":** the full pipeline completed; the step's non-zero came from the
  separate post-book `tools/run_clean7y_window_preflight.py --strict`. Its `status.json` was not persisted →
  exact blocker unrecoverable (fixed by P2 below).
- **Account-eval window gate bug (fixed in PR #213):** the 7.064y window — anchored exactly at the official
  2019-06-03 start (drift 0) — was wrongly stamped `invalid_window` because the proxy-8Y/10Y block keyed on
  `years > 7.05`. PR #213 re-keys it on *broker start earlier than official* → anchored overshoot is `valid_7y`.
- **Current hard blocker (new readiness guard, PR #215):**
  `outputs/fullrun_readiness/summary.json` → `status=blocked`, `blockers=["missing_required_env_price_tickers"]`,
  `missing_required_price_tickers=["SH"]`, `required_price_tickers=["QQQ","SH","SPY"]`. `SH` (ProShares Short
  S&P500, the fast-crash hedge instrument) is audited as required but not collected.
- **Free proxy replay (DIAGNOSTIC ONLY, never acceptance):** Main 23.09% / −30.50%, Conc 36.89% / −41.75%.
  The large divergence from the broker ledger (Conc MaxDD −41.75 vs −24.12) is itself a proxy-unreliability
  flag. Do not cite it as evidence.
- **Standing production blocker:** `pit_universe_label_clean=false` → `production_promotion_allowed=false`.

---

## 2. Review verdicts (the SH / readiness questions)

1. **PR #215 block when hedge ON but SH missing — CORRECT.** Without SH the hedge silently no-ops → false MDD
   evidence (a wiring no-op masquerading as "hedge didn't help"). Fail-fast at readiness is right. The block
   must be conditional on the hedge flag being enabled (SH not required when hedge OFF).
2. **Fix belongs in COLLECTION, not audit.** Audit worked (it caught the gap). Collection only fetches
   book/universe tickers; it must also fetch env-required extra tickers.
3. **YES — derive required env tickers from enabled flags via a SHARED helper (this is the root fix, not
   optional).** The drift (audit requires SH, collection doesn't) recurs on the next hedge/overlay ticker
   unless one source of truth feeds collection + audit + readiness.
4. **SH blocking vs PAGS non-blocking — CORRECT asymmetry.** SH is a functional dependency of an enabled
   feature → hard block. PAGS is one missing universe candidate → graceful skip, still bounded by the
   coverage floor (<400 = INVALID_UNIVERSE) guard.
5. **Cash-carry (#214) — KEEP SEPARATE from the integration fullrun.** Bundling confounds the measurement and
   changes the acceptance metric; the data contract doesn't yet define cash-yield. Integration run stays
   `cash_carry_mode=none`; cash-carry is an isolated research replay (P5).
6. **Concentrated CAGR remains THE gap.** Main is headline-SHIP → freeze/protect, don't add. Caveat: part of
   the Conc gap may be the cash-zero-yield artifact → path is carry-measure first, then bull-floor.
7. **YES — no fullrun until `fullrun_readiness=true` with SH present AND fresh AND 7Y-covering.** A
   present-but-stale or missing SH = false hedge evidence.

---

## 3. Ordered execution plan (gates between steps — do not skip ahead)

### P0 — SH data-readiness fix (CURRENT BLOCKER, do first)
- Add a shared helper, e.g. `required_env_price_tickers(enabled_flags) -> set[str]`, mapping enabled
  experiment flags → required tickers (`PHASE_MAIN_FAST_CRASH_HEDGE_ENABLED → {"SH"}`, plus the always-on
  benchmark set `{"SPY","QQQ"}`). Single source of truth.
- Consume it in ALL THREE layers: price **collection/refresh**, freshness **audit**, **readiness** summary.
- Smoke test reproducing the failure: audit requires `SH` + book universe lacks `SH` ⇒ collection MUST request
  `SH`; readiness blocks until present+fresh.
- Re-run `free_data_daily_update.yml` on the codex branch; inspect `outputs/fullrun_readiness/summary.json`.
- **Gate:** proceed only when `fullrun_ready=true`, `SH` present, **fresh**, and covers the full 7Y window
  (SH is a 2006- ETF → history is sufficient; verify, don't assume).

### P1 — Merge PR #213 (window gate overshoot + machine-readable classification)
- Confirm CI green + `tests/account_evaluation_window_gate_smoke.py` passes; merge.
- Effect: the next fullrun's anchored 7.06y window is judged `valid_7y`, not `invalid_window`.
- Note: this does NOT by itself fix preflight observability (P2) — they are separate.

### P2 — clean7y preflight observability
- Copy `outputs/clean7y_window_preflight/{status.json,report.md}` and
  `outputs/full_rebuild_logs/clean7y_window_preflight.log` into BOTH the uploaded artifact and `cloud_results`.
- Make the run summary distinguish failure causes:
  `pipeline_completed`, `post_preflight_failed`, `account_eval_window_classification`,
  `production_promotion_blocked`, `artifact_upload_failed`. Never again lose the post-preflight blocker.

### P3 — Main freeze / non-regression guard
- Main is headline target-pass (35.28% / −24.25%). Stop adding Main MDD-repair hooks.
- Every Concentrated-focused lever must report Main ΔCAGR / ΔMaxDD / ΔSharpe / turnover and **reject on
  material Main regression** (guideline: Main ΔCAGR ≥ −0.25pp, ΔMaxDD ≥ −0.25pp, ΔSharpe ≥ −0.03).

### P4 — ONE integration fullrun (only after P0 readiness=true; cash_carry_mode=none)
- Dispatch exactly one fullrun on the codex integration branch with the three hooks
  (`PHASE_AI_CAPEX_MOMENTUM_TILT_ENABLED`, `PHASE_MAIN_FAST_CRASH_HEDGE_ENABLED`,
  `PHASE_CONCENTRATED_CASHFUNDED_EARLY_ENTRY_ENABLED`).
- Verify, from `account_evaluation/official_metrics.json` + `verdict.log`:
  - hedge **actually fired** (`applied>0`, ≥1 fire date) — *present ≠ used*;
  - cash-funded early entry `applied>0`;
  - Main non-regress; Concentrated CAGR/MaxDD;
  - `window_classification=valid_7y` (post-P1); `pit_universe_label_clean=false` still recorded.
- This reproduces the 28360773460 PARTIAL on a clean valid window (research evidence, not promotion).

### P5 — Cash-carry research replay (SEPARATE, isolated; NOT in P4)
- Per `docs/CODEX_DIRECTIVE_CASH_CARRY_ACCOUNTING_20260629.md`: default OFF; add `"dgs3mo":"DGS3MO"` to
  `MACRO_FRED_SERIES` (reuse `load_fred_series`); **ACT/365 calendar-day** accrual; rate is percent (/100);
  PIT (`available_from = rate_date + 1 business day`, forward-fill from past only); guard negative cash.
- Measure on the SAME artifact, both arms under the same mode; label `metric_mode=
  broker_ledger_next_close_cash_carry`; keep the zero-yield number side-by-side.
- Report Main/Conc CAGR·MaxDD·Sharpe before→after, accrued interest, avg_cash, and **tier-2 `is_cagr_min` /
  `oos_is_cagr_ratio` before→after** (carry should lift IS CAGR and help the overfit gate).
- Do NOT fold into official acceptance until `ALPHAOPS_DATA_SYSTEM_CONTRACT.md` explicitly defines cash-yield
  treatment (separate decision-maker approval).

### P6 — Concentrated CAGR gap: bull-floor A/B on the cash-carry baseline
- Per `docs/CODEX_WORK_ORDER_CONC_CAGR_BULL_FLOOR_20260629.md`. Replay-stage one-flag A/B
  (`PHASE_REGIME_CAPACITY_BULL_FLOOR_ENABLED=1`, conc floor 0.85 → sweep 0.90 / 0.95), no full rebuild for the
  cheap A/B.
- Compare **cash-carry baseline vs cash-carry bull-floor** (never zero-yield vs cash-carry).
- No-op proof: `rebalance_dates_bull_floor_lifted>0` + Conc `avg_cash` drops. Gate-first
  (MaxDD ≥ −25 AND CAGR ≥ 50 first, then rank). **Overfit guard mandatory:** reject if the gain is confined
  to 2025 OOS or a single name (LITE); require ≥2 bull eras + OOS fold; OOS/IS not worse than the 46.66%
  baseline's 4.92x.

### P7 — Fallback if bull-floor insufficient: selection layer
- AI Capex bottleneck boost / EPS-revision & guidance confirmation / late `target_exit` loser reduction.
- Uploaded research is design-input only (taxonomy/regime), not ex-ante stock picks; PIT + walk-forward.

---

## 4. Acceptance criteria (what Claude will verdict)

- **P0:** readiness=true, SH present/fresh/7Y, shared helper drives all three layers, smoke reproduces+passes.
- **P4 fullrun:** hedge `applied>0` with real fire dates; cash-funded early `applied>0`; Main non-regress;
  `window_classification=valid_7y`; `pit_universe_label_clean=false`; broker-ledger is the only metric cited.
- **P5 cash-carry:** default-OFF preserves EXACT prior metrics; accrues over calendar days (weekend credited);
  no future rate (PIT); both arms same mode; reported as accounting correction, not alpha delta.
- **P6 bull-floor:** ship gate ΔCAGR ≥ +0.5pp toward 50 AND final MaxDD ≥ −25 AND ΔSharpe ≥ −0.05 AND Main
  non-regress AND theme_leader_capture non-regress AND early_scout ≥ 4 AND multi-era/OOS robustness.
- **Global:** cheap replay never accepted as final — reproduce on a full rebuild before any "achieved" claim.

---

## 5. Non-negotiables

- No production promotion. No live trading. No fullrun while readiness is blocked.
- No proxy 8Y/10Y work. Free/cheap proxy replay is diagnostic only — never production evidence.
- No partial-year 2026 annualized CAGR as proof.
- No forward returns in live ranking or historical ex-ante selection. PIT only; walk-forward + 126d embargo.
- New env-required tickers default OFF unless their feature flag is enabled; new levers env-gated default OFF.
- Acceptance metric = `broker_ledger_next_close` only. Cash-carry stays research-mode until the contract
  defines it.
- `pit_universe_label_clean=false` remains a production blocker until the membership PIT audit passes.

---

## 6. Document / branch index

| Item | Where | Status |
|---|---|---|
| Window gate overshoot + classification fix | PR #213 (`claude/pr146-review-analysis-6dkvd8`) | open/draft, CI |
| Cash-carry accounting directive | `docs/CODEX_DIRECTIVE_CASH_CARRY_ACCOUNTING_20260629.md` | committed |
| Concentrated bull-floor work order | `docs/CODEX_WORK_ORDER_CONC_CAGR_BULL_FLOOR_20260629.md` | committed |
| Measurement & acceptance protocol | `docs/CODEX_MEASUREMENT_PROTOCOL.md` | committed |
| This master directive | `docs/CODEX_MASTER_DIRECTIVE_INTEGRATION_TRACK_20260630.md` | committed |
| Integration hooks + result | run 28360773460, branch `codex/integration-main-conc-target-hooks-20260629` (PR #212) | PARTIAL |
