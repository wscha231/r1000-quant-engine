# Master Plan — r1000 Quant Engine (2026-04-22 PM)

**Goal**: Main 22.95% → **25%**, Concentrated 33.17% → **40%** CAGR.
Subscription-ready service tier (정석 무료 + 성장주 유료).

---

## 0. 현재 상태 — Where we are

### 오늘까지 완료 (34+ commits, 2026-04-22)

**Tier 0 — Foundation 데이터 정합성** ✅
- `04503fd` mktcap 1e12 cap 해제 → mega-cap (NVDA $4T, AAPL $3.7T) 분리
- `42ddce3` 1970 epoch dates fix (SEC int-date 파싱)
- `5b5edac` Empty standalone CSV (sleeve_test 컬럼)
- Tier 0d (r_12m cliff) 조사완료 — bug 아님
- Tier 0e (R1000 vs SPX benchmark) — defer

**Tier 1 — 게이트 fix (버려진 phase 회수)** ✅
- `04503fd` Phase 4/6c/7a 게이트 env-overrides-cfg (Phase 11 fix 패턴)
- 새 cfg field 추가가 fingerprint 무효화 → cache rebuild
- `7b9dad1` reuse_fingerprint EXCLUDE list (runtime-only fields)

**Tier 2 — Exit discipline 구현** ✅ (default OFF, A/B ready)
- `1f6349e` 15-R1 trailing stop (peak drawdown, per-sleeve)
- `abe89b0` 15-R2 revision break exit (N개월 연속 negative)
- `abe89b0` 15-R3 stock RS break exit (top decile → bottom 30%)

**Tier 3 — Selection 강화 (부분)** ✅ (default OFF, A/B ready)
- `dfcc07c` 15-S1a 3-factor toxic prune (future_winner only)
- `2cc2a76` 15-S1a sub-toggles (per-factor ablation)
- `6d1d848` 15-A1 negative-IR feature drop (3개)
- `aba097c` 9-cell A/B grid harness

**Phase 13-lite — Subscription 인프라** ✅
- `80e0869` concentrated CSV enrichment (Phase 12A 패턴)
- `80e0869` current_portfolio_summary.json + concentrated 동일
- `a34d407` recent_trades.json (last-90d 트레이드 이벤트)

**Research deliverables** ✅
- `21f1979` future_winner factor IC audit (3m horizon = sweet spot)
- `77d829f` 종목 선별 deep audit (production score IR 0.048, 11 missed winners)
- `53af224` 15-S1a A/B verdict (main FAIL / concentrated PASS)
- `ac95d22` ablation verdict (drop_ub best single, FT 91% of conc gain)

### 진행 중
- A/B `b029fgd3t` — fingerprint 변경 → cache rebuild 진행 (15:19~16:20 예상)

---

## 1. 다음 즉시 (A/B 완료 직후 ~1시간)

### 1.1 자동 실행 (코드 작성 0)

```bash
# Tier 2 grid (9 cells, ~45min)
bash research/phase15_tier2_ab/run_tier2_grid.sh
py -3 research/phase15_tier2_ab/analyze_tier2.py
```

9 cells:
- A baseline / B R1 / C R2 / D R3 / E all_R / F R+A1
- G P4 (regime sleeve weights) / H P6c (vol target) / I full_stack

### 1.2 결과 분석 → ship 결정
- ship gate 통과한 phase의 cfg default를 True로 flip
- 또는 default OFF 유지하고 env opt-in만 지원

### 1.3 즉시 ship 가능 (검증 후)
- 15-A1 negative features drop (data IR -0.33~-0.40 명백한 noise)
- Phase 4 regime sleeve weights (만약 PASS)
- Phase 6c vol targeting (만약 MaxDD 개선)
- 15-R1/R2/R3 (만약 cell PASS)

---

## 2. 단기 (이번 주, 코드 ~10h)

### 2.1 Phase 7a 재설계 — Clustered insider buying
- 현재: insider_flow_signal_score (단발 매수도 포함, IC 약함)
- 신규: C-suite + 같은 주 3명 이상 + 단순 옵션 매도 제외
- 데이터 이미 있음: `sec_form345_*` columns
- 예상 ΔCAGR: +0.3~0.8pp
- 시간: 3-4h

