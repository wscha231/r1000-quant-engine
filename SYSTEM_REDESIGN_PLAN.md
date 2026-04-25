# R1000 Quant Engine — Full System Redesign Plan

_Created 2026-04-25 after leakage discovery._

## Lessons Learned (Today's Session)

1. **Leakage 발견 — 사용자 직감이 시스템 살림**: ML 76% CAGR이 100% leakage였음 (forward returns가 features로 사용)
2. **검증된 진짜 alpha**: 정석 model +11%, T4 RS Acceleration +10% (백테스트 검증)
3. **검증되지 않은/음의 알파 신호**: T1 Stage 2 Breakout (-2.5%), ML clean (~0), T5 Turnaround (regime-dependent)
4. **Insider/Analyst upgrade 통념 거꾸로**: 21일 -5~-7% (단기 contrarian)
5. **PIT discipline 절대 원칙**: 모든 feature가 시점 t에 알 수 있는 데이터만 사용

## 전체 7 Layer 아키텍처

```
┌─ Layer 1: Data Collection ────────────────────────┐
│  Price (Alpaca), Fundamentals (SEC + Finnhub),   │
│  Macro (FRED), Universe (iShares IWB)            │
│  Output: cache/, raw data                         │
└──────────────────────────────────────────────────┘
            ↓
┌─ Layer 2: Feature Engineering (PIT-safe) ───────┐
│  Past momentum (mom_*m), Technical (MA/RSI/vol), │
│  Fundamental ratios (live recompute),            │
│  Macro regime (vix/cpi/m2/yield)                 │
│  AUTOMATED leakage audit                         │
│  Output: feature_store_pit.parquet               │
└──────────────────────────────────────────────────┘
            ↓
┌─ Layer 3: Rule Engine (검증된 신호만) ────────────┐
│  T4 RS Acceleration (+10%), T3 Earnings Gap     │
│  Sector relative, Theme phase                    │
│  Drop T1 (negative alpha), T2 (weak)             │
│  Output: rule_signals.csv                        │
└──────────────────────────────────────────────────┘
            ↓
┌─ Layer 4: ML Layer (정직한) ────────────────────┐
│  Time-series CV, Quantile regression             │
│  Walk-forward validation                         │
│  Ship gate: decile spread > 5%                   │
│  Output: ml_predictions.csv                      │
└──────────────────────────────────────────────────┘
            ↓
┌─ Layer 5: Portfolio Construction ────────────────┐
│  Combined score (정석 + T4 + ML)                 │
│  Sector caps, position sizing, risk parity       │
│  Output: portfolio_target.csv                    │
└──────────────────────────────────────────────────┘
            ↓
┌─ Layer 6: Execution ─────────────────────────────┐
│  Alpaca paper -> Live broker                     │
│  Limit orders, trailing stops                    │
│  Audit trail                                     │
│  Output: actual_trades.csv                       │
└──────────────────────────────────────────────────┘
            ↓
┌─ Layer 7: Monitoring ────────────────────────────┐
│  Daily P&L, drift detection, alerts              │
│  Live vs backtest reconciliation                 │
│  Auto-pause on drift                             │
│  Output: daily_report.json + Telegram            │
└──────────────────────────────────────────────────┘
```

## Phase 별 Plan (총 ~2주)

### Phase 0: Inventory (Day 1, 6h)

기존 코드 정리 + PIT discipline migration plan

**작업**:
- [x] 현재 commit `6c0a496` 기준 21 modules 검토
- [ ] PIT-safe vs leakage features 분류 표 작성
- [ ] Keep / Refactor / Drop 결정

**Keep**:
- `aggressive/data_alpaca.py`, `universe.py`, `finnhub_client.py`
- `aggressive/signals_technical.py` (T1-T5 detectors)
- `r1000_themes.py`, `aggressive/theme_discovery.py`
- `r1000_rule_backtester.py` (검증 framework)

**Refactor**:
- `r1000_pattern_miner.py`: leakage 제거 완료, but ML 가치 미미
- `r1000_rebalance_advisor*.py`: v3 hybrid는 유지, v4 ML은 폐기
- `r1000_strategy_backtester.py`: 정직한 결과 출력

