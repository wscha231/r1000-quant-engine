# Credible Target Roadmap — Back to Main 35%/-25%, Conc 50%/-25%

> **목표**: full-period CAGR/MDD를 **신빙성 있게** 원래 목표치(Main 35%/-25%, Conc 50%/-25%)까지 복귀.
> **핵심 정직성**: "올리기"와 "신빙성 있게 만들기"는 **단기적으로 상충**한다. 이 문서는 그 상충을 직시하고 2단계로 푼다.
> 작성 2026-06-19. 검증: `[GITHUB]` origin/master 직접 분석.

---

## 1. 현재 정직한 위치 (GitHub/Codex 분석 결과)

### 1.1 Ledger 추이 (검증됨, origin/master)

| run | commit | Main full | Main IS | Main MDD | Conc full | Conc IS | Conc MDD |
|---|---|---|---|---|---|---|---|
| 27457206698 | a8b271ea | 34.5% | 22.1% | -26.0% | 44.9% | 21.7% | -25.8% |
| 27498401423 | d42daf82 | 34.3% | 21.5% | -25.9% | 44.6% | 21.3% | -25.9% |
| 27516185696 | cd48042 (bull-floor) | **35.2%** | **22.9%** | **-24.5%** | 44.4% | 22.4% | -25.9% |
| 27614583121 | 0c59381 (현재) | 35.0% | 22.4% | -26.1% | 45.0% | 21.6% | -25.8% |

**목표**: Main 35% / -25%, Conc 50% / -25%.

### 1.2 목표까지 거리 (full CAGR 기준)

| | 현재 full | 목표 | 갭 | 현재 IS (정직) | IS 기준 갭 |
|---|---|---|---|---|---|
| Main CAGR | 35.0% | 35% | **0pp (이미 도달)** | 22.4% | **-12.6pp** |
| Main MDD | -26.1% | -25% | **-1.1pp** | — | — |
| Conc CAGR | 45.0% | 50% | **-5.0pp** | 21.6% | **-28.4pp** |
| Conc MDD | -25.8% | -25% | **-0.8pp** | — | — |

### 1.3 GitHub/Codex 분석 — 무엇이 됐고 안 됐나

**✅ 됐다:**
- PR #64-79 머지 — loop closure, coordination, daily operations 하드닝 (16개 PR)
- Codex가 alpha-방향 sidecar 생성 + wire: `run_era_aware_scoring_challenger`, `run_era_leadership_sidecar`, `run_crisis_paper_order_bridge`, `run_adr_candidate_scanner` (전부 sidecar에 wire됨)

**⚠️ 문제:**
- `latest_global_alpha_universe` metrics가 **IS=0.00%, strengthened=None** — 최신 symlink가 Tier-2 이전 run을 가리키거나 account_evaluation 재구현이 is_cagr 필드를 잃음 (**회귀**)
- bull-floor 검증 win(+1.45pp Main / +1.12pp Conc)이 **여전히 default OFF** — 안 켜짐
- era/crisis 도구가 전부 **challenger/sidecar(shadow)** — production scoring 미접근
- selection 엔진(`r1000_pipeline.py`) 3일+ 변경 0
- 61개 orphan 브랜치 (지난 분석)

### 1.4 한 줄 진단

**Main full 35%는 이미 목표에 닿았지만 그건 OOS 부풀림이고, 정직한 엔진은 22%다. Conc는 full로도 5pp 부족하고 정직하게는 28pp 부족하다. Codex는 부지런했지만 전부 sidecar/safety 축에 머물러 selection 엔진(=full CAGR을 진짜 올리는 곳)은 안 건드렸다.**

---

## 2. 직시할 상충 — "올리기" vs "신빙성"

### 2.1 핵심 역설

사용자 목표 = **"신빙성 있는 전체기간 CAGR을 35/50까지 올린다"**. 그런데:

