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

## 6. Target: CAGR 100% (user-set, 2026-04-23)

### 6.1 Math
- 100% CAGR = 매월 +5.95%, $100k → $11.8M over 83 months (118x)
- vs 역사적 개별 최고: LRCX CAGR 48%, NVDA CAGR 41%, LITE CAGR 39% (single best stocks over 83m)
- **단일 최고 주식도 CAGR 50%가 ceiling** → 포트폴리오 100% = 극한 stretch

### 6.2 100% 달성 path (3 options)

| Option | 방식 | CAGR 예상 | Risk |
|---|---|---|---|
| **A. Pure theme rotation** | N=3 concentrated + 완벽 entry/exit + cash | 60-80% (일부 연도 100%+) | MaxDD -40%+ |
| **B. Leverage only** | 기본 30-40% + 2x ETF | 80-100% in bull, -50-70% in bear | 복구 어려움 |
| **C. A + B 혼합 + regime gates** | N=3 + theme timing + 1.5-2x leverage + bull-only | 90-120% in bull years | -50-60% in bear |

**현실적 path**: Option A 먼저, 60-80% 확인 → Option C로 leverage 추가 (Phase 17).

### 6.3 Ship gate (tiered)

| 시점 | Tier | Main CAGR | Concentrated CAGR | Sharpe | MaxDD |
|---|---|---|---|---|---|
| 현재 baseline | - | 19.8% | 30.9% | 1.02 | -28% |
| Week 2 (Phase 16 초기) | Conservative | 25% | 40% | 1.15 | -25% |
| Week 3 (threshold tuning) | Realistic | 30% | 50% | 1.20 | -30% |
| **Phase 16 최종** | **Aggressive** | **35%** | **60-80%** | 1.20 | -35% |
| Phase 17 + leverage (future) | Stretch | 40% | 80-120% | 1.15 | -50% |

### 6.4 핵심 성공 조건

1. **Theme early 진입**: phase=early → phase=maturing 전환 시 매수
2. **Theme peaking/ending 즉시 exit**: breadth peak + acceleration 음전환
3. **Regime turn 감지 + cash 대피**: 2022/2026 같은 상황 반복 방지
4. **Concentrated N=3**: N=5 champion 33% → N=3은 45%+ 가능성
5. **Multi-theme 분산**: AI + Energy + Health 3 테마 교차 entry

### 6.5 Risk 관리

- N=3 concentrated → variance 극심 (1 종목 -30% = 포트 -10%)
- 따라서 **trailing stop -10-15%** 동시 사용 (Phase 15-R1 강화)
- Theme-level stop도 병렬 (Phase 16 exit_trigger)
- **2중 안전장치**: stock-level + theme-level

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
- Future Phase 17: leverage overlay (2x ETF + regime gates)

## Phase 17 preview — Leverage overlay (100% CAGR 달성 key)

After Phase 16 theme rotation validated at 60-80% CAGR, Phase 17 adds:

```
cfg.leverage_factor: float = 1.0     # default no leverage
cfg.leverage_enabled_regime: list = ['bull_strong']
cfg.leverage_max_when_active: float = 2.0
cfg.leverage_deleverage_trigger: str = 'regime_turn'  # immediate 1.0x
```

- Bull regime + theme maturing + breadth > 60% → 1.5-2x leverage via TQQQ/UPRO
- Regime turn detected → immediate deleverage to 1.0x + cash buffer
- Bear regime → 0x (100% cash or inverse SPY/QQQ)
- **단계적 접근**: paper trade 3개월 → live small position → scale up

## 100% target realism
- Theme-run 단위로는 역사적 사례 다수 (AI 2023-24, COVID 2020)
- 다년 평균 100% = extreme (지금까지 최고 장기 투자자도 40-50% 대)
- **계획적 목표**: Phase 16로 50-70% 확정 → Phase 17로 leverage 조합 90-120% bull year 달성