**Drop**:
- ML predictor (decile spread 0)
- T1 Stage 2 Breakout fire (negative alpha)
- T5 Turnaround standalone use (-7% bull market)

### Phase 1: PIT Foundation (Day 2-4, 16h)

**목표**: 모든 feature가 시점 t에서 알 수 있는 데이터만 사용 보장

**1.1 Leakage Audit Tool (4h)**
```python
# r1000_leakage_audit.py (NEW)

def audit_feature(df, feature_name, snapshot_date):
    """
    For known stocks at known dates, verify feature value 
    matches PAST data not FUTURE.
    
    Test cases:
      NVDA 2023-12: r_12m past=+239%, forward=+170%
      SPY 2020-03 COVID: bench_ret_12m past=-10%, forward=+50%
      Any stock: future earnings should not appear in 'forward_pe'
    """
    
def audit_all(feature_store_path):
    """Run all audits, output report."""
```

**1.2 Rebuild feature_store_pit (8h)**
- 새 PIT-safe feature_store 빌드
- Documented column provenance
- Each feature has "computed_at_date" timestamp
- Includes:
  - mom_*m (past returns 1m/3m/6m/12m/24m/36m)
  - Technical (MA20/50/150/200, RSI14, MACD, BB, ATR, OBV)
  - Fundamental ratios (PE/PEG with live recompute)
  - Sector RS (rs_industry_*m, rs_sector_*m)
  - Macro (cpi, vix, m2, dxy, yield curve)
  - Theme phase + breadth

**1.3 Continuous Verification (4h)**
- Pre-commit hook: leakage audit on any feature change
- CI: nightly audit on feature_store
- Telegram alert if leakage detected

### Phase 2: Rule Validation (Day 5-6, 12h)

**목표**: 모든 신호의 진짜 alpha 측정

**2.1 Walk-forward Backtest Framework (4h)**
```python
# r1000_walk_forward.py (NEW or refactor)

def walk_forward(rule_func, universe, start, end, 
                 horizons=[21, 63, 126, 252]):
    """
    Properly time-series-split backtest.
    For each month-end:
      1. Apply rule using ONLY data <= that date
      2. Hold for horizon days
      3. Compute return + alpha vs SPY/sector
      4. Aggregate stats with confidence intervals
    """
```

**2.2 5-year R1000 Backtest (8h)**
모든 신호 검증:
- T1 Stage 2 Breakout (이미 -2.5% 확인)
- T2 VCP (이미 -0.4% 확인)
- T3 Earnings Gap (n 부족, 더 데이터 필요)
- T4 RS Acceleration (+10% 검증)
- T5 Turnaround (regime test)
- Insider 3+ buy (단기 vs 장기)
- Analyst upgrade (단기 vs 장기)

**Ship gate**: 
- Sample size n >= 100
- Sharpe >= 0.30
- Statistical significance (p < 0.05)

### Phase 3: ML with Discipline (Day 7-9, 18h)

**목표**: 정직한 ML — 가짜 알파 X

**3.1 Time-series CV Framework (6h)**
```python
# r1000_ml_train.py

def time_series_cv(X, y, n_splits=5):
    """
    Time-respecting k-fold:
      Fold 1: train 2018-2020, val 2021
      Fold 2: train 2018-2021, val 2022
      Fold 3: train 2018-2022, val 2023
      Fold 4: train 2018-2023, val 2024
      Fold 5: train 2018-2024, val 2025
    """
```

**3.2 Train Honest Models (8h)**
- Quantile regression (p5, p50, p95)
- LightGBM with strong regularization
- Features: ONLY PIT-safe (Phase 1 output)
- Target: r_3m forward (excluded from features)

**3.3 Validate (4h)**
- Cross-validation R² > 0.05 required
- Decile spread out-of-sample > 5% required
- SHAP analysis for interpretability
- If both gates fail → ship with confidence_low flag, OR drop ML

### Phase 4: Portfolio Construction (Day 10-11, 12h)

**4.1 Combined Score (4h)**
```python
combined_score = (
    0.40 * old_jeongseok_score    # +11% alpha proven
    + 0.30 * t4_rs_score           # +10% alpha proven
    + 0.20 * ml_predicted_pct      # if ship gate passed
    + 0.10 * theme_phase_mult      # context
)
```