- **PIT universe(Workstream C)를 적용하면 full CAGR이 떨어질 가능성이 크다.** 현재 우주는 2024-25 승자(NVDA, BE, ASML) 위주 = survivorship bias가 full CAGR을 부풀리고 있음. 이걸 제거하면 Conc full 45% → ~35% 정도로 압축될 수 있음.
- 즉 **"신빙성 있게 만들기"의 첫 효과는 headline 하락**이다.

### 2.2 그래서 두 가지를 분리해야 한다

```
지금 full CAGR 45% (Conc) = [진짜 알파] + [survivorship 부풀림] + [OOS 행운] + [market β]

목표: credible full CAGR 50%
     = [진짜 알파를 키워서] credible basis 위에서 50% 달성

단계:
  Phase 1 (신빙성 확립): 부풀림/행운/β를 측정·제거 → headline 떨어짐 (45%→~35%?)
                          이게 "진짜 출발선"
  Phase 2 (진짜 올리기): credible basis에서 진짜 알파로 35%→50%
```

**Phase 1 없이 Phase 2 하면**: OOS 행운을 더 쌓는 것 = 환상 위의 환상.
**Phase 1만 하면**: headline 떨어지고 끝 = 사용자 불만.
**둘 다 해야**: 정직하게 목표 달성.

### 2.3 정직한 기대치

| 시점 | Conc full CAGR | 의미 |
|---|---|---|
| 지금 | 45% | survivorship + OOS 부풀림 포함 |
| Phase 1 후 | ~33-38% (예상) | credible. 진짜 출발선. **일시적으로 낮아 보임** |
| Phase 2 후 (목표) | 45-50% credible | 진짜 알파로 달성 |

**Main도 동일**: 지금 35%(부풀림) → Phase 1 후 ~30% credible → Phase 2 후 35% credible.

---

## 3. 2단계 로드맵

### Phase 1 — 신빙성 확립 (6주, Codex v2 plan)

이미 작성된 **`docs/CODEX_IMPLEMENTATION_PLAN_7Y_FULL_CAGR_PIT.md` (v2)** 가 Phase 1이다:

| Workstream | 산출 | Phase 1 기여 |
|---|---|---|
| A. 7Y lock | 8/10Y proxy 차단 | 부풀림 방지 |
| B. Credibility 6도구 | α/β 분해, walk-forward, bootstrap CI, cost stress, regime, start-date | **45%의 진짜 정체 파악** (얼마가 알파/β/행운인가) |
| C. PIT universe | survivorship 제거 | **credible 출발선 확정** (headline 떨어질 수 있음) |

**Phase 1 종료 시 답하는 질문**:
- Conc 45% 중 진짜 알파는 몇 %인가? (B2 factor: α_share)
- survivorship 제거하면 몇 %인가? (C: PIT universe A/B)
- 단일 OOS 행운 빼면 몇 %인가? (B1: walk-forward)
- → **credible Conc CAGR = X%** (출발선 확정)

### Phase 2 — credible basis에서 진짜 목표 달성 (8-12주)

Phase 1이 끝나면 비로소 **진짜 알파 레버**로 올린다. 이게 §4.

---

## 4. Phase 2 — full CAGR을 진짜 올리는 레버 (credible 기준)

신빙성 측정/PIT는 **CLARIFY**(명확히)할 뿐 **RAISE**(올리기)는 안 한다. 진짜 올리는 건 아래 4개:

### 4.1 Lever 1 — Bull-floor promote (검증됨, 즉시 +1pp) ⭐⭐

- 이미 A/B로 검증: Main IS +1.45pp, Conc IS +1.12pp, Main MDD +1.44pp 개선.
- **그런데 default OFF로 안 켜져 있음.** 켜기만 하면 즉시 +1pp credible (OOS 부풀림 아님 — IS도 올랐으니).
- 별도 alpha PR (v2 plan A1 범위 밖, 명시적으로 분리함).
- **비용: 1일. 효과: +1pp credible. ROI 최고.**

### 4.2 Lever 2 — Era-aware scoring을 challenger→production (가장 큰 lever) ⭐⭐⭐

