# Phase 8 Proposal — CAGR 15 → 25-30% Restructuring

**Date**: 2026-04-17
**Based on**: `DIAGNOSIS_FACTOR_IC.md`, `DIAGNOSIS_COUNTERFACTUAL.md`, `DIAGNOSIS_BUGS.md`
**Goal**: Raise main-portfolio CAGR from 15.44% to 25-30%+ over 83-month backtest, while keeping or improving Sharpe / MaxDD.

---

## Why Phase 1-7 fell short — the short version

1. **59% of our 258 factors are pure noise** (IC ∈ [-0.01, +0.01]). They dilute the composite via `row_mean`'s 1/N averaging.
2. **12 factors have negative IC**, including Phase 2's `industry_rotation_signal` (IC -0.012). They're actively HARMFUL.
3. **Phase 5's sub-industry leader/laggard has zero alpha** (IC near 0). Dilution fix from c4d50fd doesn't rescue the underlying signal.
4. **Fundamental factors have 2-4x stronger IC at r_12m than r_1m**. But we train on r_1m and rebalance monthly — structurally wired for short-term noise.
5. **Our final `score` has IC +0.011 at r_1m but -0.006 at r_12m** (negative). We systematically rank names that look good short-term but bad long-term.
6. **NVDA ranked 9 → 17 → 18 → 23 during its biggest months (Oct 2023 - Jan 2024)**, then jumped to rank 1 in Mar 2024 (AFTER the parabolic move). Our ranking is lagging, mean-reverting.
7. **Turnover 49.5%/month eats 3pp CAGR in costs**.
8. **2024-06 macro bug corrupted 1 month of signals** (1e14-scale values propagated).

---

## Phase 8 scope — 9 changes grouped into 3 sub-phases

### Phase 8a: Signal Sanitation (QUICK_RESCORE measurable)

Fix the wiring without touching the feature store.

1. **8a.1 — Drop 12 negative-IC factors** from all three sleeve weight tables.
   - Remove `quality_trend_score` from core (w=1.00, IC=-0.004)
   - Remove `selection_confirmation_score` from core (w=0.55, IC=-0.003)
   - Remove `industry_rotation_signal` from all sleeves (IC=-0.012)
   - Remove `archetype_defensive_value_score` wherever used (IC=-0.006)
   - Drop the `atr14_pct` exposure on the exit-risk path if it's feeding back into scoring

2. **8a.2 — Disable Phase 5 by default** (`sub_industry_leader_laggard_enabled = False`).
   Factor IC is ~0; keeping it adds schema noise.

3. **8a.3 — IC-proportional reweighting of sleeve weight tables**.
   - `strategy_blueprint_score` (IC 0.017): 0.25 → 1.00 in core
   - `industry_group_strength_score` (IC 0.016): 0.10 → 0.60 in core, 0.30 → 0.80 in future
   - Boost `ep_ttm`, `fcfy_ttm`, `sp_ttm`, `roe_proxy`, `sage_composite_score` weights
   - Reduce or remove factors with |IC| < 0.005 (noise bucket)
   - Target: total per-sleeve L1 unchanged (preserve composite magnitude) but weight distribution aligned with IC

4. **8a.4 — Hold-policy hysteresis**.
   Add score bonus for held names with positive recent return:
   ```python
   held = numeric_series_or_default(d, "held_from_prev_rebalance", 0.0) > 0
   recent_win = numeric_series_or_default(d, "r_1m", 0.0) > 0
   long_trend = cross_sectional_robust_z(d, "mom_12m") > 0
   d["hold_persistence_bonus"] = (
       0.8 * held
       + 0.5 * (held & recent_win)
       + 0.7 * (held & long_trend)
   )
   ```
   Wire this into all three sleeve composites with weight +0.9 (this signal is HIGH conviction — "stuff we already picked AND is working AND has long-term trend").

5. **8a.5 — Macro bug fix** (2024-06 corruption).
   - Clamp macro scores to `[-5, 5]` at end of `compute_macro_regime_features`
   - Add divide-guard to `sahm_scaled` / `hy_oas_change_z` if denominator < 0.001
   - Tighten `hard_sanitize` default clip from 1e12 to 1e4

**Runtime**: 1-2h code, 20min QUICK_RESCORE measurement.
**Expected CAGR gain**: **+4 to +6pp** → 19-21%.

---

### Phase 8b: Long-horizon alpha capture (FULL REBUILD required)

Structural: feed the engine LONG-HORIZON signal and LONG-HORIZON training.

6. **8b.1 — Add long-lookback momentum features**.
   - New columns: `mom_18m`, `mom_24m`, `mom_36m`
   - New composite: `multi_year_winner_score = z(mom_12m) + 0.8*z(mom_24m) + 0.6*z(mom_36m)` (weighted average of multi-year compounded returns)
   - New flag: `persistence_trend_24m = (mom_12m > 0.15) & (mom_24m > 0.30) & (mom_36m > 0.50)` (3-year persistent up-trend)
   - Wire into `future_winner` and `early_scout` sleeves at weight 0.6-0.8 (both dominated by short momentum factors currently)

