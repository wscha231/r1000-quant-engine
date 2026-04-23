# Phase 16 — Theme Detection + Lifecycle Management (Proposal)

**Date**: 2026-04-23
**Status**: Draft — user directed "테마도 중요, 끝나는지 파악, 100% CAGR 목표"

## 0. Problem statement

Current engine:
- `industry_group` (33), `industry` (120) RS computed ← already granular
- `sector` (11), `sage_sector` (8) RS ← coarse
- **No cross-industry theme concept** (AI infra, weight-loss drugs, nuclear SMR)
- **No theme lifecycle tracking** (when does the theme end?)
- Engine picks NVDA/GOOGL (mega-cap) but misses LITE (+1056% mom), CIEN (+568%), WDC (+631%) — all in "AI infrastructure" theme

User insight:
> "테마가 끝나는지 잘 파악해서 잘 빠져나오고"
> "주도주가 계속 잘 가긴 하지만 그 테마가 언젠가는 끝나긴 할꺼다"
> "잘 파악해서 매수 매도만 해도 CAGR 100% 달성 가능"

## 1. Three-layer approach

```
Layer 1  THEME TAXONOMY          themes.yaml — 25 themes × 5-15 members
   ↓
Layer 2  THEME AGGREGATES        theme_rs_{1m,3m,6m,12m,24m},
                                 theme_breadth_above_ma200,
                                 theme_acceleration,
                                 theme_drawdown_from_peak
   ↓
Layer 3  PER-TICKER THEME SIGNAL theme_phase (early/maturing/peaking/ending),
                                 theme_leadership (top-mom_6m in its theme),
                                 theme_exit_trigger
```

## 2. Theme taxonomy (themes.yaml)

25 themes drafted (see `themes.yaml`):

| Group | Themes |
|---|---|
| AI/Semi | ai_infrastructure, ai_software, semi_equipment, semi_design_memory, cloud_hyperscale, data_center_infra |
| Energy/Power | oil_gas_ep, oil_gas_services, lng_midstream, nuclear_smr, power_grid_infra |
| Healthcare | weight_loss_drugs, oncology_mrna, medtech_devices, biotech_cros |
| Fintech | payments_rails, digital_banks_brokerage |
| Software | cybersecurity, saas_vertical |
| Consumer | ecommerce, discount_retail, luxury_discretionary |
| Industrial | defense_drones, industrial_reshoring, autonomous_driving |
| Alt | crypto_blockchain, uranium_materials |

Each theme: 5-15 tickers. One ticker CAN belong to multiple themes (NVDA → ai_infrastructure + semi_design_memory + ai_software).

## 3. Theme aggregate computations (per rebalance_date)

### 3.1 Basic aggregates
```
theme_mom_{1m,3m,6m,12m,24m}  = mean of member mom_{X}
theme_rs_{1m,3m,6m,12m}        = mean of member rs_benchmark_{X}
theme_breadth_above_ma200     = fraction of members with px > MA200
theme_avg_vol_252d            = mean realized vol
theme_median_mktcap           = median market cap of members
```

### 3.2 Derived signals
```
theme_acceleration_s6  = theme_mom_1m − theme_mom_6m
theme_acceleration_s12 = theme_mom_3m − theme_mom_12m
theme_deceleration     = negative of above
theme_drawdown_peak    = theme_cum_return - rolling_max(theme_cum_return)
theme_breadth_decline  = theme_breadth_above_ma200 − MA(theme_breadth, 12m)
```

### 3.3 Phase label logic (theme lifecycle)

```
theme_phase =
  'early'    if theme_rs_12m < 0 AND theme_rs_1m > 0 AND breadth > 0.40  (turning up)
  'maturing' if theme_rs_12m > 0 AND theme_acceleration_s6 > 0            (accelerating)
  'peaking'  if theme_rs_12m > 0 AND breadth > 0.70 AND acceleration_s6 < 0  (breadth peak, decel)
  'ending'   if theme_drawdown_peak < -0.15 AND breadth < 0.40            (broken)
  'dead'     if theme_rs_12m < 0 AND breadth < 0.25                       (lost)
```

