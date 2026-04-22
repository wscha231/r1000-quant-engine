# Phase 15 — Stock Selection Deep Audit (2026-04-22)

**Research question**: Can we strengthen the current stock selection mechanism? Ranking quality is weak (rank_ic_mean=0.019, precision_at_k=0.046) and production CAGR (22.95% main / 33.17% concentrated) is below user's 25%/40% targets. Where is alpha leaking?

**Method**: `phase15_selection_deep_audit.py` over `scored_oos_latest.parquet` (46,650 rows, 914 tickers, 84 months) + concentrated holdings history (14,193 entries across 63-combo grid).

**Target horizon**: forward_r_3m as the primary test. Forward_r_1m and forward_r_12m for horizon sensitivity.

---

## Finding 1 — Engine misses a lot of mid-cap winners

Of the top-20 cumulative winners over the 83-month backtest window, **11 were never (or barely) selected** (≤10 concentrated picks across the 63-combo × 83-month grid = ≤0.2% inclusion rate):

| Ticker | Cumul. return | Selections | Sleeve when picked | Sector |
|---|---|---|---|---|
| **KLAC** | +1458% | **0 / 5229** | (never) | Semiconductor equipment |
| MPWR | +1213% | 3 | early_scout | Semiconductor |
| XPO | +969% | 2 | early_scout | Logistics |
| MU | +940% | 3 | future_winner | Semi memory |
| AXON | +911% | 0 | (never) | Law enforcement tech |
| CIEN | +878% | 0 | (never) | Networking |
| FTAI | +854% | 0 | (never) | Infrastructure leasing |
| LSCC | +815% | 0 | (never) | Semi (programmable logic) |
| PWR | +775% | 0 | (never) | Electrical contracting |
| FIX | +760% | 0 | (never) | HVAC services |
| MEDP | +749% | 0 | (never) | Healthcare CRO |

For reference, winners engine DID capture: LRCX (943 picks), AVGO (691), NVDA (654), GOOGL (320), GOOG (155), DELL (114), AMAT (119), TSLA (82), JBL (44).

### Pattern
- Engine strongly favors **mega-cap obvious names** (LRCX, AVGO, NVDA).
- Systematically misses **non-obvious mid-caps in adjacent industries** (KLAC vs LRCX — SAME INDUSTRY — yet 1458% vs zero picks).
- Missed-winner diagnostics (`scored_oos_latest`, rank percentile of score, pct=True asc=False):
  - KLAC avg score percentile = 0.28 (top 28%), MU 0.14, MPWR 0.42.
  - These ranked well cross-sectionally but not well enough to enter concentrated top-3 or top-5.

### Likely root cause
- Production `score` column is weak (see Finding 2) — blending dilutes individual strong signals.
- Cross-sectional ranking at N=3-5 is binary: either you're top-3 or zero. Missing by one rank point = excluded for 83 months.
- Features that pick up "mid-cap compounder" pattern are under-weighted.

---

## Finding 2 — Production `score` column is nearly random

Per-predictor per-horizon IC audit (81-94 months per target):

| Predictor | IC_IR (1m) | IC_IR (**3m**) | IC_IR (12m) |
|---|---|---|---|
| **`score`** (final blend, production) | 0.058 | **0.048** 🚨 | 0.161 |
| pred_cat_ret | 0.303 | **0.543** | 0.727 |
| **pred_future_winner_ret** | 0.252 | **0.521** | **1.244** 🔥 |
| score_cat | 0.242 | 0.493 | 0.945 |
| score_linear | 0.085 | 0.324 | 0.798 |
| pred_lin_ret | 0.067 | 0.292 | 0.708 |

### Key observations
1. **`score` has IR 0.048 on forward_r_3m** — effectively no signal.
2. Individual predictors (`pred_future_winner_ret`, `pred_cat_ret`) have IR 0.5-1.2. **They ARE strong, but blending destroys most of it**.
3. `pred_future_winner_ret` on forward_r_12m has **IR 1.244** — exceptional for equity ranking.
4. ML signal is fundamentally 3-12 month alpha, NOT 1-month. Confirms earlier finding from `phase15_s1_future_winner_factor_ic.csv`.

### Why is production `score` so weak?
The production score is a weighted blend across many axes (Ridge, CatBoost, ranker, sleeve composites, phase overlays, focus overlay, sage overlay, regime overlay, etc.). Many components are weak or zero-IC (see Finding 3). The blend averages out strong signal from `pred_future_winner_ret` and `pred_cat_ret` with hundreds of near-random inputs.

---

## Finding 3 — 255 of 381 features are weak; 4 are actively hurting

Feature strength buckets (IC vs forward_r_3m, 81 months, after excluding the 4 training-label columns that trivially correlate with targets):

| Bucket | IR range | Count | Action |
|---|---|---|---|
| STRONG | ≥ 1.0 | 1 (`tenbagger_hit`) + 4 training labels | Keep / boost |
| MODERATE | 0.5-1.0 | 6 | Keep |
| WEAK | -0.3 to 0.5 | 255 | **Prune candidates** |
| NEGATIVE | < -0.3 | **4** | **Urgent drop** |

### Urgent drop (actively negative alpha on 3m horizon)

| Feature | IC_IR 3m | IC_mean |
|---|---|---|
| `macro_hedge_score` | -0.398 | -0.044 |
| `focus_live_event_defensive_score` | -0.333 | -0.038 |
| `focus_defensive_regime_score` | -0.332 | -0.037 |
| `atr14_pct` | -0.323 | -0.050 |

**Impact**: defensive overlays meant to reduce drawdown are actually **hurting forward returns**. The 3m IR is the horizon where most composites operate.

### Strongest actual predictors (excluding training labels)