7. **8b.2 — Train walk-forward ML on r_12m target instead of (or in addition to) r_1m**.
   - Add a second ensemble `ensemble_12m` trained on `r_12m` forward return
   - Blend `score_model_12m` into final score at 50% weight alongside existing `score_model_1m`
   - Rationale: r_12m target has 2.4x stronger IC on fundamental factors, and directly captures NVDA-style multi-year winners

8. **8b.3 — Fix Phase 1 keepcols bug**.
   - Add `PHASE1_ALPHA_COLUMNS` constant listing 5 Phase 1 columns
   - Append to `build_feature_store.keep_cols` whitelist
   - Bump `ENGINE_REUSE_VERSION` to force regeneration
   - Rationale: Phase 1 columns never reached the walk-forward scoring path (same class as the Phase 2 keepcols-fix). Without this, Phase 1 alpha = 0.

**Runtime**: 2-3h code, 3h FULL rebuild.
**Expected CAGR gain (on top of 8a)**: **+4 to +7pp** → 23-28%.

---

### Phase 8c: Aggressive position sizing for confirmed winners (QUICK_RESCORE)

9. **8c.1 — Force `future_winner` sleeve for mega-cap + high-growth + multi-year trend**.
   Override sleeve label when:
   ```python
   force_future_winner = (
       (market_cap_live > 50e9)
       & (revenue_growth_final > 0.25)
       & (multi_year_winner_score > 1.0)
   )
   ```
   This moves NVDA / AVGO / MU / AMD out of `core_compounder` (12% allocation) into `future_winner` (58% allocation) where they deserve to be based on their momentum profile.

10. **8c.2 — Growth-adjusted valuation** (dampen value penalty when growth is extreme).
    - If `revenue_growth_final > 0.40`: `forward_value_score_penalty *= 0.0` (skip)
    - If `revenue_growth_final > 0.20`: `forward_value_score_penalty *= 0.5`
    - Rationale: NVDA E/P 0.05 gets penalized, but 50% revenue growth justifies the premium. Current engine treats them as unrelated.

**Runtime**: 1h code, 20min QUICK_RESCORE.
**Expected CAGR gain (on top of 8b)**: **+2 to +4pp** → 25-32%.

---

## Ship gate

Each sub-phase has a QUICK_RESCORE (8a, 8c) or FULL (8b) measurement against baseline. A sub-phase ships only if:
- ΔCAGR ≥ +2pp
- ΔSharpe ≥ 0
- ΔMaxDD ≤ +3pp

If a sub-phase fails, roll back and move to the next. (8a failure is unlikely — it's mostly dropping negatively-measured factors.)

---

## Execution order

```
Step 1: Phase 8a (~2h code + 20min QUICK_RESCORE)  [safe, high-confidence]
        Target: CAGR 15.44% → 19-21%

Step 2: Phase 8c (~1h code + 20min QUICK_RESCORE)  [depends on 8a, high-confidence]
        Target: 19-21% → 22-25%

Step 3: Phase 8b (~3h code + 3h FULL rebuild)      [structural, medium-confidence]
        Target: 22-25% → 25-30%+
```

Total commit & measurement time: ~7-8 hours active work, spread over 2 Colab runs. Most of the window is waiting for the FULL rebuild in step 3.

---

## What will be RETAINED vs REMOVED from existing phases

| Phase | Retention | Reason |
|---|---|---|
| Phase 1 (turnaround/value/uptrend) | **RETAIN + FIX** | Bug 2 needs fix; then A/B-measure real IC |
| Phase 2 (industry RS + O'Neil) | PARTIAL RETAIN | Keep `industry_group_strength_score`; drop 9 noise + 1 negative |
| Phase 3 (sleeve renorm) | DROP from mainstream | Already REJECTED |
| Phase 4 (regime-conditional) | DEFER | Test after 8a/8b/8c land |
| Phase 5 (leader/laggard) | **DROP** | Factor IC zero; disable by default |
| Phase 6a/6b (DD breaker + VIX guard) | RETAIN | Essentially dormant (avg_cash 0.3%); low downside |
| Phase 6c (vol target) | DEFER | A/B pending |
| Phase 7a (insider + accruals) | DEFER | A/B pending |

---

## Risks

1. **r_12m training target risk**: models trained on long-horizon may over-fit to a specific regime (growth era 2019-2024). Mitigation: blend both 1m and 12m models, not replace.

2. **Phase 5 disable risk**: although factor IC is zero, there may be second-order interactions with other phases. Mitigation: Phase 5 is gated by cfg flag and env var; easy to re-enable if A/B shows collateral damage.

3. **Sleeve force-reclassification risk**: moving NVDA from core to future increases concentration (future sleeve gets 58% of portfolio across fewer names). Mitigation: widen `future_winner_sleeve_names` from 7 to 10; keep core at 12% for defensive ballast.

4. **Growth-adjusted valuation risk**: removing value penalty for high-growth names could increase exposure to bubble-valued names at peaks. Mitigation: combine with breakdown penalty so names collapsing still get cut.

5. **"IC ≠ CAGR" risk**: high factor-level IC doesn't always translate to portfolio CAGR. Mitigation: Grinold-Kahn IR scaling in DIAGNOSIS_COUNTERFACTUAL.md §3 gives conservative estimate; real deployment needs A/B verification.
