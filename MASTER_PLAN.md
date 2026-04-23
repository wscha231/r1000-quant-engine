# Master Plan v3 — r1000 Quant Engine (2026-04-23)

**Core goal**: Main 19.78% → **25%**, Concentrated 30.92% → **40%**. Subscription service readiness.

## 📊 CRITICAL: Regime-turn weakness (newly quantified 2026-04-23)

| 연도 | Engine | Bench | Excess | 비고 |
|---|---|---|---|---|
| 2019-2024 | 14~46% | 13~22% | +1~+24pp | 대부분 outperform |
| **2022 bear** | **-15.3%** | -9.4% | **-5.9pp** 🔴 | Mom 전략 약점 |
| 2025 | 20.4% | 16.4% | +4.1pp | ok |
| **2026 YTD** | **-4.0%** | -1.4% | **-2.7pp** 🔴 | **지금 underperform** |

**Engine structural weakness**: **Regime-turn에서 last-out**. 강세 regime에서 +20pp 초과, bear/reversal에서 -5pp 이상 손해. Beat-ratio 54% (절반 승률) → 초과수익은 outlier 강세 달에 편중.

**User 검증한 직감** (오늘 대화):
- "이미 오른 거 사는 경향" ← deep audit: top-10 trailing 36m return +63.6% vs universe +38.1%
- "종목 안 바뀐다" ← 모멘텀 엔진은 의도적 persistence
- "비중 더 다양하게" ← weight cap 14%에 NVDA/GOOGL 막힘 + score IR 0.048이라 변별력 부족

---

## 0. 현재 상태

**43+ commits (2026-04-22 일일)**. HEAD: `a09eab5`.

### 오늘 (2026-04-23) 진행 중
- `byo9l9idw` full collector + pipeline run (~1시간)

### 실행된 code changes (all default OFF)
- Tier 0 a/b/c 데이터 fix (mktcap, 1970 dates, standalone CSVs)
- Phase 4/6c/7a gate env-override 수정
- 15-A1, 15-S1a (+ sub-toggles), 15-R1, 15-R2, 15-R3 구현
- Phase 13-lite (concentrated enrichment + summary JSONs + recent_trades)
- --ab-quick CLI (BUG: concentrated grid 끄면 main blend 붕괴)
- reuse_fingerprint runtime-only 제외

### A/B 결과 (어제)
- 9-cell Tier 2 grid: **--ab-quick 버그로 결과 invalid**
- 15-A1: cache reuse로 **feature-store 재빌드 안 됨** → A/B invalid
- Phase 4 -0.25pp FAIL (but --ab-quick 문제 혼재 가능성)
- Phase 6c zero delta (dormant, safe ship)

---

## 1. 🔴 Errors discovered (summary)

### A/B infrastructure (Critical)
1. --ab-quick 모드 → sleeve_cap_policy champion 선택 실패 → main blend 붕괴
2. cache reuse 전략이 feature-store-level phases에 부적합 (15-A1 등)
3. cfg field 추가마다 fingerprint 변경 → one-time slow rebuild (7b9dad1로 해결)

### Alpha / signal (Critical)
4. Production `score` IR 0.048 — 거의 랜덤
5. 11개 mid-cap winner 완전 누락 (KLAC +1458%, MPWR, XPO, MU, AXON ...)
6. 엔진이 "이미 오른 거" 사는 편향 (+63.6% trailing 36m)
7. **Regime-turn에서 구조적 -5pp 이상 손해** (2022, 2026 YTD)

### Weight / structure (High)
8. Weight cap 14% (`stock_weight_max_no_ttm` / regime_ctl 중첩)
9. Cash target 4% in "balanced" regime — bull 장에서 과보수
10. TTM coverage 부족: 68% fallback, 5%만 clean TTM
11. Tier 0a mktcap 1e14 해제 후 **-3.17pp drift** — 옛 cap이 implicit 페널티 역할

### Data quality (Medium)
12. `fund_panel.accepted = 2026-05-15` (미래 날짜 버그 잔재)
13. r_12m coverage cliff (2025-10 이후 — forward return이니 정상, audit 통과)

---

## 2. 🎯 Revised priorities (v3)

### Tier A — Immediate (this week)