### 2.2 15-S4 Sleeve-specific rebalance grid
- 현재 default: core 1m / future 2m / early 1m
- A/B grid: core {1m, 3m, 6m} × future {1m, 2m, 3m} × early {1m}
- = 9 combinations × ~5min = 45min A/B
- 예상 ΔCAGR: +0.3~1pp (compounder 회전 절감)

### 2.3 15-S2b conviction multiplier 튜닝
- 기존 `cfg.conviction_hold_seed_bonus = 0.35`
- A/B at 0.70 (2x), 1.05 (3x)
- 시간: 30분 (cfg override만)

### 2.4 Tier 0e benchmark R1000 (IWB)
- 현재 SPX. R1000 universe라 약간 부정확
- IWB ETF historical 가격 필요 (yfinance)
- 시간: 2h

---

## 3. 중기 (이번 달, 코드 ~30h)

### 3.1 15-S1b ML target horizon realign — **가장 큰 ML lift**
- 현재: pred_future_winner_ret 훈련 target = r_1m
- 데이터: r_1m IR 0.25, r_3m IR 0.52, r_12m IR 1.24
- 변경: target = r_3m
- **FULL rebuild 필요 (~3h, 한 번)**
- 예상 ΔCAGR: concentrated +3~5pp, main +0.5~1pp
- A/B: BEFORE/AFTER FULL run

### 3.2 15-E Inflection Detector — **user 핵심 비전**
- "이미 오른 거" 사는 거 vs "오르기 전 발굴"
- 신규 feature `inflection_signature_score`:
  - Low trailing 12m (40~70th percentile)
  - Improving fundamentals (margin 가속, EPS revision 상승)
  - Technical base (vol contraction)
  - Val residual 양수
  - Insider buying (clustered)
- 시간: 6-8h (research + feature 설계)
- 예상 ΔCAGR: +1~3pp (KLAC-type 발굴)

### 3.3 Multi-horizon RS + sage_sector — **user 아이디어 직접 구현**
- 현재 RS coverage 불완전 (sector RS 6m only, 24m 없음, sage_sector RS 전무)
- 추가:
  - `rs_industry_24m`, `rs_industry_group_24m`
  - `rs_sector_{1,3,12,24}m` (현재 6m만)
  - `rs_sage_sector_{1,3,6,12,24}m` (전무)
  - Acceleration features (1m vs 12m spread)
  - 4-quadrant label (long+short)
- 시간: 6-8h
- 예상 ΔCAGR: +1~2.5pp main, +2~4pp concentrated

### 3.4 15-S2b Core Conviction Lock — 진짜 implementation (mid-rank)
- 단순 conviction_hold multiplier 외에, **#8-#18 mid-rank** specific
- 12개월 min-hold + 절대 quality threshold
- 시간: 4-6h
- 예상 ΔCAGR: +0.3~0.8pp

---

## 4. 장기 (1-2개월, ~50h+)

### 4.1 15-C1 Continuous weight glide
- 매주 score refresh + target weight 25%/주씩 glide
- Full swap은 thesis break event에만
- 시간: 8-10h
- 효과: turnover 43% → 25%, 비용 절감 +1~2pp/년

### 4.2 15-C2 Event-driven triggers
- Earnings 발표 즉시 beat/miss + guidance 평가
- RS 1주 내 top→bottom 감지 → 즉시 trim
- Daily cron 인프라 필요
- 시간: 10-12h
- 효과: intra-month risk 완전 해소

### 4.3 15-R4 Weekly monitor
- Daily/weekly cron이 exit 조건만 검증
- 신규 진입은 monthly rebal 유지
- 15-C2와 통합 가능
- 시간: 3-4h (15-C2 일부)

### 4.4 Phase 14 Dividends
- 현재 Adj Close라 implicit, but live 포트엔 explicit cash dividend 추적 필요
- 시간: 1-2일

### 4.5 Execution reality modeling
- Per-ticker liquidity 필터
- Dynamic slippage cost
- 실 구독자 수익률 신뢰도 확보
- 시간: 1주

---