- Codex가 `run_era_aware_scoring_challenger.py` 만들어서 sidecar로 wire함 — 하지만 **challenger(shadow)**, production scoring 미접근.
- F1 발견: single global 모델이 2020 software와 2024 AI를 같은 계수로 평가 → IS-CAGR 22% 천장.
- **Phase 2 핵심**: challenger를 production scoring에 env-gated A/B로 연결.
  - 먼저 `run_era_leadership_sidecar`의 **per-era IC 매트릭스** 확인 (GO/NO-GO 게이트)
  - 2020 software era에서 profitability_inflection IC<0면 → era 분리 정당
  - env `PHASE_ERA_AWARE_SCORING_ENABLED` A/B → ledger 측정
- **이게 IS-CAGR 22%→28%+를 만들 유일한 단일 lever** (selection 엔진 수정).
- **비용: 2-3주 (challenger는 이미 있으니 wire + A/B). 효과: credible +3-8pp 잠재.**

### 4.3 Lever 3 — PIT universe가 IS-CAGR을 올릴 수도 (양면) ⭐⭐

- C(PIT universe)는 full CAGR을 떨어뜨리지만(survivorship 제거), **IS-CAGR은 올릴 수 있음**.
- 이유: PIT-aware feature가 그 시점 진짜 leader를 더 정직하게 식별 → 2021/2023 bull underinvestment 같은 leak 완화 가능.
- 즉 C는 Phase 1(신빙성)이면서 동시에 Phase 2(IS-CAGR alpha) lever.
- **비용: Phase 1에 포함. 효과: IS-CAGR +2-4pp 잠재 (full은 떨어지지만 IS는 오름).**

### 4.4 Lever 4 — Concentrated 종목 수/sizing 재설계 (Conc 전용) ⭐

- Conc가 50% 목표에서 가장 멀음. 5종목 집중이 노이즈 증폭.
- 후보(각각 독립 A/B): continuation winner relaxation, theme leadership boost.
- **단 concentration cap 완화는 MDD 위험 — 보류.**
- **비용: 각 1주. 효과: Conc credible +2-3pp.**

---

## 5. MDD를 -25% 안으로 (credible)

현재 Main -26.1%, Conc -25.8% — 둘 다 목표 -25% 살짝 초과.

### 5.1 Lever — Crisis paper bridge를 production cash로 ⭐⭐

- Codex가 `run_crisis_paper_order_bridge.py` 만들어 wire함 — 하지만 **paper/review-only**.
- F2 발견: crisis 신호→행동 1-30일 지연 (월 1회 rebalance에 갇힘).
- **Phase 2**: 일별 crisis_state 전이 시 cash override를 broker book에 inject (이전 P0.2 설계).
- 효과: MDD trough를 막아 -26% → -23% 가능.
- **비용: 1주 (bridge 이미 있으니 production wire). 효과: MDD -2~3pp 개선.**

### 5.2 Lever — Bull-floor가 이미 MDD 개선

- bull-floor A/B에서 Main MDD -25.93→-24.49 (+1.44pp). 켜기만 하면 MDD도 좋아짐.

---

## 6. "목표 달성"을 부를 수 있는 기준 (credible)

**중요**: 다음을 모두 만족해야 "credible 35/50 달성"이라 부른다 (full CAGR 단독 금지):

| 조건 | 기준 |
|---|---|
| Full CAGR | Main ≥ 35%, Conc ≥ 50% (broker_ledger_next_close, PIT universe ON) |
| IS-CAGR | Main ≥ 28%, Conc ≥ 30% (정직한 엔진) |
| OOS/IS ratio | ≤ 3.0x (Tier-2) |
| Factor α-share | ≥ 30% (full CAGR의 30%+가 진짜 알파, β 아님) |
| Start-date robustness | range ≤ 15pp (not FRAGILE) |
| Bootstrap CI | width ≤ 25pp (not LOOSE) |
| MDD | Main ≥ -25%, Conc ≥ -25% |
| Cost robustness | 100bps에서 CAGR > 25% |
| Regime concentration | not DIRECTIONAL (bear에서도 안 무너짐) |

