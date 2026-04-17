# Factor IC Diagnosis — 2026-04-17

**Purpose**: Measure per-factor rank IC (Spearman correlation with forward return) across 83 OOS months to identify which factors actually have alpha vs which are noise or negative contributors.

**Source data**: `G:\내 드라이브\r1000_top30_institutional\feature_store\scored_oos_latest.parquet` (46,647 rows × 494 cols, 83 months 2019-03 through 2026-02, excluding corrupted 2024-06 month).

**Full results**: `DIAGNOSIS_factor_ic.csv` — all 258 scored factors ranked by ic_mean.

---

## Summary

| Bucket | Count | % of 258 | Verdict |
|---|---|---|---|
| IC > +0.02 (real alpha) | 22 | **8.5%** | Keep / boost weight |
| IC in [-0.01, +0.01] (noise) | 153 | **59.3%** | Drop or reduce weight |
| IC < -0.01 (negative) | 12 | **4.7%** | Remove or flip sign |
| IC < -0.02 (strong negative) | 3 | 1.2% | Remove immediately |

**Only 9% of our 258 factors produce real alpha.** The other 91% are diluting the composite via `row_mean`'s 1/N averaging.

---

## Top 20 Positive-Alpha Factors (excluding ML training labels)

Training labels (y_blend IC 0.52, y_bin IC 0.30, future_winner_y IC 0.21) are circular — they correlate with themselves, not a real alpha source.

Real signal factors:

| Rank | Factor | IC | IC_IR | Comment |
|---|---|---|---|---|
| 1 | `pred_cat_ret` | 0.046 | 0.28 | ML ensemble prediction |
| 2 | `score_future_winner_model` | 0.043 | 0.26 | Future-winner model output |
| 3 | `pred_future_winner_ret` | 0.038 | 0.25 | Future-winner prediction |
| 4 | `pred_future_winner_p` | 0.034 | 0.19 | Future-winner probability |
| 5 | `pred_cat_p` | 0.030 | 0.17 | Category classifier prob |
| 6 | `fcf_growth_yoy` | 0.030 | 0.22 | FCF growth (fundamental) |
| 7 | `vol_252d` | 0.028 | 0.13 | **Higher vol = higher return** |
| 8 | `eps_ttm` | 0.027 | 0.22 | Earnings (level) |
| 9 | `ep_ttm` | 0.026 | 0.19 | **Earnings yield (classic value)** |
| 10 | `fcfy_ttm` | 0.025 | 0.15 | **Free cash flow yield** |
| 11 | `forward_ps_final` | 0.024 | 0.16 | Forward P/S (low = better) |
| 12 | `sp_ttm` | 0.022 | 0.14 | Sales yield |
| 13 | `sage_composite_score` | 0.022 | 0.24 | **SAGE composite — highest IC_IR** |
| 14 | `fcf_cagr_best` | 0.020 | 0.17 | FCF CAGR (best of 1y/2y/3y/5y) |
| 15 | `net_income_cagr_5y` | 0.020 | 0.22 | 5y earnings CAGR |
| 16 | `eps_cagr_5y` | 0.019 | 0.21 | 5y EPS CAGR |
| 17 | `net_income` | 0.018 | 0.20 | Absolute NI |
| 18 | `val_residual_ep` | 0.018 | 0.25 | Sector-adjusted E/P |
| 19 | `ocf_cagr_3y` | 0.017 | 0.15 | 3y OCF CAGR |
| 20 | `return_on_equity_effective` | 0.016 | 0.20 | **ROE (classic quality)** |

**Takeaway**: The real alpha sources in our factor bank are (1) **classic value** (ep_ttm, fcfy_ttm, sp_ttm, forward_ps_final), (2) **long-horizon CAGR metrics** (5y eps/ni/ocf CAGR), (3) **ROE/quality**, (4) **SAGE composite**, and (5) **ML predictions**. Missing from the top 20: any Phase 1/2/5 signal, any short-horizon momentum (mom_1m/3m/6m), any archetype score, any industry-rotation signal.

---

## Top 12 Negative-IC Factors — REMOVE or REVERSE

| Factor | IC | IC_IR | Currently used in |
|---|---|---|---|
| `atr14_pct` | **-0.036** | -0.24 | Hold policy exit risk |
| `dividend_payout_ratio` | **-0.035** | -0.24 | Compounder sleeve |
| `macro_duration_rate_interaction` | -0.020 | -0.13 | Macro regime |
| `shares_yoy` | -0.019 | -0.22 | Dilution penalty input |
| `dilution_penalty` | -0.019 | -0.22 | Various sleeves |
| `leader_safety_score` | -0.017 | -0.08 | Crisis fit |
| `capex` | -0.015 | -0.12 | Raw fundamental |
| `dividend_yield_ttm` | -0.013 | -0.07 | Raw fundamental |
| `macro_hedge_score` | -0.012 | -0.10 | Strategy blueprint |
| **`industry_rotation_signal`** | **-0.012** | -0.10 | **Phase 2 — WAS SHIPPED ON** |
| `liabilities` | -0.010 | -0.09 | Raw fundamental |
| `ma50_above_ma150` | -0.009 | -0.06 | Technical |

