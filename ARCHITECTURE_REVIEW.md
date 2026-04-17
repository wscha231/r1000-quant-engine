# Architecture Review — First-Principles Cold Assessment

**Date**: 2026-04-17
**Author**: Claude (session 5, 2-day Phase 8 project)
**Purpose**: Honest, ruthless evaluation of whether the current architecture is sound or has drifted into over-engineering. Written in response to the user asking "cold assessment" after 2 days of Phase 8 work.

---

## 1. Executive summary

**Verdict**: The system is **structurally sound but bloated**. The core architecture (layers) is well-designed for an institutional-grade quant engine. The problem is accumulated factor-level bloat and dead-phase code debt.

- 258 factors measured → 9% have real alpha, 59% are noise, 5% are negative
- 27,000+ lines → ~8-10k lines of genuine value + ~15-17k of cruft
- Phase 3 rejected / Phase 5 default-OFF / Phase 7a default-OFF → their infrastructure is still in the repo (~1,100 lines of inactive code)
- Final score IC (0.011) is LOWER than best single factor IC (0.026) — the composite is diluting the signal

**Recovery path**: Not a rewrite. A three-pass cleanup: **Measure (done) → Refactor (REFACTOR_PLAN) → Subtract (Phase 9)**.

---

## 2. Inventory — what we have

### 2.1 Healthy structural pillars (keep ALL)

| Pillar | Why it's good |
|---|---|
| PIT-safe fundamental merge (`accepted` timestamp) | Hardest part of quant to implement; we did it right. |
| Walk-forward training with 126-day embargo | Standard anti-lookahead discipline. |
| Universe construction (R1000 historical membership) | 8.8% drop rate is normal; no unusual survivorship bias. |
| Operator / backtest layer separation | Enables real-money deployment without tangling research code. |
| Walk-forward ML ensemble (Ridge + CatBoost + Ranker) | Good diversification across model types. |
| CHANGELOG under Agent Update Contract | Every commit's motivation is traceable. |

These 6 pillars are the **institutional-grade spine**. They are worth preserving even if everything else gets rewritten.

### 2.2 Factor bloat (biggest problem)

From `DIAGNOSIS_factor_ic.csv` (258 factors, 83 OOS months):

| IC bucket | Count | % | Verdict |
|---|---|---|---|
| IC > +0.02 (real alpha) | 22 | **8.5%** | Keep, boost weight |
| IC in [-0.01, +0.01] (noise) | 153 | **59.3%** | Drop |
| IC < -0.01 (negative) | 12 | **4.7%** | Remove or reverse |
| Uncategorised / low coverage | 71 | 27.5% | Audit |

**Interpretation**: We have been adding factors hopefully-additively. Most don't add alpha. Some actively hurt.

### 2.3 Phase-level accretion

