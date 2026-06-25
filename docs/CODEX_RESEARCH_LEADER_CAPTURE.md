# Codex Research Spec — Leader Capture Optimization (entry / exit / replace timing)

> Handoff target: Codex (local). Author: Claude Code (web), 2026-06-24.
> Read alongside: `docs/CODEX_PLAN_FORWARD_TIMING_OPTIMIZATION.md` (levers + ship gate),
> `docs/CODEX_DIRECTIVE_CAGR_MDD_ROADMAP.md` (targets), `CLAUDE.md` (answer-sheet ban).
> Goal: optimize WHEN we buy / sell / replace leaders, using market regime, earnings
> (실적), momentum, and period-by-period relative strength — without answer-sheet hindsight.

---

## 0. Prime directive (unchanged)

Every rule is forward-causal (PIT, available_from ≤ t), name/era-agnostic, env-gated
default OFF, and must survive walk-forward + 126d embargo. Measured on
`broker_ledger_next_close`. Ship gate: ΔCAGR ≥ +0.5pp AND ΔSharpe ≥ −0.05 AND
ΔMaxDD ≥ −3pp AND **theme_leader_capture must not regress**. No production promotion
(pit_universe_label still blocks). No live / T3 / proxy work.

---

## 1. Current method — as-built map (verified in code)

**Leader definition** — `r1000_market_leader_engine.classify_leader_tier(row)`:
period-by-period RS vs SPY **and** QQQ (1w/1m/3m/6m) + `sector_leadership_score`:
- `DUAL_LEADER`  : rs_spy_3m>0 AND rs_qqq_3m>0 AND (rs_spy_6m>0 OR rs_qqq_6m>0)
- `SECTOR_LEADER`: rs_spy_3m>0 AND sector_leadership_score>0
- `EMERGING_LEADER`: short-term (1w/1m) RS>0 but 3m RS ≤ 0
- `LAGGING`     : else

**Entry (buy)** — monthly rebalance, next-close fill. Selection by the score stack
(`dynamic_leader_score`, `compute_oneil_leadership_score`, `sector_theme_leadership_score`,
`compute_rs_acceleration_score`, `compute_h6_dynamic_leader_score`). Overextension is a
**score tilt only** (`stage2_overext_penalty`), NOT an entry gate.

**Exit (what actually drives production trades)** —
`tools/run_alphaops_vnext_policy_replay.py::holding_state(row, score_median, score_sigma)`:
- `EXIT`   : `hard_reject` / `top7_standalone_blocked` / price below **both** ma50 and ma200
- `TRIM`   : `alphaops_vnext_score < score_median − max(score_sigma, 0.25)` (peer-band)
- `WARNING`: `rs_benchmark_1w < 0 AND rs_benchmark_3m < 0`
- `HOLD`   : else

**Replace** — `build_variant_book`: challenger must beat weakest held by a gap
(`threshold_normal` / `threshold_broken`); PR #151 raises the gap for healthy leaders.

**Regime** — `crisis_state_for_date` → `crisis_cash_target` + `crisis_new_buy_allowed`
(cash + new-buy gating only; turnover is NOT regime-conditioned).

**Earnings (실적)** — `compute_eps_revision_score` (`eps_revision_score`),
`phase9_c3_eps_turn_positive`, `ni_loss_narrowing_4q`, and a per-ticker
consecutive-negative-`revision_score` streak — all feed **SCORE only** (≈0.15 weight),
**not** the exit/hold STATE.

---

## 2. Diagnosis — where leader capture leaks (evidence-linked)

🔴 **#1 (biggest): two leader-state machines; the protective one is not wired to trades.**
`classify_leader_state` contains a **`SHAKEOUT_GUARD`** (protect a held name when
6m RS>0 AND leadership intact (sector>0 + above200) AND smart-money confidence ≥ 0.25
AND only a 1-month wobble (rs_qqq_1m<0≤rs_qqq_3m) AND not crisis). But the **production
`vnext holding_state` does not use it** — it trims on a peer-band rank and warns on
1w&3m RS sign. → direct cause of the premature-sell leak (entry_exit_timing_audit:
**+8.4% 126d excess on 35% of exits, pct_held_365d_plus = 0%**). A healthy leader that
dips below the hot-month peer median gets TRIM'd.

🔴 **#2: earnings is absent from sell/hold timing.** Strong revisions/EPS-turn live in
SCORE, not STATE → we TRIM earnings-strong leaders and keep earnings-broken ones.

🟠 **#3: RS is LEVEL-only (sign), not SLOPE.** `rs_acceleration_score` exists but the
state machine reads rs>0/<0, so we enter late (after strength) and exit late (after the
break) instead of on acceleration/deceleration.

🟠 **#4: no entry-timing quality gate.** Overextension is a score tilt, not a gate →
chasing names far above ma50 is possible.

