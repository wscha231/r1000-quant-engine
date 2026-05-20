# Smart Money + ETF Overlay 통합 계획서

작성일: 2026-05-20
작성자: Claude (Opus 4.7)
대상: SEC 13F/Form4 + ETF leadership 시그널을 기존 R1000 엔진에 정량적으로 통합

---

## 1. 현재 baseline (verdict 2026-05-13, commit 4333fcd)

| 지표 | 값 | 95% Bootstrap CI |
|---|---:|---:|
| CAGR | 29.19% | [17.43%, 46.60%] |
| Sharpe | 1.7249 | [1.12, 2.59] |
| MaxDD | -17.46% | [-21.4%, -6.7%] |
| IR | 1.2652 | — |
| excess_cagr | +16.76% | [+7.0%, +27.9%] |
| **avg_cash_weight** | **20.93%** | (여전히 높음) |
| position_risk_exit_count | 373 | (8년) |
| p_excess_gt_0 | 100% | — |
| p_cagr_gt_25% | 76% | — |

**핵심 관찰**:
- excess_cagr CI [+7%, +28%] → 알파는 통계적으로 robust
- avg_cash 20.93% → 여전히 cash 과다 (target ≤ 10%)
- 본 계획의 목표: SEC + ETF 시그널로 **추가 +2~5pp CAGR + cash drag 감소**

---

## 2. 현재 wired 가중치 (PR #16, conservative starter)

```python
# r1000_config.py
w_sec_institutional_evidence: float = 0.30   # 13F overlay
w_sec_insider_evidence: float = 0.20         # Form 4 overlay
```

**최대 기여도 추정** (institutional + insider 점수 모두 1.0 만점 가정):
- 종목별 score 평균 ~2.0 기준 → SEC overlay 최대 +0.50점 → score 25% 추가
- 보수적 starter — codex 문서 권장 "IC validated 전까지 작게"

**문제**: 현재 SEC 아티팩트 미생성 → 가중치 효과는 0
**해결**: Step 2/3 워크플로우 트리거 후 측정

---

## 3. 핵심 문제: 가중치를 어떻게 정할 것인가?

### 옵션 A — 고정 가중치 (현재 방식)
- 장점: 단순, 즉시 적용 가능
- 단점: IC 검증 없음, 데이터 손실 시 silent degradation

### 옵션 B — Data-driven 학습 가중치 (codex 설계, 권장)
- `tools/run_sec_evidence_learning_pipeline.py`가 이미 구현됨
- 각 시그널의 forward-return IC + decile spread 측정
- 결과 → `outputs/sec_evidence_learning/best_score_weights.json`
- 장점: 통계적 근거, 시그널이 죽으면 자동 0
- 단점: 학습용 데이터 (Q1 13F + 8년 candidate replay) 필요

### 옵션 C — Hybrid (제안)
- Phase 1: 고정 0.30/0.20 starter로 첫 full_rebuild
- Phase 2: 학습 파이프라인 실행, IC 측정
- Phase 3: IC 검증된 가중치로 재학습 + A/B

---

## 4. 통합 계획 (4 Phase)

### Phase α — SEC 데이터 수집 + IC 측정 (2일)

**1.1 sec_13f_quarterly_refresh.yml 트리거** (수동, GitHub UI)
- 입력: master 브랜치, 34 verified managers
- 출력: `outputs/sec_institutional_signals/signals_latest.parquet`
- 컬럼: `sec_13f_smart_money_score`, `institutional_evidence_score`, `institutional_evidence_confidence_score`, `sec_13f_crowding_score`

**1.2 sec_form4_daily_refresh.yml 트리거**
- 출력: `outputs/sec_ownership_signals/signals_latest.parquet`
- 컬럼: `sec_form4_net_buy_score`, `early_evidence_score`, `evidence_confidence_score`

**1.3 sec_evidence_learning_manual.yml 트리거** (학습)
- 입력: 8년 candidate replay + Q1 2026 13F + 30일 Form 4
- 처리: 시그널별 IC + decile spread + top-k 초과수익률 측정
- 출력: `outputs/sec_evidence_learning/best_score_weights.json`

**측정 항목**:
| 시그널 | 목표 IC | 통과 기준 |
|---|---:|---|
| institutional_evidence_score | ≥ 0.02 | top decile excess return ≥ +1.0%/mo |
| early_evidence_score (Form 4) | ≥ 0.015 | cluster buy hit rate ≥ 55% |
| sec_13f_breadth_score | ≥ 0.02 | 5+ managers 합의 명 평균 초과 ≥ +0.8%/mo |
| sec_13f_crowding_score | ≤ -0.01 | 15+ managers 종목 평균 underperform |
| sec_form4_sale_risk_score | ≤ -0.005 | sale-only 종목 평균 약세 |

**Phase α 결과 후 결정 트리**:
- IC ≥ 0.02 → 가중치 0.30 유지/상향
- 0.01 ≤ IC < 0.02 → 가중치 0.15로 하향
- IC < 0.01 OR negative → 가중치 0.0 (시그널 비활성화)

