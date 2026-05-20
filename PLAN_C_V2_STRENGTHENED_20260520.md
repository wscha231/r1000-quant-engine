# Plan C v2 (Strengthened) — Smart Money + ETF Overlay
**Updated**: 2026-05-20 (revision after ChatGPT Pro cross-review)
**Status**: Replaces v1 (PLAN_SMART_MONEY_OVERLAY_20260520.md)

---

## Changelog vs v1
- **Baseline corrected**: official broker-ledger (main 20.35% / concentrated 36.41%) replaces research (29.19%)
- **Phase C0 (governance) added**: explicit official/research separation
- **Phase C1.5 (data readiness audit) added**: explicit gates before any live wiring
- **Initial weights lowered**: main 0.10/cap 0.20, concentrated 0.15/cap 0.30 (was 0.30+0.20+0.10)
- **Phase C5 (Full Auto promotion) demoted to Phase C8**: manual approval until A1/A2 hard gates pass
- **Evidence fusion v2 formula added**: explicit per-signal weights
- **A1/A2 broker_accounting_audit gates made hard prerequisites**

---

## 0. Verified Code State (cross-checked vs ChatGPT Pro claims)

| Item | Status |
|---|---|
| `w_sec_institutional_evidence = 0.30` (r1000_config.py:2103) | ✅ EXISTS |
| `w_sec_insider_evidence = 0.20` (r1000_config.py:2104) | ✅ EXISTS |
| `w_evidence_fusion_score`, `w_etf_holdings_evidence` | ❌ DOES NOT EXIST (must build) |
| `evidence_fusion_apply_to_live_score` flag | ❌ DOES NOT EXIST (must build) |
| `score_etf_holdings_overlay`, `evidence_fusion_score` columns | ❌ NOT COMPUTED (must build) |
| `score_sec_institutional_overlay`, `score_sec_insider_overlay` columns | ✅ EXISTS (PR #16) |
| ETF leadership snapshot (`etf_leadership_snapshot.py`) | ✅ EXISTS (17 ETFs daily) |
| `run_theme_leadership_tape.py` report-only sidecar | ✅ EXISTS (static ETF_LOOKTHROUGH) |
| SEC evidence data on disk | ❌ NONE (cron not triggered) |
| broker_accounting_audit A1 (delisted_cost_basis) | ❌ FAILING |
| broker_accounting_audit A2 (survivorship_coverage) | ❌ FAILING |

---

## 1. Baseline Reality Check (CRITICAL)

### Official broker-ledger (the actual target):
| Portfolio | CAGR | MaxDD | Sharpe | valid_for_production |
|---|---:|---:|---:|:-:|
| **main** | **20.35%** | -33.45% | 0.991 | ✅ true |
| **concentrated** | **36.41%** | -38.45% | 1.186 | ✅ true |

### Research backtest (informational only):
| Portfolio | CAGR | MaxDD | Sharpe | Bootstrap CI |
|---|---:|---:|---:|---|
| main | 29.19% | -17.46% | 1.7249 | [17.4%, 46.6%] |

**~9pp gap** between official and research is unexplained until A1/A2 gates resolve. **All Plan C verdicts MUST use official broker-ledger numbers** — research is for diagnostics only.

### Target (revised):
- **main official**: CAGR ≥ 21.5% (+1.15pp), MaxDD ≤ -32.5% (+1pp), Sharpe ≥ 0.95 (-0.04)
- **concentrated official**: CAGR ≥ 38.0% (+1.6pp), MaxDD ≤ -37.5% (+1pp), Sharpe ≥ 1.14 (-0.05)
- NOT "32%+ CAGR" (that was research metric, ambiguous)

---

## 2. Hard Prerequisites (must resolve BEFORE any live wiring)

### Prerequisite 1: A1/A2 broker_accounting_audit gates
- `research/broker_accounting_audit.json` shows both `passed=None`
- Resolution required: delisted_cost_basis_fallback fix + survivorship_coverage audit
- **Estimated effort**: 3-5 days (this is its own subproject)

### Prerequisite 2: SEC data presence
- `outputs/sec_institutional_signals/signals_latest.parquet` must exist
- `outputs/sec_ownership_signals/signals_latest.parquet` must exist
- Triggered by: `sec_13f_quarterly_refresh.yml` + `sec_form4_daily_refresh.yml` (manual)

### Prerequisite 3: Data readiness gate
- Form 4 signal tickers ≥ 300
- 13F signal tickers ≥ 100
- SEC evidence stale days ≤ 240
- CIK string schema validation pass

**If any prerequisite fails, halt promotion path. Research/diagnostics only.**

---

## 3. Two-Axis Sector Framework (unchanged from v1)

### Axis 1 — Signal sectors (8 categories)
1. SEC 13F (institutional flow) — 14 columns
2. SEC Form 4 (insider flow) — 12 columns
3. ETF leadership (thematic momentum) — 17 ETFs daily
4. **NEW**: Smart money convergence (institutional ∧ insider)
5. **NEW**: Industry smart money flow
6. Fundamental (existing 10-Q)
7. Technical (existing RS/MA/momentum)
8. Regime (existing macro state)

### Axis 2 — Industry sectors
- 11 standard sectors + 8 curated thematic + dynamic-discovered top-30 ETFs
- Existing: `industry_group_strength_score`, `rs_industry_*`

---

## 4. Tiered Score Formula (v2 — flag-protected)

```python
# Phase C2-C7 (research/shadow only)
shadow_evidence_fusion_score = (
    0.24 * form4_cluster_buy_score          # fast, high conviction
  + 0.18 * activist_13d_score                # strong event
  + 0.16 * institutional_13f_score           # mid (45d lag)
  + 0.14 * etf_sector_leadership_score       # mid (sector rotation)
  + 0.10 * etf_thematic_alignment_score      # mid-low (PIT required)
  + 0.10 * smart_money_convergence_score     # high (cross-validation)
  + 0.08 * industry_smart_money_flow_score   # mid (diffusion)
)

# Live score application (Phase C5+, only if evidence_fusion_apply_to_live_score=True)
if cfg.evidence_fusion_apply_to_live_score:
    fusion_bonus = min(
        cfg.w_evidence_fusion_score * shadow_evidence_fusion_score,
        cfg.evidence_bonus_cap
    )
    fusion_bonus *= regime_multiplier[regime_state]  # Tier 2 (NEW)
    score += fusion_bonus
```

**Critical safeguards**:
- `evidence_fusion_apply_to_live_score: bool = False` (default OFF)
- Per-portfolio caps (main 0.20, concentrated 0.30)
- Regime multiplier outside of bonus cap (separately bounded [0.3, 1.3])
- All component scores normalized [0, 1]
- Missing signal → confidence ↓, NOT score = 0

---

## 5. Weight Tier Decision Matrix (v2 — conservative)

| Tier | Component | Type | Cadence | Source |
|---|---|---|---|---|
| 1 | score_core 14 components | FIXED | 3mo retrain | walk-forward ML |
| 2 | regime_multiplier (5×7) | DYNAMIC lookup | Quarterly | regime-conditional IC |
| 3 | short_extension_penalty | FIXED (0.20) | Manual | A/B verdict |
| 4 | w_sec_institutional | DYNAMIC | Quarterly | sec_evidence_learning |
| 4 | w_sec_insider | DYNAMIC | Quarterly | sec_evidence_learning |
| 5 | w_evidence_fusion_score | DYNAMIC | Quarterly | NEW fusion learning |
| 5 | evidence_fusion_apply_to_live_score | **MANUAL FLAG** | Human approval | governance |
| 6 | w_etf_sector_leadership | DYNAMIC | Monthly | ETF leadership IC |
| 6 | w_etf_thematic_alignment | DYNAMIC | Monthly | Theme IC (PIT required) |
| 7 | w_industry_smart_money_tilt | DYNAMIC | Quarterly | Industry flow IC |

### Initial weight bounds (per-portfolio, conservative)

```python
# r1000_config.py (NEW fields to add)
class EngineConfig:
    # SEC overlay (existing)
    w_sec_institutional_evidence: float = 0.30      # EXISTS (line 2103)
    w_sec_insider_evidence: float = 0.20            # EXISTS (line 2104)

    # NEW: Evidence fusion v2 (Plan C v2)
    w_evidence_fusion_score: float = 0.10           # main starter (NEW)
    w_evidence_fusion_score_concentrated: float = 0.15  # NEW
    evidence_bonus_cap: float = 0.20                # main cap (NEW)
    evidence_bonus_cap_concentrated: float = 0.30   # concentrated cap (NEW)
    evidence_fusion_apply_to_live_score: bool = False  # MASTER SWITCH (NEW)

    # NEW: ETF overlay (must wait for PIT data)
    w_etf_sector_leadership: float = 0.04           # very small starter (NEW)
    w_etf_thematic_alignment: float = 0.03          # very small starter (NEW)
    etf_holdings_pit_required: bool = True          # safety (NEW)

    # NEW: Smart money convergence + industry tilt
    w_smart_money_convergence: float = 0.05         # NEW (was 0.10 in v1)
    w_industry_smart_money_tilt: float = 0.04       # NEW (was 0.08 in v1)

    # NEW: Data readiness gates
    sec_evidence_min_form4_signal_tickers: int = 300  # NEW
    sec_evidence_min_13f_signal_tickers: int = 100    # NEW
    sec_evidence_max_stale_days: int = 240            # NEW
```

**Promotion path** (Tier 5 weight escalation):
```
Phase C2-C3:  apply_to_live = False             (shadow only)
Phase C4-C5:  apply_to_live = True, w = 0.05    (cautious, broker-ledger validated)
Phase C6:     apply_to_live = True, w = 0.10    (if SHIP verdict + A1/A2 passed)
Phase C7+:    apply_to_live = True, w = 0.15    (concentrated only, broker-ledger SHIP)
NEVER:        w > 0.25 without 6mo broker-ledger consistency
```

---

## 6. Regime-Conditional Weight Multipliers (unchanged from v1)

```python
REGIME_WEIGHT_MULTIPLIERS = {
    "deep_bear":   {"sec_inst": 0.5, "sec_insider": 1.2, "etf": 0.3, "convergence": 0.6, "industry_tilt": 0.4},
    "bear":        {"sec_inst": 0.7, "sec_insider": 1.0, "etf": 0.5, "convergence": 0.8, "industry_tilt": 0.6},
    "neutral":     {"sec_inst": 1.0, "sec_insider": 1.0, "etf": 1.0, "convergence": 1.0, "industry_tilt": 1.0},
    "bull":        {"sec_inst": 1.2, "sec_insider": 0.9, "etf": 1.2, "convergence": 1.2, "industry_tilt": 1.1},
    "strong_bull": {"sec_inst": 1.0, "sec_insider": 0.7, "etf": 1.3, "convergence": 1.3, "industry_tilt": 1.2},
}
```

---

## 7. Implementation Phases (v2 — re-ordered for safety)

### Phase C0 — Governance + Baseline Fix (1 day) ⭐ NEW
**Goal**: Establish official/research separation, freeze defaults.

NEW files:
- `research/evidence_overlay_governance.md` — official vs research rules
- `research/baseline_registry_official_20260520.md` — pinned official metrics
- `research/promotion_gate_evidence_overlay.md` — gate definitions

Updates:
- `run_local.py:CURRENT_BASELINE` — split into `CURRENT_BASELINE_OFFICIAL` + `CURRENT_BASELINE_RESEARCH`
- `r1000_config.py` — comment all new w_* fields with apply_to_live = False default

**Verification**: `py -3 tests/smoke_test.py` 97/97 + new test `evidence_fusion_apply_to_live_default_off`

---

### Phase C1 — Data Foundation (1 week, BLOCKING) ⭐ MANUAL TRIGGER
**Manual triggers (GitHub UI)**:
1. `sec_13f_quarterly_refresh.yml` (master)
2. `sec_form4_daily_refresh.yml` (master)
3. Wait 24-48h for first artifacts
4. `sec_evidence_learning_manual.yml` (after both above complete)

**Outputs expected**:
- `outputs/sec_institutional_signals/signals_latest.parquet`
- `outputs/sec_ownership_signals/signals_latest.parquet`
- `outputs/sec_evidence_learning/best_score_weights.json`

---

### Phase C1.5 — Data Readiness Audit (2 days) ⭐ NEW (from ChatGPT)
**Goal**: Quantitative gate before any code changes.

NEW tool: `tools/run_evidence_data_readiness.py`

Outputs:
- `outputs/evidence_data_readiness/summary.json`
- `outputs/evidence_data_readiness/coverage_by_month.csv`
- `outputs/evidence_data_readiness/coverage_by_ticker.csv`
- `outputs/evidence_data_readiness/report.md`

**Hard gates**:
| Metric | Threshold | Action if Fail |
|---|---:|---|
| Form 4 signal tickers | ≥ 300 | Halt — increase manager universe |
| 13F signal tickers | ≥ 100 | Halt — manual reselection |
| SEC stale days | ≤ 240 | Halt — re-trigger crons |
| CIK schema (10-digit zero-padded) | 100% pass | Halt — fix managers.csv |
| ETF observed_at present | required | ETF Tier 6 → research only |

If gates fail: only Smart Money Top30 (Phase C6) and IC learning (Phase C2) proceed — NO live score wiring.

---

### Phase C2 — Evidence Weight Learning (research-only, 2 days)
Reuse existing `tools/run_sec_evidence_learning_pipeline.py` + extend with NEW measurements.

Extended outputs:
- `outputs/evidence_weight_learning/evidence_ic_by_horizon.csv` (1M/3M/6M IC per signal)
- `outputs/evidence_weight_learning/evidence_topk_hit_rate.csv` (top-5/10/20 excess)
- `outputs/evidence_weight_learning/evidence_decile_spread.csv` (top vs bottom decile)
- `outputs/evidence_weight_learning/evidence_regime_ic.csv` (regime-conditional IC for Tier 2)
- `outputs/evidence_weight_learning/evidence_weight_recommendation.json` (research-only)

**No production weight change at this phase.** Output is for human review only.

---

### Phase C3 — Shadow Evidence Fusion + Convergence (3 days)
**NEW files**:
- `tools/run_smart_money_convergence.py` — adds `smart_money_convergence_score` column
- `tools/run_industry_smart_money_flow.py` — industry-level aggregation
- `tools/run_evidence_fusion_v2.py` — computes shadow `evidence_fusion_score_v2`

**Modify**:
- `r1000_pipeline.py:add_total_score_columns` — compute `evidence_fusion_score_v2` (shadow) but DO NOT apply to score (guarded by `evidence_fusion_apply_to_live_score=False`)
- `r1000_config.py` — add 8 new fields (see Section 5)

**Smoke tests** (4 new):
- `evidence_fusion_v2_shadow_computed`
- `evidence_fusion_apply_to_live_default_off`
- `smart_money_convergence_column_populated`
- `industry_smart_money_flow_consistency`

---

### Phase C4 — Broker-Ledger Evidence Challenger (3 days) ⭐ CRITICAL
**NEW tool**: `tools/run_evidence_overlay_challenger.py`

**Rules**:
- DO NOT modify production score formulas
- Build challenger target books only
- Run broker-ledger next-close replay (official metric mode)
- Evaluate main + concentrated separately

**Matrix** (7 runs):
| Run | SEC inst | SEC insider | ETF | Convergence | Industry tilt | Regime mult |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| A (baseline) | OFF | OFF | OFF | OFF | OFF | OFF |
| B (SEC only) | learned | learned | OFF | OFF | OFF | OFF |
| C (ETF only) | OFF | OFF | learned | OFF | OFF | OFF |
| D (convergence only) | OFF | OFF | OFF | ON | OFF | OFF |
| E (SEC + ETF) | learned | learned | learned | OFF | OFF | OFF |
| F (all additive) | learned | learned | learned | ON | learned | OFF |
| G (all + regime mult) | learned | learned | learned | ON | learned | ON |

**Initial challenger weights** (per-portfolio):
```yaml
main:
  w_evidence_fusion_score: 0.10
  evidence_bonus_cap: 0.20

concentrated:
  w_evidence_fusion_score: 0.15
  evidence_bonus_cap: 0.30
```

**SHIP gate (broker-ledger official)**:
- main: ΔCAGR ≥ +0.5pp, ΔMaxDD ≥ -1pp, ΔSharpe ≥ -0.05, turnover Δ ≤ +15%, fees Δ ≤ +15%
- concentrated: ΔCAGR ≥ +0.5pp, ΔMaxDD ≥ -1pp, ΔSharpe ≥ -0.05
- Cost sensitivity 50/75/100bps acceptable
- A1/A2 hard gates must be `passed=True` (prerequisite)

---

### Phase C5 — ETF Top-Holdings PIT (2 days) ⭐ ChatGPT priority
**NEW tool**: `tools/refresh_etf_top_holdings.py`

**Required schema** (`data_pit/etf/theme_holdings_pit.parquet`):
```
columns:
  etf: str           # ETF symbol
  constituent: str   # holding ticker
  observed_at: datetime  # when we observed
  effective_date: datetime  # holdings as-of date
  weight: float      # within-ETF weight
  source: str        # data source
  pit_label: str     # 'observed' | 'imputed' | 'stale'
```

**Until this exists**: ETF evidence is **research-only or capped at small weight (0.04-0.05)**.

---

### Phase C6 — Smart Money Top30 Standalone (2 days, parallel)
NEW tool: `tools/run_smart_money_top30.py`

Output: `outputs/smart_money/top30_latest.csv`

**CRITICAL: This is a WATCHLIST product, NOT auto-buy**:
- Daily output for human review
- Schema includes templated NL explanation
- NO automatic portfolio integration
- Telegram push to existing channel (top 5 new entries)

---

### Phase C7 — After-Service Infrastructure (3 days, parallel)
(Unchanged from v1 — independent improvements)

- C7.1 Auto-retire bad signals (IC < 0.005 for 2 quarters → w=0)
- C7.2 Auto-promote good signals (IC > 0.025 for 2 quarters + broker_ledger pass)
- C7.3 Auto-add new top managers (probation period 6mo)
- C7.4 Anomaly alerts (Telegram)
- C7.5 Auto-baseline rotation proposal (semi-auto, human approval)
- C7.6 Regime drift detection

---

### Phase C8 — Full Auto Weight Promotion (DEMOTED from v1 Phase C5)
**ONLY allowed if ALL of**:
- A1 + A2 broker_accounting_audit gates = `passed=True`
- 6+ months of consistent SHIP verdicts on Phase C4 challenger
- Manual approval explicit
- Hard cap: max ±20% weight change per quarter (was ±30%)
- Rollback trigger: any month's official broker-ledger dCAGR < -0.5pp → auto-revert

**Until ChatGPT's prerequisite work is done, Phase C8 is BLOCKED.**

---

### Phase C9 — Regime Multiplier Calibration (2 days, FINAL)
After Phase C4 ships, calibrate regime multipliers based on observed regime-conditional IC.
NEW tool: `tools/run_regime_multiplier_calibrate.py` (quarterly)

---

## 8. Update Frequency Matrix (v2 — minimum critical set)

| Component | Cadence | Workflow |
|---|---|---|
| Form 4 data | Daily 08:20 KST | `sec_form4_daily_refresh.yml` |
| 13F data | Quarterly Feb/May/Aug/Nov | `sec_13f_quarterly_refresh.yml` |
| ETF leadership snapshot | Daily | `after_close_daily.yml` |
| **Data readiness audit** | Weekly | NEW `evidence_data_readiness.yml` ⭐ |
| Smart Money Top30 | Daily 09:00 KST | NEW `smart_money_top30_daily.yml` |
| Anomaly monitor | Daily | NEW `anomaly_monitor.yml` |
| Evidence IC learning | Quarterly post-13F | NEW `evidence_weight_learn.yml` |
| Broker-ledger challenger | Quarterly | NEW `evidence_overlay_challenger.yml` |
| Regime multiplier calibrate | Quarterly | NEW `regime_multiplier_calibrate.yml` |
| Manager reselection | Semiannual Jun/Dec | `sec_13f_manager_reselection.yml` |
| Walk-forward retrain | 3 months per-fold | existing |
| FULL_REBUILD | Manual | `full_rebuild_manual.yml` |

---

## 9. Risk Matrix (v2)

| Risk | Severity | Mitigation (NEW from ChatGPT) |
|---|:-:|---|
| **Official-research metric confusion** | 🔴 HIGH | Phase C0 governance; require explicit `metric_source` in all reports |
| **A1/A2 gates failing** | 🔴 HIGH | Hard prerequisite — no promotion until both `passed=True` |
| ChatGPT-claimed config fields don't exist | 🟡 MED | Don't assume — verify before reference |
| Full Auto promotion premature | 🔴 HIGH | Phase C8 only after A1/A2 + 6mo SHIP |
| Initial weights too high | 🟡 MED | main 0.10 / concentrated 0.15 starters |
| ETF holdings not PIT-safe | 🟡 MED | Capped 0.04-0.05 until PIT layer ready |
| 13F lag (45 days) | 🟢 LOW | Form 4 prioritized (0.24 weight in fusion v2) |
| Missing data ≠ bad signal | 🟢 LOW | Separate confidence from score; missing→conf↓ |

---

## 10. Critical Files (v2)

| File | Action | LoC |
|---|---|---:|
| `r1000_config.py` | Add 8 NEW fields + readiness gates | +60 |
| `r1000_pipeline.py:add_total_score_columns` | Compute fusion_v2 SHADOW + guard | +50 |
| `r1000_features.py:load_sec_evidence_overlay` | Extend for ETF + convergence | +40 |
| `tools/run_evidence_data_readiness.py` | NEW ⭐ Phase C1.5 | ~250 |
| `tools/run_evidence_fusion_v2.py` | NEW Phase C3 | ~200 |
| `tools/run_smart_money_convergence.py` | NEW Phase C3 | ~180 |
| `tools/run_industry_smart_money_flow.py` | NEW Phase C3 | ~150 |
| `tools/run_evidence_overlay_challenger.py` | NEW ⭐ Phase C4 | ~350 |
| `tools/refresh_etf_top_holdings.py` | NEW Phase C5 | ~220 |
| `tools/run_smart_money_top30.py` | NEW Phase C6 | ~250 |
| `tools/run_regime_multiplier_calibrate.py` | NEW Phase C9 | ~150 |
| 7-9 GitHub workflows | NEW | ~450 |
| `research/evidence_overlay_governance.md` | NEW Phase C0 | ~100 |
| `research/baseline_registry_official_20260520.md` | NEW Phase C0 | ~50 |
| `research/promotion_gate_evidence_overlay.md` | NEW Phase C0 | ~80 |
| `tests/smoke_test.py` | +15 new tests | +250 |

**Total**: ~2,800 LoC NEW + ~150 LoC modified

---

## 11. Execution Order (v2 — re-sequenced)

```
Week 1: Phase C0 (governance) + Phase C1 trigger (manual GitHub UI)
        └─ Wait for data (5-7 days)

Week 2: Phase C1.5 (data readiness audit) — HARD GATE
        ├─ If gate fails: halt, fix manager universe / cron timing
        └─ If gate passes: Phase C2 (IC learning research-only) starts

Week 3: Phase C3 (fusion v2 + convergence shadow) + Phase C6 (Top30) parallel
        └─ Phase C5 (ETF PIT) starts in background

Week 4: Phase C4 (broker-ledger challenger) — CRITICAL VALIDATION
        ├─ Run 7-scenario matrix
        ├─ SHIP gate evaluation
        └─ If SHIP: enable evidence_fusion_apply_to_live_score=True (manual)
        └─ If REJECT: iterate weights, OR keep research-only

Week 5: Phase C7 (after-service) + Phase C9 (regime mult calibration)
        └─ Phase C8 (Full Auto) BLOCKED until A1/A2 resolved

Independent track: A1/A2 broker_accounting_audit fix (3-5 days)
```

**Total: ~18-22 days dev + ~5-7 days cloud validation**

---

## 12. First Concrete Action

**Critical path 1** (governance + data):
1. Phase C0 — create `research/evidence_overlay_governance.md` (1h)
2. Phase C1 — trigger `sec_13f_quarterly_refresh.yml` + `sec_form4_daily_refresh.yml` via GitHub UI (manual)

**Critical path 2** (independent A1/A2 work — can start in parallel):
3. Fix `delisted_cost_basis_fallback` (S1-1 from Part A audit)
4. Run survivorship audit
5. Set both A1/A2 gates to `passed=True`

These two tracks BOTH must complete before Phase C4 (broker-ledger challenger) can produce promotable results.

---

## 13. Differentiator vs ChatGPT Pro's Plan

| Aspect | ChatGPT Pro | This v2 plan |
|---|---|---|
| Official/research separation | ✅ explicit | ✅ adopted (Phase C0) |
| Data readiness gates | ✅ explicit | ✅ adopted (Phase C1.5) |
| Conservative initial weights | ✅ 0.10/0.15 | ✅ adopted |
| A1/A2 prerequisite | ✅ implied | ✅ adopted (Section 2) |
| Form 4 > 13F priority | ✅ explicit | ✅ adopted (fusion v2 weights) |
| ETF PIT requirement | ✅ explicit | ✅ adopted (Phase C5) |
| Auto-promotion timing | ✅ "later" | ✅ adopted (Phase C8 last) |
| Regime multipliers | ❌ not proposed | ✅ retained (Phase C9, with safety) |
| Industry sector tilt | ❌ not proposed | ✅ retained (Tier 7, smaller weight) |
| Dynamic ETF discovery | ❌ not proposed | ✅ retained (deferred to Phase C5+) |
| Confidence formula | ❌ not specific | ✅ retained `sqrt(obs/1000)` |
| After-service C7 (alerts, drift) | ❌ minimal | ✅ retained |
| Smart Money Top30 = watchlist | ✅ explicit | ✅ adopted (no auto-buy) |
| Evidence fusion v2 formula | ✅ explicit weights | ✅ adopted |

**Verdict**: ChatGPT's governance + conservatism is correct and adopted. My regime/industry/discovery infrastructure adds independent alpha sources that ChatGPT didn't propose. v2 = ChatGPT's safety + my breadth.

---

## 14. What Did NOT Change

- 2-axis sector framework (signal + industry)
- 5-state regime classifier
- 6-scenario A/B matrix (extended to 7 with G = + regime mult)
- After-service infrastructure
- Smart Money Top30 standalone product
- ETF 3-layer concept (17 + 8 thematic + dynamic top-30)
- IC-based weight learning formula
- Confidence factor calculation
