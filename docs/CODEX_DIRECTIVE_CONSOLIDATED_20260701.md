# Codex Directive — Consolidated next steps (perfected)

> Author: Claude Code (web), 2026-07-01 10:11 KST. Merges the ChatGPT-Pro contract directive with
> code-verified corrections and the first MEASURED cash-carry number. This supersedes the loose parts of
> `docs/CODEX_MASTER_DIRECTIVE_INTEGRATION_TRACK_20260630.md` for sequencing.

## 0. Verified current state (important — read before acting)

Two things shipped since the last report; the system is further along than "nothing changed" suggests:
- **`#213` window-gate fix — MERGED.** Anchored 7.06y windows now classify `valid_7y` (confirmed live in run
  28436307420). ✅
- **`#214` research-only cash-carry accounting — MERGED and CORRECT.** Audited `run_broker_ledger_replay.py`:
  `DAY_COUNT=365` (ACT/365, not 252), `raw_rate_pct/100`, `max(state.cash,0)` negative guard, calendar-day
  accrual, DGS3MO via PIT `available_from = rate_date + BDay`, **default OFF** (`R1000_BROKER_CASH_CARRY_ENABLED`),
  smoke test present. This exactly matches the cash-carry directive — no rework needed. ✅

**Why CAGR/MDD look frozen across runs:** cash-carry is implemented but **never enabled in a run**, and the
runs only toggled replay-stage levers that do not change the base selection. The base selection is genuinely a
persistent semiconductor/storage cluster (SNDK/BE/WDC/CIEN/LITE, identical current holdings across 6 runs) —
that persistence is real, not only a display bug.

**MEASURED cash-carry uplift (computed analytically from the actual daily equity+cash curves, DGS3MO annual
path, 50 bps haircut):**
- **Main: +0.85 pp → ~35.6% (crosses the 35% canonical target)**
- **Concentrated: +1.42 pp → ~46.9% (closes ~⅓ of the 2.54 pp gap)**

So enabling cash-carry is not "cosmetic" — it recovers Main's target and roughly one-third of Concentrated's
gap, with zero added drawdown and no change to holdings. **This is the single highest-ROI unmeasured lever.**

---

## 1. Corrections to the ChatGPT-Pro directive (adopt these)

1. **Q4 canonical target is likely BACKWARDS.** ChatGPT Pro made `user_current/02_target_weights.csv`
   (AMD/AMAT/GLW, ~358% turnover) canonical. But the operating decision must respect the AlphaOps vNext
   current-holding/turnover policy. Code evidence: `build_daily_user_current_contract.py::load_target_weights`
   reads `target_rows_from_portfolio_reports` FIRST (raw scored) and only falls back to the operating book. A
   358% one-month concentrated swap is the raw scored snapshot bypassing hysteresis — **wrong** for a
   user/operating target. **Canonical = the AlphaOps vNext operating/official target book**
   (`reports/operating_*_target_book.csv` / `alphaops_vnext/official_*_target_book.csv`, ≈ BE/SNDK/WDC low
   turnover). Fix `load_target_weights` to prefer the operating book; `user_current` and
   `account_ledger_preview` both derive from it.
2. **The fullrun end-error is TWO problems, not one.** (a) the safety-audit contract bug (ChatGPT Pro covered
   it), AND (b) the run **cancelled at the 5h50m runner limit** during post-processing. Fixing the contract
   will NOT fix the timeout. Also the earlier run's `--strict` preflight `status.json` was never persisted.