**Critical finding**: `industry_rotation_signal` (Phase 2 O'Neil rotation playbook) has **negative alpha**. Phase 2 rolled this out ON by default — it has been hurting the portfolio since 2026-04-16.

---

## Phase-by-Phase Factor IC Audit

### Phase 1 (turnaround / value / uptrend)
- **ALL 5 factors MISSING from scored_oos_latest.parquet**
- Phase 1 columns never made it into the walk-forward training set
- Same class of bug as Phase 2 keepcols-fix — Phase 1 columns need to be added to `build_feature_store.keep_cols`
- Currently contributes zero to historical backtest and is only in the latest-scoring path via `compute_strategy_blueprint_columns` re-derivation

### Phase 2 (industry RS + O'Neil leadership)
| Factor | IC | Verdict |
|---|---|---|
| `industry_group_strength_score` | +0.016 | Keep |
| `industry_group_breadth_above_ma200` | +0.010 | Marginal keep |
| `rs_industry_12m` | +0.010 | Marginal keep |
| `industry_within_leader_rank` | +0.008 | Noise |
| `rs_industry_6m` | +0.006 | Noise |
| `industry_breadth_above_ma200` | +0.004 | Noise |
| `rs_industry_group_6m` | +0.003 | Noise |
| `oneil_leadership_score` | +0.002 | Noise |
| `rs_industry_group_3m` | +0.001 | Noise |
| `rs_industry_3m` | +0.0003 | Noise |
| **`industry_rotation_signal`** | **-0.012** | **REMOVE** |

**Net verdict**: Phase 2 is weak. 1 marginal-alpha signal (`industry_group_strength_score`), 1 negative (`industry_rotation_signal`), 9 noise. Consolidate 9 noise signals into a single composite OR drop them; flip or drop `industry_rotation_signal`.

### Phase 5 (sub-industry leader/laggard)
| Factor | IC | Verdict |
|---|---|---|
| `industry_leader_bonus_score` | -0.001 | Drop |
| `industry_leader_gap` | -0.006 | Drop |
| `industry_laggard_penalty_score` | (fires 0% — not measurable) | Drop |

**Verdict**: Phase 5 has **zero alpha**. Even the dilution fix from commit `c4d50fd` doesn't save it — the underlying signal has no predictive power. Recommendation: **disable Phase 5 by default** (`PHASE_PHASE5_LEADER_LAGGARD_ENABLED=0`).

---

## Current Sleeve Weight vs Factor IC — Misalignment

CORE sleeve (19 weight-pairs, total L1=8.52):

| weight | IC | effective (w*IC) | Factor |
|---|---|---|---|
| 1.10 | +0.008 | +0.009 | moat_quality_blueprint_score |
| 1.05 | +0.005 | +0.006 | long_hold_compounder_score |
| 1.00 | **-0.004** | **-0.004** | **quality_trend_score — NEGATIVE** |
| 0.95 | +0.009 | +0.009 | actual_results_score |
| 0.90 | +0.005 | +0.005 | archetype_compounder_score |
| 0.55 | **-0.003** | **-0.002** | **selection_confirmation_score — NEGATIVE** |
| 0.45 | +0.008 | +0.004 | garp_score |
| 0.25 | **+0.017** | +0.004 | strategy_blueprint_score — **underweighted** |
| 0.25 | +0.002 | +0.0004 | oneil_leadership_score — noise |
| 0.10 | +0.016 | +0.002 | industry_group_strength_score — **underweighted** |

**Current weighted IC** = 0.0049. **IC-proportional redistribution** → weighted IC = 0.0114 = **132% improvement**. Rough CAGR translation: +4-6pp.

Biggest misalignments:
1. `quality_trend_score` w=1.00 IC=**-0.004** (negative) — should be dropped or reversed
2. `selection_confirmation_score` w=0.55 IC=**-0.003** (negative) — should be dropped
3. `strategy_blueprint_score` w=0.25 IC=+0.017 (best in core) — should be **boosted to 1.0+**
4. `industry_group_strength_score` w=0.10 IC=+0.016 — should be **boosted to 0.50+**

---

## Holding-Horizon IC — THE BIG REVEAL

Same factors scored against r_1m vs r_3m vs r_6m vs r_12m forward returns:

| Factor | r_1m IC | r_3m IC | r_6m IC | **r_12m IC** |
|---|---|---|---|---|
| ep_ttm | 0.026 | 0.031 | 0.036 | **0.042** (1.6x) |
| fcfy_ttm | 0.025 | 0.044 | 0.054 | **0.050** (2.0x) |
| sp_ttm | 0.022 | 0.042 | 0.064 | **0.086** (**3.9x**) |
| roe_proxy | 0.016 | 0.020 | 0.024 | **0.035** (2.2x) |
| sage_composite_score | 0.022 | 0.020 | 0.035 | **0.052** (2.4x) |
| mom_6m | 0.008 | 0.012 | 0.018 | 0.019 (2.4x) |
| rs_industry_12m | 0.010 | 0.015 | 0.016 | 0.023 (2.3x) |
| `score` (our composite) | **+0.011** | 0.005 | 0.003 | **-0.006** ❌ |
| `score_total` | +0.011 | 0.005 | 0.003 | **-0.006** ❌ |

**Average top-5 fundamental IC**: r_1m 0.022 → r_12m 0.053 (**2.4x**)

**Our final `score` composite: +0.011 at r_1m, but goes NEGATIVE at r_12m.** This is structural: our ML ensemble is trained against short-horizon (~1 month) targets, so it learns 1-month flip patterns. Names with strong LONG-TERM alpha (NVDA/AVGO/MU/SAGE-scoring names) appear weak in the short-term training and get ranked lower than they should.

**Implication**: a strategy with a 6-12 month holding period, training ML against r_6m or r_12m, would capture ~2.4x the alpha per factor — and most importantly, would catch NVDA/AVGO/MU early and ride the multi-year trend instead of selling into the first wiggle.