---

### Phase β — Smart Money Top30 독립 상품 (3일)

hedgefollow.com 비슷한 standalone 출력. R1000 본 엔진과 별도.

**1.4 신규 도구: `tools/run_smart_money_top30.py`**

입력:
- `outputs/sec_institutional_signals/signals_latest.parquet`
- `outputs/sec_ownership_signals/signals_latest.parquet`
- `research/sec_13f_manager_universe_20260519/managers.csv` (성과 데이터)

랭킹 공식 (hedgefollow + 우리 강점):
```
smart_money_score =
    w_breadth     * sec_13f_breadth_score           # 합의도 (N funds)
  + w_quality     * manager_quality_weighted_score  # 매니저 성과 가중
  + w_conviction  * top_manager_position_weight     # 톱 매니저 within-portfolio %
  + w_insider     * sec_form4_net_buy_score         # 인사이더 매수
  + w_convergence * (institutional AND insider)      # 둘 다 매수 보너스 (×1.5)
  - w_crowding    * sec_13f_crowding_score          # 과밀 페널티
  - w_stale       * sec_13f_stale_days              # 신선도 페널티
```

가중치 starter:
| 구성 | 가중치 | 근거 |
|---|---:|---|
| breadth | 0.30 | 다수 합의 신뢰도 |
| quality | 0.25 | Whalerock +198% > Fisher +93% 가중 |
| conviction | 0.15 | 톱 매니저 within-book 비중 |
| insider | 0.15 | Form 4 cluster buy |
| convergence | 0.10 | institutional + insider 동시 |
| crowding | 0.10 | NVDA-class 과밀 페널티 |
| stale | 0.05 | 90일+ 미갱신 페널티 |

**출력**:
- `outputs/smart_money/top30_latest.csv` — 30 개 랭킹
- `outputs/smart_money/conviction_explainer.md` — 자연어 설명
  ("AMZN: 12개 top funds 동시 매수, CEO $5M Form 4 buy, breadth_rank #3")

**우리만 가진 차별점**:
- hedgefollow: 13F만 / 우리: 13F + Form 4 + 펀더멘털(SEC 10-Q) + RS + 모멘텀
- ETF 시그널 추가 (Phase γ)

---

### Phase γ — ETF Leadership Overlay (2일)

**1.5 기존 thematic_etf_universe.yaml 활용**

이미 작업 시작된 부분 (이전 채팅에서 언급): 신규/레버 제외 상승 ETF top-5 holdings 월 1회 편입.

신규 도구:
- `tools/refresh_etf_top_holdings.py` (월간 cron)
- 대상 ETF: ARKK, QQQE, SMH, XLE, KWEB, 양자컴 ETF(QTUM, BUG), eVTOL(CRPT), AI(BOTZ), 우주(UFO)

ETF top-5 holdings → score bonus:
```python
score_etf_overlay = w_etf * etf_leadership_score * etf_relative_strength
```

가중치 starter: `w_etf_overlay: float = 0.15`

**조건**:
- ETF 자체가 6mo RS > 0
- ETF AUM > $100M (작은 ETF 제외)
- 종목이 ≥ 3개 leading ETF에 포함될 때 보너스 ×1.3

---

### Phase δ — Engine 통합 + A/B Cloud Rebuild (1일)

**1.6 통합 시나리오 4개 A/B**

| 시나리오 | SEC 13F | SEC Form4 | ETF | 예상 결과 |
|---|:-:|:-:|:-:|---|
| **A** (current baseline) | OFF | OFF | OFF | CAGR 29.19% (현재) |
| **B** (SEC만) | ON 0.30 | ON 0.20 | OFF | CAGR ~30-32% 예상 |
| **C** (ETF만) | OFF | OFF | ON 0.15 | CAGR ~30% 예상 |
| **D** (모두 + IC 검증) | learned | learned | learned | **목표: CAGR 32%+ / Sharpe 1.85+** |

**SHIP 게이트** (시나리오 D 대 A):
- dCAGR ≥ +1.5pp
- dSharpe ≥ -0.05
- dMaxDD ≥ -3pp
- early_scout ≥ 4

**REJECT 조건**:
- 시나리오 D < B 또는 D < C → 통합으로 인한 노이즈 (시그널 분리)
- D Sharpe < 1.7 → 변동성 증가

---

## 5. 가중치 결정 매트릭스 (사용자 핵심 질문)

### 권장: **2단계 가중치 정책**

#### 단계 1 — Bootstrap (즉시, 1주)
```python
# r1000_config.py
w_sec_institutional_evidence: float = 0.30  # 현재 starter 유지
w_sec_insider_evidence: float = 0.20        # 현재 starter 유지
w_etf_overlay: float = 0.15                  # 신규
w_smart_money_convergence_bonus: float = 0.10  # 신규 (insider + institutional)
```

총 score 기여도: 최대 +0.75 (score 평균 2.0 기준 ~37% 추가)