3. **Cash-carry is DONE (#214), not "to implement later."** Reprioritize to MEASURE it now — it is the
   highest-ROI item and needs no fullrun.
4. **"Holdings unchanged" is BOTH** a contract drift AND genuine selection persistence (same semi cluster).
   The persistence is the deeper CAGR/overfit root; the contract drift is the display/safety bug.

---

## 1b. Round-2 code-verified refinements (CRITICAL — neither prior directive caught these)

1. **🔴 Cash-carry is a SILENT NO-OP as shipped — the DGS3MO rate is never fetched.** `#214` added
   `"dgs3mo":"DGS3MO"` to `MACRO_FRED_SERIES` and the ledger reads `cache_macro/fred_dgs3mo_DGS3MO.parquet`,
   BUT the pipeline only calls `load_fred_series(...)` for the 14 feature series (vix, dgs10, hy_oas, dxy, m2,
   ...) and **NEVER for `dgs3mo`** (verified: `r1000_pipeline.py` L4396–L5031). No workflow/sidecar
   materializes it either. So enabling `R1000_BROKER_CASH_CARRY_ENABLED=1` today → `load_cash_rate_series`
   returns empty → `raw_rate_pct=0` → **credit=0**. A naive P1 would report Δ=0 and everyone would wrongly
   conclude "cash-carry does nothing." **This is the real reason it looks like it wouldn't help.**
   - **Fix (P1 prerequisite):** materialize `cache_macro/fred_dgs3mo_DGS3MO.parquet` — add
     `load_fred_series(cfg, paths, "dgs3mo", MACRO_FRED_SERIES["dgs3mo"])` in the pipeline macro step (mirrors
     the dgs10 call), OR a standalone fetch in the workflow before the broker replay. Confirm the file lands in
     the same `cache_macro` the ledger reads (`REPO_ROOT/cache_macro`).
   - **Mandatory no-op guard:** when cash-carry is enabled, assert `cash_interest_accrued_usd > 0`. If 0 →
     FAIL LOUD (rate not found), do NOT report Δ=0 as "no effect." (Analytic triage estimate remains
     Main +0.85 pp / Conc +1.42 pp; the exact number needs the real daily DGS3MO once fetched.)
2. **P0.1 caveat — verify the operating book is genuine hysteresis, not a frozen echo.** Before making the
   operating/official target book canonical, the drift audit (P0.2) must confirm the operating book EVER
   deviates from current holdings when raw scores diverge strongly. If it equals current holdings EVERY month
   regardless of scores, that is a separate "stale echo" bug and making it canonical would freeze the portfolio
   permanently. Distinguish healthy-hysteresis (low turnover, still re-evaluates) from stuck-echo (never moves).
3. **P0.4 hard wall — GitHub hosted-runner max is 6h; 5h50m cancel means a SUCCESSFUL run barely fits.**
   Fail-fast fixes the failure case, but a VALID run's critical path (rebuild → official metrics → target books
   → safety audit → commit) must fit with margin. The ~73-min goal-search research sidecar can push a valid run
   over the ceiling. So in `run_full_rebuild_sidecars.py`, run the completion-critical chain FIRST and
   defer/split the heavy research grid into a separate job or gate it behind a time budget — it must never
   cancel an otherwise-valid run.

---

## 2. Answer to the user's asset question (short-bonds / gold / silver instead of cash)

- **"Hold short-term Treasuries instead of cash" ≈ cash-carry**, which is already measured at **+1.42 pp
  (Conc) / +0.85 pp (Main)**. A T-bill ETF (BIL/SGOV) ≈ cash + T-bill yield − expense, so cash-carry captures
  ~all of that benefit without tracking-error/liquidity friction. Enable cash-carry FIRST; a BIL/SGOV proxy
  A/B is a later confirmation, not a new idea.
- **Gold / silver / corporate bonds are NOT cash substitutes.** They carry their own drawdowns and go down
  WITH equities in stress (2022-style). Concentrated MDD headroom is only **0.92 pp** to −25%; using them as
  the defensive core risks breaking the gate. They may be tested ONLY as a small, separate satellite sleeve
  with its own drawdown A/B — never tagged as reserve/cash.
- **Taxonomy (do not mix):** Reserve = CASH / cash-carry / BIL / SGOV / SHV · Crash hedge = SH (event-only) ·
  Satellite = GLD / LQD / VCIT / low-vol · Growth = AI-Capex / momentum / semis.

---

## 3. Ordered plan (gates between; do NOT dispatch a fullrun until P0 done + tested)

### P0 — Make a fullrun actually COMPLETE (immediate blocker: contract + timeout + observability)
**P0a Canonical target (root of the drift).** Make the operating/official target book canonical; fix
`load_target_weights` priority (operating book first). `user_current/02_target_weights.csv` and
`account_ledger_preview/*/target_weights.csv` must both derive from it and carry a shared
`target_snapshot_hash` (+ `source_path`, `generated_at`, `semantics`).
**P0b Safety-audit contract.** Stop validating target tickers against `positions_current.csv`. Emit
`account_ledger_preview/<pf>/target_price_coverage.csv` (ticker, target_weight, current_position_exists,
target_only_new_buy, reference_price, price_date, price_source, price_status, stale) and have
`run_live_trading_safety_audit.py` block on `target_weight>0 AND price_status!=ok`, exempt CASH, and NOT
require target-only names to be current positions. (`run_account_order_preview.py:192 add_zero_position_target_prices`
already exists — reuse it.)
**P0c Fail-fast + timeout.** Move the safety/contract validation to run **right after target-book generation**
(before the ~73-min goal-search sidecar), so a contract failure aborts at ~3.5 h instead of cancelling at
5.9 h. Confirm whether the 5h50m cancel was the contract-block retry or genuine compute; if genuine, trim/split
the post-processing sidecars.
**P0d Preflight/summary observability.** Persist `outputs/clean7y_window_preflight/{status.json,report.md}` and
`full_rebuild_logs/clean7y_window_preflight.log` into artifact + `cloud_results`. Run summary must distinguish
`pipeline_completed / post_preflight_failed / safety_contract_failed / timeout_cancelled / production_blocked`.
**P0e Drift + hedge visibility.** `tools/run_current_target_drift_audit.py` (current vs user-target vs
preview-target overlap/weights/hash) and `outputs/hedge_exposure_report/summary.json` (why SH is absent from
current holdings: `hedge_dates`, `latest_hedge_active`, `reason_current_hedge_absent`).
**Gate:** local smokes pass (target-only-with-price → no block; target-only-without-price → block; current
holding without price → block; user-target vs preview-target agree; drift audit passes). No fullrun before this.