**A1. Regime detection + dynamic signal blend** (new priority #1)
- **2022/2026 -5pp 손해 문제 직접 대응**
- **진단 (2026-04-23)**: 현재 Phase 4 SLEEVE_FACTOR_REGIME_MULTIPLIERS의 "balanced" regime multiplier = **1.00** (no-op). 2022 bear + 2026 YTD 둘 다 "balanced" 라벨 유지 추정 → Phase 4 보호 기능 **한 번도 안 켜짐**.
- **원인**: 현재 regime taxonomy가 **event-based** (war / stagflation / systemic_crisis) 이고 **market-cycle-based가 아님**. Bull/bear/turn labels 없음.
- **Fix plan**:
  1. 새 `market_cycle_regime` label: bull_trending / bull_peaking / bear_falling / bear_bottoming / recovery / sideways / stagflation
  2. Detector inputs: VIX (z-score 63d), breadth (% above MA200), SPY drawdown, SPY MA200 relation, credit spreads, fear_greed composite
  3. New multiplier table: bear_falling = core ↑, future/early ↓ (방어). recovery = early ↑ (early leaders 잡기)
  4. Phase 4 activate + 기존 event_regime과 **AND** (둘 다 만족 시 적용)
- 시간: 8-10h (detector 6h + multiplier tuning 2h + FULL A/B ~3h)

**A2. Tier 0a mktcap 원복 테스트**
- 1e14 → 1e12 원복, baseline 재측정
- 3pp drift가 mktcap 원인인지 ML retrain drift인지 판별
- 시간: 30분 config + 30분 QUICK run

**A3. --ab-quick bug fix OR 폐기**
- 현재 bug: concentrated grid OFF시 sleeve_cap champion 선택 실패
- Option 1: 최소 1 concentrated combo + sleeve_cap champion 유지
- Option 2: --ab-quick 폐기, full QUICK (20-30분) 기본
- 시간: 2-3h

### Tier B — Next week (core alpha)

**B1. 15-S1b ML target r_1m → r_3m** (FULL, ~3h)
- Deep audit: pred_future_winner_ret IR 0.25@1m vs **1.24@12m**
- 3m horizon 이 sweet spot
- Main +0.5~1pp, Concentrated **+3~5pp** 기대

**B2. 15-E Inflection detector**
- KLAC/MU/MPWR-type mid-cap 조기 발굴
- Signal: low trailing 12m (40-70th pct) + improving fundamentals + technical base + val_residual 양수
- 시간: 6-8h research + feature 설계 + FULL 테스트

**B3. Weight cap regime 민감화**
- Bull: 18-20% per-name cap (high-conviction 허용)
- Bear: 10-12% (분산)
- Current fixed 14% → 시장 adaptive
- 시간: 2-3h

### Tier C — Medium (일주일-2주)

**C1. Multi-horizon RS + sage_sector**
- User idea validated: 24m base + 1m/3m acceleration + 4-quadrant label
- 시간: 6-8h + FULL

**C2. 15-S2b Core conviction lock (mid-rank #8-18)**
- Deep audit: top-7 이미 안정 (2.55m hold), #8-18이 churn 원인
- 시간: 4-6h

**C3. Cash policy 동적 조정**
- Bull regime: 0-1%
- Balanced: 2-3%
- Risk-off: 5-15% (이미 있음)
- 시간: 2-3h

**C4. 15-R1/R2/R3 threshold 완화 재시험**
- 어제 grid: threshold 83m 내 한 번도 trigger 안 됨
- Options: R1 -15% → -10%, R2 2m → 1m, R3 top15→bot30 → top25→bot40
- 시간: A/B 30분 (cells already set up)

### Tier D — Architectural (1-2개월)

**D1. 15-C1 Continuous weight glide**
- Weekly score refresh + 4주 glide
- Turnover 43% → 25%, 비용 -1~2pp/년

**D2. 15-C2 Event-driven triggers**
- Earnings beat/miss, RS break, regime flip → 즉시 action
- Daily cron 인프라

**D3. Execution reality modeling**
- Per-ticker liquidity 필터
- Dynamic slippage cost
- Service 신뢰도

### Tier E — Deferred (외부 데이터/research)

- **Phase 14 Dividends tracking** (1-2일)
- **Options flow** (유료 데이터 4주+)
- **NLP earnings call sentiment** (LLM API 2-3주)
- **R2000 universe 확장** (regime 증폭 위험)

---

## 3. 🎯 25%/40% 달성 가능 path

| 단계 | Main | Concentrated | MaxDD |
|---|---|---|---|
| 현재 Full QUICK baseline | 19.78% | 30.92% | -27.75% |
| + A1 regime detection (bear/turn 회복) | 22~23% | 32~34% | -22% |
| + A2 mktcap 원복 (3pp drift 회복) | 25~26% | 33~35% | ~ |
| + B1 ML target r_3m | 26~27% | 37~40% | ~ |
| + B2 Inflection detector | 27~28% | **40~42%** | ~ |
| + C1~C4 | **28~30%** | 42~45% | -18% |

**목표 달성**: B1+B2 완료 시 25%/40% 도달 가능.

---

## 4. 지금 해야 할 것 (우선순위 재정립)

1. **byo9l9idw 완료 대기** (~30-60분 추가)
2. **결과 확인** — 새 baseline + fresh data 검증
3. **Tier A1-A3 중 가장 빠른 것부터**:
   - A2 mktcap 원복 (30분 + QUICK 20분) — 3pp drift 원인 규명
   - A3 --ab-quick fix (2-3h) — A/B 신뢰도 복구
   - A1 regime detection (6-8h) — 2026 underperform 직접 대응

**추천 오늘 순서**:
1. byo9l9idw 완료
2. 결과 분석 + 새 baseline 측정
3. A2 mktcap 원복 테스트 (빠른 규명)
4. A3 --ab-quick fix
5. B1 ML target r_3m FULL (밤에 백그라운드)

---

## 5. 방향 Pivot 요약

**Before (어제)**:
- Tier 0 → 1 → 2 (exit discipline) → 3 (selection)

**After (오늘 증거 기반)**:
- **Tier A regime-awareness first** (2022/2026 약점 직접 대응)
- **Tier A2 Tier 0a 원복 검토** (예상과 반대 결과)
- **Tier B1 ML target r_3m이 큰 lift** (IR 1.24 활용)
- **Tier B2 Inflection detector** (user 비전 + mid-cap 발굴)
- **Exit discipline (R1/R2/R3)은 Tier C4로 강등** (threshold 완화 후 재시험)