#### 단계 2 — Learned (Phase α 완료 후)
학습 파이프라인 결과를 보고 적용:

```python
# 가중치 결정 공식
w_signal = clip(
    IC_decile_spread × confidence_factor,
    lower=0.0,
    upper=0.40
)

# confidence_factor = sqrt(observation_count / 1000)
# 1000개 이상 obs면 1.0, 100개면 0.32
```

예상 학습 결과 범위 (codex 권장):
| 시그널 | 학습 가중치 범위 |
|---|---:|
| institutional_evidence | 0.15 ~ 0.40 |
| insider (Form 4 cluster) | 0.10 ~ 0.30 |
| manager_quality_weighted | 0.10 ~ 0.25 |
| breadth (consensus) | 0.10 ~ 0.20 |
| crowding penalty | -0.05 ~ -0.15 |
| stale penalty | -0.02 ~ -0.08 |

---

## 6. Regime-Adaptive 가중치 (선택, Phase ε)

레짐별로 SEC 시그널 효과가 다를 수 있음:

| Regime | SEC 가중치 조정 | 근거 |
|---|---|---|
| **bull/strong_bull** | × 1.2 | 기관 매수가 모멘텀 강화 |
| **neutral** | × 1.0 | baseline |
| **bear** | × 0.6 | 헷지펀드도 손실, 시그널 노이즈 ↑ |
| **deep_bear** | × 0.3 | 인사이더 매수만 신뢰 (저점 매수) |

구현: `r1000_pipeline.py:add_total_score_columns()`에서 `regime_state` 컬럼 읽어 곱셈.

---

## 7. 실행 순서 (Critical Path)

```
[지금 즉시]
  ├─ Step 2: GitHub UI에서 sec_13f_quarterly_refresh.yml 트리거 ←
  └─ Step 3: GitHub UI에서 sec_form4_daily_refresh.yml 트리거

[1일차 (오늘 저녁)]
  └─ Phase α: sec_evidence_learning_manual.yml 트리거
       → IC 결과 분석 → 가중치 결정

[2~3일차]
  ├─ Phase β: tools/run_smart_money_top30.py 작성
  └─ Phase γ: refresh_etf_top_holdings.py + thematic_etf_universe.yaml

[4일차]
  └─ Phase δ: A/B 4-scenario cloud rebuild

[5일차]
  └─ 결과 분석 → master rotate (SHIP 시) 또는 weight 재조정 (PARTIAL 시)
```

---

## 8. 위험 + 대응

| 위험 | 대응 |
|---|---|
| Q1 13F 데이터 적음 (5월 mid 마감 직후) | Q4 2025 + Q1 2026 데이터 모두 사용; coverage_pct 측정 |
| 인사이더 매수가 noise (소규모 매수) | $50K 이상 + cluster buys (≥2 insiders) 필터 |
| 매니저 성과 가중치가 momentum chasing | Bootstrap CI 측정, p_excess_gt_0 ≥ 0.7 필수 |
| ETF 포지션 dilution | top-5 holdings만, ETF top 30%만 채택 |
| SEC 시그널 + 기존 sleeve 충돌 | LATEST-only 유지 (백테스트 미적용), 추가만 가능 |

---

## 9. 다음 작업 (사용자 결정 필요)

**즉시 가능**:
- [A] GitHub UI에서 워크플로우 트리거 (Step 2/3) → Phase α 시작
- [B] Phase β `run_smart_money_top30.py` 코드 작성 시작 (SEC 데이터 없어도 골격 가능)
- [C] Phase γ `refresh_etf_top_holdings.py` 코드 작성 시작
- [D] Regime-adaptive 가중치 (Phase ε) 우선 구현

**권장**: A 후 B, C 병렬 작성. 데이터 들어오면 D 실행.

---

## 10. 핵심 차별점 요약

| 항목 | hedgefollow | 우리 |
|---|:-:|:-:|
| 13F 매니저 추적 | ✅ | ✅ (34개 verified) |
| Form 4 인사이더 | ✅ | ✅ |
| AI 랭킹 설명 | ✅ (유료) | 🟡 (템플릿 가능) |
| 펀더멘털 통합 (10-Q) | ❌ | ✅ (SEC EDGAR 8년) |
| 기술적 신호 (RS, MA, 모멘텀) | ❌ | ✅ |
| 매크로 레짐 게이트 | ❌ | ✅ |
| 자동 리스크 관리 (DD breaker) | ❌ | ✅ |
| ETF 테마 통합 | ❌ | 🟡 (계획) |
| 8년 walk-forward 검증 | ❌ | ✅ |
| 학습 가중치 (IC validated) | ❌ | ✅ (파이프라인 구현됨) |

**결론**: hedgefollow는 standalone 13F+Form4 상품. 우리는 같은 시그널을 **더 풍부한 컨텍스트와 검증된 가중치**로 결합 가능. 본 계획서대로 5일 작업이면 hedgefollow 대비 우월한 시스템 달성 가능.