🟡 **#5: industry-group leadership not required in `leader_tier`** (stock-vs-index only)
→ can hold a strong stock in a dying group (violates O'Neil "leader in a leading group").

🟡 **#6: regime does not modulate turnover** (crisis touches cash only).

---

## 3. Research framework (priority order toward CAGR/MDD targets)

All levers PIT, env-gated default OFF, measured via `entry_exit_timing_audit` +
`stock_selection_quality` + broker-ledger. Use the lever-sweep harness for cheap grids.

### A. Sell / hold timing  — HIGHEST VALUE (attacks the +8.4% leak)

#### A1 — Wire SHAKEOUT_GUARD into the production exit machine  ★ start here
- **What**: in `vnext holding_state`, before returning `TRIM`/`WARNING`, consult a
  shakeout guard equivalent to `classify_leader_state`'s: if `leader_tier ∈
  {DUAL_LEADER, SECTOR_LEADER}` (PIT) AND 6m RS>0 AND price>ma200 AND it is a
  single-month wobble (rs_benchmark_1m<0 ≤ rs_benchmark_3m) AND not crisis → downgrade
  the exit to `HOLD`/`no_add` instead of TRIM. Do NOT protect names that are below ma200
  or have rs_3m<0 (those are real breaks).
- **PIT inputs**: leader_tier, rs_benchmark_{1m,3m,6m}, price_above_ma200, crisis_state —
  all already on the row at decision time.
- **env**: `PHASE_SHAKEOUT_GUARD_PROD_ENABLED` (default OFF).
- **Why it's the cheapest big win**: the logic already exists in
  `classify_leader_state`; this is a wiring change into `holding_state`, not new alpha.
- **Acceptance**: `entry_exit_timing_audit` — TRIM/WARNING 126d excess on protected rows
  moves toward ≤ 0; `pct_held_365d_plus` rises from 0%; theme_leader_capture non-regress;
  ship gate holds. Telemetry: count of `shakeout_guard_applied=True` rows > 0 (prove it
  fired — same no-op guard discipline as PR #151).

#### A2 — Earnings gate promoted from score into hold/exit state
- **What**: split the existing earnings signals into a hold-extend vs exit-accelerate gate:
  - hold-extend: strong `eps_revision_score` > 0 / `phase9_c3_eps_turn_positive` /
    `ni_loss_narrowing_4q` → suppress TRIM/WARNING for one cycle (earnings-confirmed leader).
  - exit-accelerate: consecutive-negative-`revision_score` streak ≥ N (the streak is
    already tracked in `r1000_pipeline.py`) → escalate WARNING→EXIT_REPLACE faster.
- **PIT inputs**: eps_revision_score, phase9_c3_eps_turn_positive, ni_loss_narrowing_4q,
  negative-revision streak — all SEC-accepted-timestamp PIT.
- **env**: `PHASE_EARNINGS_STATE_GATE_ENABLED` (default OFF).
- **Acceptance**: premature_sell_excess on earnings-strong holds ↓; exits on
  earnings-broken names happen earlier (lower realized loss before exit); ship gate +
  capture non-regress.

#### A3 — RS-deceleration pre-emptive trim (after A1/A2)
- `rs_acceleration_score < 0` sustained ≥ N months AND group RS weakening → trim before
  the level break. env `PHASE_RS_DECEL_TRIM_ENABLED`.

### B. Buy / entry timing

#### B1 — Entry-quality gate
- Reject/penalize entries far above ma50 (use `distance_from_ma50` / `stage2_overext`)
  unless a fresh base breakout. Promote `stage2_overext_penalty` from score-tilt to an
  optional entry gate. env `PHASE_ENTRY_QUALITY_GATE_ENABLED`.

#### B2 — Earlier EMERGING capture (roadmap Lever 4)
- Admit `EMERGING_LEADER` before 3m RS turns positive when `rs_acceleration_score>0` +
  short-term RS new-high + volume thrust (all PIT). Current rule waits for 3m>0 → late.
- **Acceptance**: `stock_selection_quality` missed_leaders ↓, theme_leader_capture ↑,
  with no rise in false entries (premature_buy forward 63d).

#### B3 — Require leading group in `leader_tier`
- Add industry-group RS>0 to the `DUAL_LEADER` condition. env `PHASE_GROUP_LEADER_REQUIRED_ENABLED`.

### C. Replace timing
- **C1**: PR #151 leadership-persistence (in flight).
- **C2**: challenger must itself be a leader (`leader_tier` pass) — never replace a leader
  with a non-leader on a transient score blip.
- **C3**: regime-conditional turnover — GREEN + strong breadth → allow EMERGING rotation
  (capture new leaders fast); WATCH / weak breadth → hold incumbents, suppress rotation.

### D. Regime integration (ties A–C together; converges with roadmap Levers 3 & 6)
- One regime → (entry aggressiveness, exit sensitivity, turnover, gross floor) curve.
  Risk-on: faster new-leader rotation + deploy GREEN idle cash. Risk-off: hold incumbents +
  faster loss-cut + 2022-style defensive cash (which MUST survive). Build from PIT signals
  only (VIX z, breadth above ma200, index 200dma distance, index RSI, net liquidity).
  CNN Fear&Greed is **live-only context, not backtestable** — do not use it for historical
  cash/ranking.

---

## 4. Sequencing & measurement

1. **A1 (SHAKEOUT wiring)** + **A2 (earnings state gate)** first — largest leak, lowest
   risk (reuses existing logic). A/B v1: ONE conservative config, prove it fires
   (`applied=True` rows > 0) + capture non-regress + ship gate, before any grid.
2. **B2 / B3** next — faster, more accurate leader entry → capture ↑.
3. **C / D** last — integration with roadmap Levers 3/6.
- Cheap first: lever-sweep single-run grids; full A/B only on shortlisted configs;
  no blind 4h fullrun.
- Every lever: env-gated default OFF; new feature columns added to
  `build_feature_store.keep_cols` + `hard_sanitize` + phase zero-placeholder (else they
  silently become 0.0); CI smoke in the same commit.

## 5. Why this is the right track for the targets
- The biggest measured alpha leak is **sell timing** (premature_sell +8.4%,
  pct_held_365d_plus = 0%). A1+A2 attack it directly and help BOTH sleeves (let winners
  compound → Concentrated CAGR gap, and fewer round-trips → Main).
- Entry/capture (B) raises right-tail winner capture — the core of a growth/concentrated
  strategy (a few winners carry CAGR; the skill test is whether they were identifiable
  ex-ante with PIT signals, not whether returns are concentrated).
- Regime (D) is where MDD and CAGR levers are reconciled without breaking the 2022 defense.