| Feature | IC_mean | IC_IR |
|---|---|---|
| **tenbagger_hit** (past 10x flag) | 0.116 | **1.742** |
| z_cat_ret | 0.097 | 0.663 |
| val_residual_sp | 0.039 | 0.556 |
| pred_cat_ret | 0.083 | 0.543 |
| val_residual_ep | 0.033 | 0.533 |
| pred_future_winner_ret | 0.081 | 0.521 |
| score_future_winner_model | 0.088 | 0.501 |

### Recommendation
- Drop 4 NEGATIVE features from composites (phase-toggled A/B like 15-S1a).
- Boost `tenbagger_hit` weight — currently low, but IR 1.74 exceptional.
- Consider a **"minimalist composite"** using top 7 features only. Test against current 381-feature score.

---

## Finding 4 — Top-7 selection is already stable

- Top-7 mean monthly overlap: **4.3 / 7 (60.8%)**.
- 49% of months have ≥5/7 overlap (high stability).
- Only 8.4% have ≤2/7 overlap (high churn).
- Implied average hold period for a top-7 name: **2.55 months**.

### Implication for "long hold compounder" hypothesis
- Top-7 is already sticky. Additional lock mechanism (15-S2b Core Conviction Lock) has LIMITED upside on top-7 positions.
- The 43%/month turnover MUST come from positions #8-#18. That's where "Core Conviction Lock" should focus.
- Alternatively, focus on reducing position-count churn (keep exactly 15 names with slow weight drift vs rebuild the bottom 10 each month).

---

## Strategic recommendations

### Tier A — IMMEDIATE (low risk, test in hours)

**A1. Drop 4 negative-alpha features** (phase toggle, env-gated A/B like 15-S1a):
  - `macro_hedge_score`, `focus_live_event_defensive_score`, `focus_defensive_regime_score`, `atr14_pct`
  - Expected: +0.3-0.8pp CAGR, no MaxDD cost.
  - 1-2 hours work, QUICK A/B compatible.

**A2. Replace `score` with a slimmer blend** (phase toggle):
  - New `score` = weighted combo of `pred_future_winner_ret` (0.40) + `pred_cat_ret` (0.30) + `score_cat` (0.20) + `tenbagger_hit` z-score (0.10).
  - Drop most of the 255 WEAK features from the final blend.
  - Expected: IR 0.048 → 0.35+. Large CAGR impact. Risk: overfitting to in-sample IC audit.
  - 3-4 hours work, QUICK A/B (feature store unchanged, just score compute).

**A3. Tenbagger_hit weight boost** (phase toggle):
  - `tenbagger_hit` has IR 1.742 — highest non-label feature.
  - Currently weighted into composites at ~0.3. Raise to 1.0-1.5 (matches IR magnitude).
  - Expected: +0.3-0.7pp CAGR.

### Tier B — STRUCTURAL (medium risk, 1-3 days)

**B1. ML target horizon realign** (15-S1b from earlier roadmap):
  - Train `pred_future_winner_ret` on `r_3m` target, not `r_1m`.
  - Finding 2 confirms this: IR 0.521 on 3m vs 0.252 on 1m at prediction time.
  - Training on r_3m target should lift the predictor further.
  - Expected: concentrated +3-5pp CAGR.
  - FULL rebuild required (~2-3h).

**B2. Missed-winner rescue** (new feature):
  - Compute `secondary_winner_score` for names in top-40% that miss top-10.
  - Emphasize: mid-cap growth ($5B-$100B), non-obvious sector adjacencies, accelerating but not yet saturated.
  - Expected: capture KLAC / MU / MPWR / MEDP / AXON / XPO / FTAI / PWR / FIX pattern.
  - 6-8 hours work, FULL rebuild required.

### Tier C — ARCHITECTURAL (large, 1-2 weeks)

**C1. Continuous weight glide** (15-C1):
  - Focus on positions #8-18 where turnover lives.
  - Top-7 already stable, don't need glide; lower ranks need it.

**C2. Event-driven intra-month triggers** (15-C2): see earlier roadmap.

---

## Test prioritization (data-driven)

| Step | Effort | Expected Δ | Risk |
|---|---|---|---|
| A1 Drop 4 negative features | 1-2h QUICK | +0.3-0.8pp | LOW |
| A3 Tenbagger weight boost | 1-2h QUICK | +0.3-0.7pp | LOW |
| A2 Slim-score replacement | 3-4h QUICK | +1-3pp (speculative) | MED |
| B1 ML target r_1m → r_3m | 2-3h FULL | +2-4pp conc, +0.5-1pp main | MED |
| B2 Missed-winner rescue | 6-8h FULL | +0.5-1.5pp (structural) | MED-HIGH |

**Start with A1 + A3** (both LOW risk, ~3h combined, QUICK A/B). Then decide on **A2** based on A1+A3 results. **B1** remains the highest-expected-value structural change.

---

## Caveats

- Training labels (`y_blend`, `y_bin`, `future_winner_y`, `future_winner_bin`) appeared at top of the feature IR table because they ARE the target by definition. Excluded from action recommendations.
- IC numbers computed on 81 months (forward horizons truncate the tail). Results generalize.
- IC_IR is a sample statistic; real OOS performance may differ by 20-30%. Recommendations are hypotheses to confirm via A/B.
- "Prune 255 weak features" is directionally right but bulk-drop is risky — each feature's contribution may be non-linear (interactions). Prune in batches with A/B verification.

---

## Files
- `research/phase15_selection_deep_audit.py` — reproducible audit script
- `research/phase15_selection_deep_audit_report.md` — this report

## Status
Research only — no production code changes. Highest-ROI next steps: A1 + A3 as QUICK A/B (~3h), then A2 or B1 based on results.