## 5. New alpha 후보 (Phase 16+)

| 후보 | 데이터 필요 | 시간 | 예상 ΔCAGR |
|---|---|---|---|
| Event catalyst (earnings beat+raise) | 기존 | 6-8h | +1~3pp |
| Time-series momentum (dual-mom) | 기존 | 3-5h | +0.3~1pp |
| Quality-momentum regime blend | 기존 | 5-8h | +0.5~1.5pp |
| Long-short pair overlay (10-20%) | 기존 | 8-10h | +0.5~1pp Sharpe |
| **Options flow (unusual volume)** | 유료 (Unusual Whales) | 4주+ | +0.5~1.5pp |
| **NLP earnings call sentiment** | LLM API | 2-3주 | +0.3~0.8pp |
| **Industry disruption signals (10-K NLP)** | LLM API | 3-4주 | +0.5~2pp |

---

## 6. Out of scope (장기 deferred)

- R2000 universe expansion (regime 증폭 위험, 3-4x compute)
- Pre-2018 backfill
- Multiple subscriber accounts (frontend 영역)
- Tax lot accounting (FIFO/LIFO)
- Manual_positions_concentrated.yaml split (overlap이 많아 단일 yaml로 충분)

---

## 7. 누적 ΔCAGR 시나리오 (가장 보수적 → 가장 야망적)

| 시나리오 | Main | Concentrated | Path |
|---|---|---|---|
| Tier 0/1/2 ship 통과 (이미 구현) | 23-24% | 34-36% | A/B 결과 기반 |
| + Phase 4/6c shipping | 24-25% | 36-38% | 1.1 자동 실행 |
| + Tier 3 단기 (S4, S2b conv, P7a) | 25-26% | 38-40% | 2주 안 |
| **+ Tier 3 중기 (S1b, S-E, multi-horizon RS)** | **26-28%** | **40-44%** | **목표 도달** |
| + Tier 4 continuous ops | 27-29% | 42-46% | + Sharpe ↑↑ |

---

## 8. 우선순위 정렬 (data-driven)

**가장 높은 ROI/시간**:
1. ⭐ Tier 2 A/B grid 결과 → ship 통과한 거 자동 채택 (오늘/내일)
2. ⭐ Phase 4 / 6c verdict 확정 (오늘/내일)
3. ⭐⭐ 15-S1b ML target r_3m (FULL 1회) — concentrated +3-5pp 거의 확실
4. ⭐⭐ 15-E Inflection detector — user 핵심 비전 + KLAC-type 발굴
5. ⭐ 15-S4 sleeve rebal grid (compounder 회전 절감)
6. ⭐ Multi-horizon RS (user 아이디어, 학술 검증)
7. ⭐ Phase 7a clustered insider (alpha + 적은 노력)
8. 15-S2b conviction multiplier 튜닝
9. 15-C1+C2 continuous ops (architectural, 큰 작업)

**Service ship gate**:
- Phase 13-lite ✅ done (오늘)
- Execution reality modeling — 실제 구독자 수익률 보장
- Automation — Windows Task Scheduler

---

## 9. 의사결정 노드 (대기 중인 것들)

- A/B b029fgd3t 결과 → 15-A1 ship 여부
- Tier 2 grid 결과 → R1/R2/R3 ship 여부, Phase 4/6c ship 여부
- 15-S1b A/B (FULL 1회) → ML target 변경 여부
- User 결정: R2000 영구 deferred 확정 vs 추후 검토
- User 결정: subscription 출시 시점 → Phase 14 dividend tracking 시급도

---

## 10. 단순 메모

**오늘 한 일**:
- 34+ commits
- Tier 0/1/2 + Phase 13-lite 완전 구현 (default OFF)
- --ab-quick 인프라 + 3 fix
- Stock selection deep audit
- 9-cell A/B grid harness
- SESSION_HANDOFF 두 번 갱신

**진짜 break-through 후보**:
- 15-S1b (ML horizon r_1m → r_3m)
- 15-E (inflection detector)
- Multi-horizon sector RS

**아직 안 하기로 한 것**:
- R2000
- Options flow
- NLP sentiment
- Tax lot accounting