이 9개를 다 통과하는 35/50이 **진짜 목표 달성**. 지금 full 35%/45%는 이 중 IS/ratio/α-share에서 fail.

---

## 7. 전체 타임라인 (Phase 1 + Phase 2)

```
주 1-6   Phase 1 (Codex v2 plan, 12 PR):
          - 7Y lock
          - 6 credibility 도구 → 45%의 진짜 정체 파악
          - PIT universe → credible 출발선 (headline 떨어질 수 있음)
          산출: "credible Conc CAGR = X%" 확정 + 9개 신빙성 지표 baseline

주 4-6   (Phase 1과 병렬) Lever 1: bull-floor promote (1일, +1pp)
          Lever 2 준비: per-era IC 매트릭스 확인 (GO/NO-GO)

주 7-10  Phase 2-A: era-aware scoring challenger → production A/B
          (selection 엔진 첫 수정, IS-CAGR alpha)

주 9-12  Phase 2-B: crisis paper bridge → production cash (MDD)
          Conc continuation winner relaxation A/B

주 13-16 Phase 2-C: 통합 측정. 9개 신빙성 지표로 "목표 달성" 판정
          credible 35/50 도달 여부 확정
```

**총 ~4개월.** Phase 1(신빙성)이 끝나야 Phase 2(올리기)가 의미 있음.

---

## 8. 즉시 다음 액션 (이번 주)

| 우선 | 액션 | 담당 | 비고 |
|---|---|---|---|
| P0 | `latest_global_alpha_universe` IS=0.00 회귀 조사 | Claude | account_evaluation 재구현이 is_cagr 잃었는지 |
| P0 | bull-floor promote (별도 alpha PR) | Codex | 검증된 +1pp, 안 켜져 있음 |
| P0 | Codex v2 plan(Phase 1) 시작 — A1 7Y lock부터 | Codex | `docs/CODEX_IMPLEMENTATION_PLAN_7Y_FULL_CAGR_PIT.md` |
| P1 | per-era IC 매트릭스 확인 (era_leadership_sidecar 출력) | Claude/Codex | Phase 2 GO/NO-GO |
| P1 | 61 orphan 브랜치 정리 | 사용자 | 위생 |

---

## 9. 정직한 결론 (사용자에게)

**"신빙성 있는 전체기간 CAGR/MDD를 35/50까지 올린다"는 목표는 옳고 달성 가능하지만, 두 단계를 거쳐야 합니다:**

1. **Phase 1 (신빙성)**: 지금 full 45%가 얼마나 진짜인지 측정하고 PIT universe로 부풀림을 제거합니다. **이 단계의 첫 효과는 headline이 ~35%로 떨어지는 것**일 수 있습니다 — 그게 진짜 출발선입니다. 떨어진다고 후퇴가 아니라, 처음으로 정직한 숫자를 보는 것입니다.

2. **Phase 2 (올리기)**: credible 출발선에서 진짜 알파(era-aware 모델, bull-floor, PIT-aware selection)로 35/50까지 올립니다. 이게 OOS 행운 모방이 아닌 진짜 성장입니다.

**가장 큰 단일 lever는 era-aware scoring을 challenger에서 production으로 승격하는 것**입니다 (F1 — single global 모델이 IS 22% 천장의 원인). Codex가 challenger는 이미 만들었으니, per-era IC 확인 후 production A/B만 하면 됩니다.

**즉시 할 일**: (a) bull-floor 켜기 (검증된 +1pp, 공짜), (b) `latest` IS=0.00 회귀 조사, (c) Codex v2 Phase 1 시작.

---

**End of Credible Target Roadmap — 2026-06-19 KST.**
Author: Claude Code. 검증: origin/master ledger + account_evaluation 직접 분석.
Companion: `docs/CODEX_IMPLEMENTATION_PLAN_7Y_FULL_CAGR_PIT.md` (Phase 1 실행 상세).