## 4. Per-ticker theme features

For each (ticker, date):
```
theme_primary         = first theme in themes.yaml ticker belongs to
theme_count           = number of themes ticker belongs to
theme_leadership_rank = rank within primary theme by mom_6m (1 = top leader)
theme_leadership      = 1 if theme_leadership_rank <= 3 else 0
theme_phase_primary   = phase of primary theme
theme_exit_trigger    = (theme_phase_primary in ['ending','dead']) OR
                        (theme_rs_6m drops >20pp vs 6m ago)
```

## 5. Integration into composite + backtest

### 5.1 Score composition additions

**Future_winner composite** gains:
```
+0.60 × theme_leadership × theme_phase_is(maturing)   # early leader of maturing theme
+0.40 × theme_acceleration_s6                          # theme accelerating
-0.80 × theme_exit_trigger                             # exit when theme ends
```

**Early_scout composite** gains:
```
+0.80 × (theme_phase_is(early) AND theme_leadership)  # emerging leader of new theme
+0.30 × theme_breadth_improving                       # breadth expanding
```

### 5.2 Backtest exit triggers

Phase 15-R3 RS break extended with theme-level:
```
exit condition = stock RS break OR theme_exit_trigger
```

When theme ends → exit all theme-tagged holdings immediately (not wait for next rebal).

## 6. Ship gate for Phase 16

| Metric | Baseline | Phase 16 target | Stretch |
|---|---|---|---|
| Main CAGR | 19.78% | 25% | 30% |
| Concentrated CAGR | 30.92% | 40% | 50% |
| MaxDD main | -27.75% | -22% | -20% |
| Sharpe | 1.02 | 1.15 | 1.25 |

**100% CAGR realism**: concentrated with N=3 perfect-theme-timing is theoretically achievable on paper but:
- Would require perfect theme-entry AND theme-exit timing
- Sample size concern (3 names × perfect picks = high variance)
- Real-world slippage + taxes not modeled
- **Realistic concentrated goal: 45-55% CAGR with theme-aware selection**

## 7. Implementation plan (2-3 weeks)

### Week 1 — infrastructure (10-15h)
1. themes.yaml → loader function (`load_themes()` in r1000_helpers.py)
2. Theme aggregate computation in build_feature_store or new stage
3. Per-ticker theme features attach to feature_store
4. Smoke tests for theme loader

### Week 2 — scoring + exit (10-15h)
5. Add theme weights to future_winner / early_scout composites
6. Phase 15-R3 extended with theme_exit_trigger
7. Output: `theme_leadership_latest.csv` (per-theme top-3 leaders + phase)

### Week 3 — validation (8-10h)
8. Retrospective backtest: apply theme signals to past 83 months
9. Compare: baseline vs +themes CAGR/Sharpe
10. Tune phase thresholds

## 8. Risks

- **theme overfit**: 25 themes × 10 members = 250 data points. Small sample for aggregate stats.
  - Mitigation: use 6m+ rolling windows; don't make decisions on <3-month data
- **membership drift**: member tickers may need updating as companies pivot.
  - Mitigation: quarterly review process; dead_themes section
- **lifecycle miscategorization**: phase='maturing' may be at actual peak.
  - Mitigation: 2-month confirmation before acting; use multiple signals

## 9. Open design questions

- Manual theme assignment vs ETF-based? (Current: manual)
- Equal-weight theme aggregate vs mktcap-weight?
- Should ONE ticker be weighted across multiple themes or just primary?
- When theme splits (e.g. AI infrastructure → GPU + networking), how to handle?

## 10. Next actions

1. Review themes.yaml with user — add/remove/edit themes
2. Implement theme loader + aggregate computation (Week 1)
3. Backtest with theme features to measure actual lift
4. Decide on threshold tuning per 9-cell ablation pattern

## Files
- `themes.yaml` — taxonomy (this commit)
- `PHASE_16_THEMES_PROPOSAL.md` — this doc
- Future: `r1000_themes.py` (loader + aggregate computation)
- Future: `research/phase16_theme_retrospective/*` (validation)