### P1 — MEASURE cash-carry (no fullrun; highest ROI; confirms the +1.4 pp)
**P1.0 prerequisite (do FIRST — see §1b.1):** materialize `cache_macro/fred_dgs3mo_DGS3MO.parquet` (the rate is
not currently fetched → cash-carry is a silent no-op without it). Then enforce the no-op guard
`cash_interest_accrued_usd > 0` or FAIL LOUD.
On the recovered artifact 28436307420 (or the latest broker replay), run the broker ledger twice:
`R1000_BROKER_CASH_CARRY_ENABLED=0` vs `=1` (DGS3MO, 50 bps, day_count 365). Report Main/Conc CAGR·MaxDD·Sharpe
before→after, `cash_interest_accrued_usd`, and **tier-2 `is_cagr_min` / `oos_is_cagr_ratio` before→after**
(carry should lift IS CAGR and help the overfit gate). Expected: **Main ~+0.85 pp (→ over 35%), Conc ~+1.4 pp**.
Label `metric_mode=broker_ledger_next_close_cash_carry`; keep the zero-yield number beside it. This is an
accounting baseline correction — both future A/B arms use the same mode. Do NOT fold into the official
acceptance run or claim production (contract requires an explicit cash-yield definition + `pit_universe_label_clean`).

### P2 — Concentrated residual CAGR: bull-floor A/B on the cash-carry baseline
Per `docs/CODEX_WORK_ORDER_CONC_CAGR_BULL_FLOOR_20260629.md`. Replay-stage one-flag
(`PHASE_REGIME_CAPACITY_BULL_FLOOR_ENABLED=1`, conc floor 0.85 → sweep 0.90/0.95). Compare **cash-carry
baseline vs cash-carry + bull-floor**. No-op proof (`rebalance_dates_bull_floor_lifted>0`, avg_cash drops),
gate-first (MaxDD≥−25 AND CAGR≥50), **overfit guard mandatory** (reject if gain is 2025/LITE-only; require ≥2
bull eras + OOS fold; OOS/IS not worse). With cash-carry closing ~1.4 pp, bull-floor only needs ~1.1 pp more.

### P3 — Reserve-asset policy doc + (later) cash-proxy/satellite A/B
`docs/CODEX_RESERVE_ASSET_POLICY_*.md` with the taxonomy in §2. Cash-proxy ETF A/B
(`cash_zero | cash_carry_dgs3mo | cash_proxy_BIL | cash_proxy_SGOV(if history)`) and any gold/bond **satellite**
test come AFTER P1/P2, each with its own drawdown A/B; reject if MaxDD worsens past −25.

### P4 — Selection persistence / theme concentration (the deeper CAGR + overfit root)
Only after P0–P2: the same semi/storage cluster carrying the OOS right tail is the real overfit driver
(OOS/IS 4.92x). Explore AI-Capex-bottleneck breadth / EPS-revision confirmation / cluster diversification as a
selection-layer track (PIT, walk-forward). Cash levers cannot fix single-theme concentration.

---

## 4. Acceptance criteria (Claude will verdict)
- **P0:** a fullrun COMPLETES (not cancelled); safety audit passes valid target-only buys and still blocks real
  missing prices; user-target == preview-target (shared hash); preflight/summary observability present; failure
  causes are distinguishable.
- **P1:** default-OFF preserves EXACT prior metrics; enabled shows Main ~+0.85 pp / Conc ~+1.4 pp with accrued
  interest and calendar-day (weekend-credited) accrual; PIT (no future rate); reported as accounting correction.
- **P2:** ship gate ΔCAGR≥+0.5 pp toward 50 AND MaxDD≥−25 AND ΔSharpe≥−0.05 AND Main non-regress AND multi-era/OOS
  robustness AND early_scout≥4.
- **Global:** cheap A/B never final — reproduce on a completed fullrun before any "achieved" claim; production
  stays blocked by `pit_universe_label_clean=false`.

## 5. Non-negotiables
No production promotion; no live trading; no fullrun until P0 completes + local smokes pass; no proxy 8Y/10Y;
free/cheap proxy replay is diagnostic only; no partial-year 2026 annualized CAGR as proof; PIT-only, walk-forward
+ 126d embargo; new levers env-gated default OFF; cash-carry stays research-mode until the data contract defines
cash-yield; gold/bonds/blue-chips never classified as reserve/cash.

## 6. What is DONE vs OPEN
DONE: window-gate fix (#213), cash-carry accounting code+test (#214, verified correct). OPEN: enable/measure
cash-carry (P1), fullrun completion contract+timeout (P0), canonical operating-book target (P0a), bull-floor
measurement (P2), selection concentration (P4).