**4.2 Position Sizing (4h)**
- Top 3 by combined: 18% each
- 4-6: 12% each  
- 7-12: 8% each
- Sub-sector cap 35% (soft)
- Volatility cap (2% risk per trade)

**4.3 Risk Manager (4h)**
- Max drawdown -15% → reduce position
- Regime-turn detection → defensive cash
- Single ticker 14% hard cap
- Stop loss at -8% (O'Neil)

### Phase 5: Production Pipeline (Day 12, 8h)

**5.1 Daily Refresh (4h)**
- 매일 23:00 KST GHA workflow
- 데이터 fetch → features → rules → ML → portfolio target
- Output: daily_target.json
- Telegram digest + Discord webhook

**5.2 Drift Detection (4h)**
```python
# r1000_drift_detector.py

def detect_drift(live_returns, backtest_returns):
    """
    Compare live performance vs backtest expectations.
    Alert if:
      - Live Sharpe < 50% of backtest Sharpe (3-month rolling)
      - Live MaxDD exceeds backtest MaxDD
      - Win rate drops > 10pp
      - Features distribution shifted (PSI > 0.25)
    """
```

### Phase 6: Live Operation (Ongoing)

**6.1 Paper Validation (1-2 weeks)**
- Alpaca paper $100k
- Daily monitoring vs backtest expectations
- Drift detection active
- Weekly review

**6.2 Small Live (Month 1-2)**
- $10k initial capital
- Same signals as paper
- Compare paper vs live (slippage, fees)
- Build trust

**6.3 Scale Up (Month 3+)**
- Conditional: live tracking matches paper within 2σ
- Monthly rebalance, risk-parity adjusted

## Project Structure (Target)

```
r1000-quant-engine/
├── data/                         # Layer 1
│   ├── collectors/
│   │   ├── alpaca.py             # bars
│   │   ├── finnhub.py            # fundamentals + insider
│   │   ├── sec_edgar.py          # 10-K/10-Q
│   │   ├── fred.py               # macro
│   │   └── ishares_iwb.py        # universe
│   ├── cache/                    # gitignored
│   │   ├── bars/
│   │   ├── finnhub/
│   │   ├── sec/
│   │   └── macro/
│   └── README.md
│
├── features/                     # Layer 2
│   ├── pit_safe/
│   │   ├── momentum.py           # mom_*m
│   │   ├── technical.py          # MA, RSI, BB, MACD, ATR, OBV
│   │   ├── fundamental.py        # live recompute PE/PEG
│   │   └── macro.py              # regime, vix, m2
│   ├── leakage_audit.py          # CRITICAL
│   ├── feature_store.py          # build orchestrator
│   └── tests/
│
├── rules/                        # Layer 3
│   ├── tiers.py                  # T3/T4 (validated only)
│   ├── theme_phase.py
│   ├── earnings_event.py         # PEAD-style
│   └── validated.yaml            # which rules ship
│
├── models/                       # Layer 4
│   ├── train_pit.py              # honest training
│   ├── predict.py
│   ├── walk_forward.py
│   ├── shap_explain.py
│   └── ship_gate.py              # decile spread > 5%
│
├── portfolio/                    # Layer 5
│   ├── score_combiner.py
│   ├── sizer.py                  # tier caps + vol parity
│   ├── risk_manager.py
│   └── advisor.py                # final picks
│
├── execution/                    # Layer 6
│   ├── alpaca_executor.py
│   ├── audit_trail.py
│   └── order_manager.py
│
├── monitoring/                   # Layer 7
│   ├── daily_review.py
│   ├── drift_detector.py
│   ├── pnl_tracker.py
│   └── alerts/
│       ├── telegram.py
│       └── discord.py
│
├── backtest/                     # Validation
│   ├── walk_forward.py
│   ├── strategy_compare.py
│   └── reports/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── leakage/                  # leakage tests
│
├── .github/workflows/
│   ├── daily_pipeline.yml
│   ├── weekly_finnhub.yml
│   ├── monthly_unified.yml
│   ├── ci.yml                    # tests + leakage audit
│   └── nightly_drift.yml
│
├── docs/
│   ├── ARCHITECTURE.md
│   ├── PIT_DISCIPLINE.md
│   ├── ALPHA_AUDIT.md            # what's verified
│   └── DEPLOYMENT.md
│
└── README.md
```

## Validated Alpha Sources (Truth Table)

| 신호 | 검증 | Sample size | Alpha (90d) | Sharpe | Production? |
|------|------|------------|-------------|--------|-------------|
| 정석 model_score | ✅ | 15 months | +11% | 1.01 | YES |
| T4 RS Acceleration | ✅ | n=75 | +10% | 0.21 | YES |
| T3 Earnings Gap | ⚠️ | n=6 (적음) | +36% | 0.35 | YES (이벤트 only) |
| Theme phase (early/maturing) | ⚠️ | 추가 검증 필요 | TBD | TBD | TENTATIVE |
| Forward PEG (Finnhub) | ✅ | 검증 필요 | TBD | TBD | TENTATIVE |
| ML predictor (clean) | ❌ | OOS spread 0 | ~0% | - | NO |
| T1 Stage 2 Breakout | ❌ | n=281 | **-2.5%** | -0.12 | NO (역알파) |
| T2 VCP | ❌ | n=13 | -0.4% | -0.02 | NO |
| T5 Turnaround | ⚠️ | n=68 | +0.8% | 0.03 | NO standalone |
| Insider 3+ buy (21d) | ❌ | n=17 | -5% | - | NO (contrarian) |
| Analyst upgrade wave (21d) | ❌ | n=73 | -7% | - | NO (contrarian) |

## 현실적 기대치

**Production target (정직)**:
- CAGR: SPY + 8-15% alpha = 25-35% CAGR
- Sharpe: 1.0-1.5 (SPY 2.0 이하 정상)
- MaxDD: -15~-20%
- 연 hit rate: 60-65%
- Out-of-sample 첫 해 backtest의 50-70% 수익률 예상 (drift 고려)

**100% CAGR은 불가능** — Renaissance Medallion 39%, Buffett 20%. 우리 +30% CAGR도 도전적.

## Risk Management

**시스템 리스크**:
- 모델 drift: 매크로 regime 변화 (커버리지 검증 필요)
- Quant winter: 모멘텀 작동 안 하는 시기 (분산 + 적극적 risk-off)
- Survivor bias: 폐상장 종목 누락 (universe 동적 갱신)
- Backtest 시기 의존성: 2024-26 강세장 결과 (다른 regime 검증 필요)

**Human errors**:
- Leakage 재발 (지속 audit 자동화)
- 과도한 신뢰 (실제 < 백테스트 예상)
- Position 과집중 (sector cap 강제)

## Timeline

```
Week 1 (Day 1-7):
  Day 1: Phase 0 inventory
  Day 2-4: Phase 1 PIT foundation
  Day 5-6: Phase 2 rule validation
  Day 7: Phase 3 시작

Week 2 (Day 8-14):
  Day 8-9: Phase 3 ML
  Day 10-11: Phase 4 portfolio
  Day 12: Phase 5 production
  Day 13-14: Phase 6 paper validation 시작

Month 2:
  Phase 6.2 small live ($10k)
  Daily monitoring

Month 3+:
  Conditional scale up
  Continuous improvement
```

## 즉시 다음 단계 (Tomorrow)

**Option 1**: Phase 0 inventory 시작 (1일 작업)
**Option 2**: Phase 1.1 leakage audit 자동화 (4시간)
**Option 3**: 일단 Monday paper 시작 + 백그라운드 진행

**추천**: **Option 3**. 검증된 정석+T4 신호로 Monday paper 시작, 동시에 Phase 1 진행.

---

## 핵심 원칙 (모든 layer)

1. **PIT discipline 절대**: 시점 t에 미래 알 수 없는 데이터 X
2. **Validated alpha만 production**: 백테스트 + 통계적 유의성 통과
3. **정직한 기대치**: 8-15% alpha, Sharpe 1.0-1.5
4. **자동화된 leakage audit**: 매번 feature 추가 시 검증
5. **Drift 모니터링**: live vs backtest 일치 확인
6. **사용자 직감 존중**: "too good to be true → leakage 의심"

---

_이 plan은 살아있는 문서. 매주 진행도 업데이트 + 새 발견 반영._