| Phase | Status | Code footprint | Empirical value |
|---|---|---|---|
| 1 (alpha signals) | Active (8b.3 keepcols fix) | ~500 lines | Never measured (was dropped from feature_store until today) |
| 2 (industry RS + O'Neil) | Active | ~1,500 lines | 1/11 signals have alpha, 1/11 is negative |
| 3 (sleeve renorm) | **REJECTED** | ~500 lines | ΔCAGR -2.30pp |
| 4 (regime multipliers) | default OFF | ~600 lines | Never A/B measured |
| 5 (sub-industry leader/laggard) | default OFF (was ON, failed) | ~400 lines | IC = 0, dilution fix couldn't save it |
| 6a (drawdown breaker) | Active, dormant | ~600 lines | avg_cash_weight 0.3% (never fired) |
| 6b (VIX guard) | Active, dormant | ~400 lines | Same — didn't fire in backtest |
| 6c (vol targeting) | default OFF | ~500 lines | Never measured |
| 7a (insider + accruals) | default OFF | ~400 lines | Never measured |
| 8a.1-8a.5 | Active | ~800 lines | Being measured now |
| 8b.1/8b.3 | Active | ~600 lines | Being measured now |
| 8c.1/8c.2 | Active | ~400 lines | Being measured now |
| 8d.1/8d.2 | Active | ~400 lines | Being measured now |

**~1,100 lines are DEAD CODE** (Phase 3 rejected + Phase 5 default-OFF + Phase 7a default-OFF). We keep them "in case we revisit" but they actively hurt navigation and agent comprehension.

### 2.4 Sleeve composite — the real structural weakness

Each of 3 sleeves has 20-30 `(weight, factor_z_score)` pairs combined via `row_mean`. Current sums-of-absolute-weights:

| Sleeve | Term count | L1 weight sum | Effective weight per term |
|---|---|---|---|
| Core | ~21 | 8.52 | ~0.05 |
| Future | ~32 | 16.24 | ~0.03 |
| Early | ~31 | 13.79 | ~0.03 |

**Problem**: with 20-30 terms per composite, even a factor with strong IC (0.026) contributes only ~0.05 × 0.026 = 0.0013 per unit z. The **best factor is drowned in the bath**.

**Math check**: `row_mean` = `sum / count_of_non_NaN`. When we weight a factor at 0.5 and it goes alongside 19 other factors also at weight 0.5, each factor gets 1/20 effective weight = 0.025. This is why even IC 0.026 → final IC 0.011.

Phase 8a.1 (drop negative-IC) and Phase 8d.1 (boost 2 high-IC) are Band-Aids on this structural problem. The real fix: **far fewer factors per sleeve**.

---

## 3. First principles — what does a quant stock picker need?

### 3.1 Minimum viable system (academic-style)

```
1. Universe (R1000-ish) — 600-800 tickers, 10-15y history
2. 10-15 carefully-chosen factors with measured positive IC
3. IC-weighted composite (recomputed every 6-12 months)
4. Top-N selection (20-30 names)
5. Equal-weight or conviction-weight allocation
6. Monthly rebalance with turnover cap
7. Simple risk overlay (VIX spike → reduce exposure)
```

This is ~2,500 lines of code. Expected CAGR: **18-22%** based on typical factor IC.

### 3.2 Institutional-grade extensions (justified complexity)

Our system adds:
- PIT-safe fundamental processing (necessary for real deployment)
- Walk-forward ML ensemble (necessary to capture non-linear interactions)
- Live vs research portfolio separation (necessary for operator role)
- Dynamic sleeve allocation (useful for regime adaptation — but currently overengineered)

These are legitimate upgrades. Justified code: maybe **8,000-10,000 lines**.

### 3.3 What we ACTUALLY have: ~27,000 lines

The gap (~15,000-17,000 lines) is:
- 258 factors, 227 of which are noise or negative (→ most of the `features/` code is waste)
- 3 sleeve composites each with 30 weight-pairs (→ `sleeves/composite.py` is 2-3x too large)
- Phase 3/5/7a dead code
- 5 different latest-scoring paths (walk-forward / score_latest_month / prepare_latest_scored_data / build_feature_store-internal latest-scoring / concentrated scorer)
- 49 macro columns, most of which are interaction terms with low IC

---

## 4. Structural issues (not bug-level)

### 4.1 Sleeve composition is at factor-level, should be at position-level

**Current**:
```
raw factors
  → 3 sleeve composites (20-30 factors each, row_mean)
  → 3 sleeve scores per stock
  → argmax → sleeve_label per stock
  → dynamic sleeve allocation (core 12% / future 58% / early 22%)
```

**Better**:
```
raw factors
  → ML ensemble
  → single ranking score per stock
  → top-N selection (conviction-weighted)
  → apply sleeve LABEL as exposure categorisation (NOT score weight)
  → regime-conditional position sizing at the PORTFOLIO LEVEL
```

The difference: in current, "future_winner score" and "core_compounder score" are FACTOR composites with 30 weights each. In the better design, sleeve is purely categorical — it says "this name looks like a future winner" but doesn't re-weight the factors.

Why the current design is worse: tuning 60-90 factor weights (30 × 3 sleeves) is high-dimensional noise. Tuning "core/future/early portfolio weights" (3 numbers) is low-dim and interpretable.

### 4.2 ML trained on r_1m creates myopia

Already known (Phase 8e deferred). Phase 8d.2 `long_horizon_alpha_composite` is a partial workaround.

### 4.3 No explicit risk model

Barra-style factor risk model would tell us:
- This stock has beta 1.3, momentum loading 0.8, value loading -0.5
- Our top-30 portfolio has sector concentration 40% tech vs 15% benchmark

Currently we rely on ad-hoc diversification + sleeve allocation. A proper risk model would flag over-concentration before it becomes a drawdown.

**Scope**: out of scope for now (adds ~3-5k lines). Note for future.

### 4.4 Turnover is post-hoc, not optimised

We have `turnover_cap_monthly: float = 0.55` as a CAP but selection doesn't OPTIMISE for turnover. Net effect: 49.5% monthly turnover eating 3pp CAGR in costs. Phase 8a.4 hold persistence bonus is a partial fix, not a turnover-optimal selection.

### 4.5 No factor stability test across sub-periods

IC measurement is aggregate over 83 months. But a factor that had IC 0.05 in 2019-2022 and IC -0.02 in 2023-2026 would still show IC 0.02 on average. We'd weight it positively today even though it's turned negative.

**Fix**: per-year IC measurement + regime-conditional IC. Flag factors with regime instability.

**Scope**: could be a small addition to Phase 8d (~1 day work).

---

## 5. What drifted wrong in the last 2 days (and since Phase 1)

### 5.1 "Add first, measure later" pattern

Phase 1 → 2 → 3 → 4 → 5 → 6 → 7 were all implemented BEFORE measuring factor IC. Phase 3 and 5 would have been SKIPPED if we'd measured first (IC -2.30pp A/B for Phase 3; IC 0 for Phase 5).

**Rule for future**: every new signal must have a measured IC on historical data BEFORE committing to code. Phase C diagnosis (`027c5b3`) established this should be the default workflow. It wasn't before.

### 5.2 Phase accretion without phase deletion

When Phase 3 was rejected, we kept the infrastructure (`weighted_sleeve_composite` renorm path, `sleeve_weight_l1_norm`, 3 diagnostic columns, 2 cfg fields). Same for Phase 5 / Phase 7a. Each rejected phase adds ~500-1000 lines that no longer serve the pipeline.

**Rule for future**: phase rejection should trigger deletion, not just default-OFF. If we truly want to revisit, the git history preserves it — `git log --all -- r1000_top30_institutional.py` is better than a permanent dead-code scar.

### 5.3 Over-coupling of signal composition + portfolio construction

The sleeve composite handles BOTH:
1. Alpha signal aggregation (factor weights)
2. Portfolio role classification (which sleeve a name belongs to)

These are conceptually separate. Mixing them means tuning either one interferes with the other.

### 5.4 Factor count vs data pipeline stability trade-off

Every added factor:
- Expands the feature_store schema
- Adds a keep_cols entry (or a bug if missed, like Phase 1/2 keepcols-fix)
- Adds a phase toggle + env var + cfg field + zero-placeholder
- Participates in row_mean dilution
- Requires docstring + review

Incremental cost per factor: ~50 lines of scaffold. 258 factors → ~13k lines of scaffold alone.

---

## 6. What's NOT wrong (don't throw out)

Before proposing cuts, let's be clear on what's WORKING:

1. **The data layer** is excellent. PIT, survivorship, embargo all correct.
2. **The ML ensemble** is reasonable (Ridge + CatBoost + Ranker). Individual model IC 0.038-0.045 is decent.
3. **The operator separation** is a hard-to-replicate asset.
4. **The Phase 6a/6b tail protection** is built correctly even if dormant — it's insurance for future regimes.
5. **The Phase 8 foundation** (IC-first approach, sparse signal masking, long-lookback momentum, megacap override, growth-adjusted valuation) is CORRECT direction, just needs stabilisation.

---

## 7. Phase 9 proposal — "Subtractive" mode

After Phase 8 ships (CAGR ≥ 25%) and refactor Phase A completes, execute a ruthless cleanup pass.

### 7.1 Targets

| Category | Current | Target | Delta |
|---|---|---|---|
| Total lines | 27,000 | 12,000-15,000 | -12k to -15k |
| Factors | 258 | 30-40 | -218 |
| Sleeve composite weight-pairs per sleeve | 20-32 | 8-12 | -60% each |
| Phase toggles | 16 | 8-10 | -6 to -8 |
| Cfg fields | ~100 | ~50 | -50 |

### 7.2 Specific cut list

**DELETE entirely** (no default-OFF — fully remove):

1. Phase 3 renorm path + `weighted_sleeve_composite` renorm branch + 3 diagnostic columns + `sleeve_weight_renorm_enabled` cfg field + `sleeve_weight_l1_target` cfg field (~600 lines)
2. Phase 5 `add_sub_industry_leader_laggard_signals` + 3 columns + keepcols entries + toggle + dilution-masking code in `compute_portfolio_sleeve_columns` (~400 lines)
3. Phase 7a insider/accruals wiring if A/B shows no alpha (~200 lines) — DECIDE after Phase 7a A/B
4. Macro interaction factors with IC < 0.005 (~20-30 columns, ~800 lines)
5. Archetype scores with IC 0 (`archetype_cyclical_recovery_score`, `archetype_defensive_value_score`) (~300 lines)
6. `macro_hedge_score`, `leader_safety_score`, `dividend_payout_ratio` usage as features (negative IC) (~200 lines)
7. Latest-only signal factors with IC 0 (~40 columns, ~1,500 lines)
8. Zero-placeholder fallbacks for deleted phases (~300 lines)

**Estimated lines removed: 4,000-5,000**.

**SIMPLIFY** (replace, not delete):

9. Sleeve composite: consolidate 6 industry signals into one `industry_composite`; 3 revision signals into one; 3 growth-onset signals into one (~500 lines → ~150 lines)
10. Collapse 5 latest-scoring paths into 1 (walk-forward latest / score_latest_month / prepare_latest_scored_data all re-derive similar state) (~1,500 lines → ~600 lines)
11. SAGE sub-scores: keep composite, drop individual g/v/q/c weights in sleeve tables (was double-counting) (~200 lines)

**Estimated lines reduced by simplification: 1,500-2,500**.

### 7.3 What we KEEP and strengthen

1. All 22 real-alpha factors (IC > 0.02) with proportionally-boosted weights
2. Phase 1 alpha (after this run's IC measurement confirms value)
3. Phase 6a/6b (cheap insurance)
4. Phase 8a.4 hold persistence (confirmed turnover reduction)
5. Phase 8b long-lookback momentum (measured)
6. Phase 8d.2 long-horizon alpha composite (measured)
7. Entire ML ensemble (Ridge + CatBoost + Ranker)
8. Operator + portfolio state layer
9. PIT-safe fundamentals + PIT audit
10. Walk-forward + embargo discipline

### 7.4 Execution window

Phase 9 is a **3-day focused session**:
- Day 1: Delete dead phases (Phase 3/5/maybe7a) + low-IC factors
- Day 2: Simplify sleeve composites + collapse latest-scoring paths
- Day 3: A/B verify: byte-exact `backtest_metrics.json` on identical toggle set OR CAGR ≥ previous ship baseline

---

## 8. Decision framework — keep vs cut criteria

For every factor / phase / module, ask:

```
1. Has it been MEASURED (IC on historical data, not just "should work")?
   NO  → MEASURE FIRST, decide in next pass
   YES → go to 2

2. Is measured |IC| > 0.01 (10 bps of rank correlation with forward return)?
   NO  → CUT (or require a structural reason to keep)
   YES → go to 3

3. Does it add INFORMATION orthogonal to other kept factors?
   NO  → MERGE into existing composite
   YES → go to 4

4. Is the runtime / maintenance cost reasonable?
   NO  → DEFER until infrastructure is lighter
   YES → KEEP with IC-proportional weight

5. Is the code isolated enough to DELETE cleanly if future data invalidates it?
   NO  → REFACTOR before keeping
   YES → done
```

This is a checklist for Phase 9 decisions, and for every FUTURE phase addition.

---

## 9. Rule changes for future development

| Old rule | New rule |
|---|---|
| "Add phase, toggle OFF if underperforming" | "Measure IC first; only add if > 0.01 AND orthogonal" |
| "Keep dead code in case we revisit" | "Delete dead code; git history is the revisit archive" |
| "Factor count = capability" | "Factor quality = capability; count is overhead" |
| "Test after merge" | "Test before merge (unit + IC + A/B)" |
| "Composite with 30 factors captures more" | "Composite with 10 high-IC factors ranks better" |
| "One big file is fine until it breaks" | "Refactor at 5k lines, add observability at 10k" |

---

## 10. Honest self-assessment of the 2-day Phase 8 sprint

### What went well
- Phase C diagnosis (factor IC measurement) — SHOULD have been done at Phase 1.
- Phase 8a/b/c/d are the first phases where "measure → hypothesize → implement → verify" was the actual workflow.
- Review fixes (weight-0 dilution, r_1m lookahead, env name) were caught BEFORE the 3h rebuild.
- REFACTOR_PLAN + Observability plan establish the repair path.

### What didn't go well
- We still added code (Phase 8d composite, megacap override) while the underlying system is bloated.
- We didn't DELETE Phase 3/5/7a infrastructure while we were in the codebase.
- We wrote 14 commits of Phase 8 work without pausing to question whether Phase 8 itself is the right direction vs. Phase 9 Subtractive.
- The expected CAGR range (25-30%) may be achievable OR may still be held back by the 258-factor bloat — we'll know in 3 hours.

### What the user's cold-assessment question is really asking
Is this 2 days of work adding to a good system or making a complicated system MORE complicated?

**Honest answer**: a bit of both. The IC-data-driven approach of Phase 8 is correct. But the addition of 3-5 more knobs to an already-27k-line system isn't the highest-leverage move anymore. The highest-leverage move is **Phase 9 Subtractive** — drop to 12-15k lines of code, keep only alpha-proven factors, make the sleeve composite sane.

---

## 11. Recommended path forward

```
[NOW]   Phase 8 FULL rebuild runs (~3h)
  ↓
[+3h]   Cell E verdict
  ↓
[+4h]   Review: which Phase 8 sub-phases measurably helped?
  ↓
[+1d]   Refactor Phase A (5 modules + facade + observability + tests)
        Observability catches any refactor regressions immediately
  ↓
[+2d]   Phase 9 Subtractive execution
        - Delete Phase 3 / 5 / 7a infrastructure
        - Delete low-IC factors (153 columns → ~20 columns)
        - Consolidate redundant composites (industry cluster, revision cluster, growth-onset cluster)
        - Simplify sleeve composites to 10 weight-pairs each
        - Verify: byte-exact backtest_metrics.json on identical toggle set
  ↓
[+3d]   Codebase = ~12-15k lines in 5 modules
        Each module understandable by a single agent context
        IC-proven alpha factors only
        Phase 8e (r_12m ML) + Phase 8f (factor cluster consolidation) now feasible
```

**Total cleanup effort**: 3 focused days starting after Phase 8 ships.
**Outcome**: smaller, faster, more maintainable, same or better CAGR (because dilution is reduced).

---

## 12. Closing

The user's instinct to pause and cold-assess was correct and valuable. The system is on the right track **directionally** but has accumulated debt that needs discharge. Two days of Phase 8 work was productive but hit diminishing returns. The next productive step is NOT Phase 8e / 8f (more additions) but Phase 9 Subtractive (deletions) + refactor.

This review doc stays in the repo as a permanent artefact so future sessions (any agent, any human) can trace why we shifted from additive to subtractive mode at this point.
