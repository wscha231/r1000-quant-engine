# Master Priority Roadmap — 2026-06-19 KST

> **사용자 결정 종합**: (1) 18 PR 중 작업 우선순위 (2) GitHub Pages 활성화 (3) Phase 2 alpha lever 우선순위 + 계획.
> 기존 plan들 (`v2`, `WALKFORWARD_PUBLIC_REPORT`, `CREDIBLE_TARGET_ROADMAP`) 의 상위 마스터.
> 정직성 원칙: 신뢰성 확립 (Phase 1) → CAGR/MDD 올리기 (Phase 2). 환상 위 환상 안 쌓는다.

---

## 1. STAGE 우선순위 (4 stage, 7주)

각 stage는 직전 stage의 산출물에 의존. 병렬 가능한 작업은 `║` 표시.

```
┌───────────────────────────────────────────────────────────────────────┐
│ STAGE 0 — 이번 주 (2-3일)  "공짜 점수 + 게이트"                       │
├───────────────────────────────────────────────────────────────────────┤
│ S0.1  사용자: GitHub Pages 활성화 (§2 절차)                  [10분]   │
│ S0.2  Codex:  A1 — 7Y lock + 8/10Y proxy 차단                [1일]   │
│ S0.3  Codex:  bull-floor promote (별도 alpha PR)             [1일]   │
│       └─ 검증된 +1pp Main IS / +1pp Conc IS / +1.4pp Main MDD         │
└───────────────────────────────────────────────────────────────────────┘
                                ↓
┌───────────────────────────────────────────────────────────────────────┐
│ STAGE 1 — 주 1-3  "신뢰성 핵심 4개"  → 7Y CAGR이 진짜인지 확인        │
├───────────────────────────────────────────────────────────────────────┤
│ S1.1  Codex:  W1 Embargo Audit               [2일]                    │
│       └─ 84 retrain 모두 126일 gap 지켰는지 자동 검증                 │
│ S1.2  Codex:  W2 True 7Y WF OOS CAGR         [3일]                    │
│       └─ 7년 전 구간이 진짜 walk-forward OOS임을 증명                 │
│ S1.3  Codex:  W4 Decision Provenance         [2일]      ║             │
│       └─ "12개월간 OOS 보면서 한 결정" 추적 → meta-leakage 정직 공개  │
│ S1.4  Codex:  B2 Factor α/β Attribution      [3일]      ║             │
│       └─ Conc 45% 중 진짜 알파는 몇 %인가 답                          │
│                                                                       │
│ 종료 기준: W1 verdict CLEAN + W2 yearly_geomean ≈ full CAGR (±0.5pp)  │
│            + B2 α_share 측정값 확보                                   │
└───────────────────────────────────────────────────────────────────────┘
                                ↓
┌───────────────────────────────────────────────────────────────────────┐
│ STAGE 2 — 주 3-5  "공개 가능 보고서 + 나머지 신뢰성"                  │
├───────────────────────────────────────────────────────────────────────┤
│ S2.1  Codex:  W5 Public Report               [2일]                    │
│ S2.2  Codex:  AUTO Auto-publish workflow     [1일]                    │
│       └─ 공개 URL 가동: github.io/r1000-quant-engine                  │
│ S2.3  Codex:  W3 Combinatorial CV            [2일]      ║             │
│ S2.4  Codex:  B1 Walk-forward CAGR sidecar   [2일]      ║             │
│ S2.5  Codex:  B3 Start-date sensitivity      [1일]      ║             │
│ S2.6  Codex:  B4 Bootstrap CI                [1일]      ║             │
│ S2.7  Codex:  B5 Cost stress                 [2일]      ║             │
│ S2.8  Codex:  B6 Regime decomposition        [1일]      ║             │
│                                                                       │
│ 종료 기준: 9개 신뢰성 지표 모두 측정 + public URL live                │
└───────────────────────────────────────────────────────────────────────┘
                                ↓
┌───────────────────────────────────────────────────────────────────────┐
│ STAGE 3 — 주 5-7  "PIT universe — 가장 큰 신뢰성 lever"               │
├───────────────────────────────────────────────────────────────────────┤
│ S3.1  Codex:  C1 Historical R1000 membership ETL  [5일]               │
│ S3.2  Codex:  C2 PIT ADR/cycle scanner            [4일]   ║           │
│ S3.3  Codex:  C3 13F/Form4 PIT candidates         [3일]   ║           │
│ S3.4  Codex:  C4 Universe builder integration     [4일]               │
│       └─ env-gated default OFF, A/B 측정                              │
│ S3.5  Codex:  C5 Semi-annual auto-schedule        [2일]               │
│                                                                       │
│ 종료 기준: PIT universe A/B 결과 ledger에 row 추가                    │
│           Public report에 "PIT-clean" 라벨 가능 (caveat 제거)         │
│           Phase 1 신뢰성 baseline 확정 (= credible 출발선)            │
└───────────────────────────────────────────────────────────────────────┘
                                ↓
┌───────────────────────────────────────────────────────────────────────┐
│ STAGE 4 — Phase 2 (주 7-15)  "CAGR/MDD 진짜 올리기"                   │
├───────────────────────────────────────────────────────────────────────┤
│  → 별도 §3 (이 문서 §3)                                               │
└───────────────────────────────────────────────────────────────────────┘
```

### 1.1 STAGE 결정 근거 (왜 이 순서인가)

| Stage | 이유 |
|---|---|
| **S0** 이번 주 | A1 7Y lock 없으면 proxy 8/10Y가 다시 시도될 위험. bull-floor는 검증된 공짜 점수, 안 켤 이유 없음 |
| **S1** 핵심 4 | W1 (embargo audit) 없으면 "7Y CAGR이 진짜 OOS냐"에 답 못 함. W2/W4/B2가 "신뢰성"의 핵심 4가지 |
| **S2** 공개 + 나머지 | S1이 끝나야 W5 public report가 "신빙성 있는 결과"라고 보여줄 수 있음 |
| **S3** PIT universe | 가장 큰 신뢰성 lever지만 18일 소요 — S0-S2가 끝나야 Phase 1 결과 명확하게 측정 가능 |
| **S4** Phase 2 | Phase 1이 끝나야 credible baseline 위에서 진짜 알파 lever 효과 측정 가능 |

### 1.2 Stage별 GO/NO-GO 게이트

| 게이트 | 통과 조건 | 실패 시 |
|---|---|---|
| **S0 → S1** | bull-floor promote PR 머지 + ledger 새 row | bull-floor 회귀 시 즉시 revert + 원인 분석 |
| **S1 → S2** | W1 verdict CLEAN AND W2 yearly_geomean ≈ full CAGR (±0.5pp) | 매칭 안 되면 broker_replay 또는 walk-forward 코드 버그 의심 — 사용자 보고 |
| **S2 → S3** | Public URL live + 9 indicator 모두 측정값 보유 | 부분 측정 (≤7개) 상태로 S3 시작 가능 |
| **S3 → S4 (Phase 2)** | C4 A/B 결과 ledger + B2 α_share 값 + per-era IC 매트릭스 (era_leadership_sidecar 출력) | 셋 중 하나 빠지면 S4 알파 lever 선택 근거 부족 — S3 보완 후 진행 |

---

## 2. GitHub Pages 활성화 (사용자 수동, 10분)

### 2.1 사전 준비 (Codex가 PR로 만듦, AUTO workflow의 일부)

`docs/public/` 디렉토리 + placeholder `index.html`:
```
docs/public/
├── index.html       (W5가 자동 생성, 처음엔 placeholder)
├── report.md        (W5 자동 생성)
├── report.html      (W5 자동 생성)
└── data.json        (W5 자동 생성)
```

### 2.2 사용자 활성화 단계 (정확)

```
1. https://github.com/wscha231/r1000-quant-engine/settings/pages 접속

2. "Build and deployment" 섹션:
   - Source:        Deploy from a branch
   - Branch:        master
   - Folder:        /docs/public/   ← 중요: /docs 아니라 /docs/public
   - "Save" 클릭

3. 1-2분 후 페이지 상단에:
   "Your site is live at https://wscha231.github.io/r1000-quant-engine/"

4. 처음엔 placeholder 페이지 (Codex가 만들 W5 PR 머지 전).
   머지 후 다음 weekly cron이 실제 7Y report로 채움.

5. (선택) Custom domain: 사용자가 원하면 Settings → Pages → Custom domain.
   예: performance.yourdomain.com → CNAME wscha231.github.io
```

### 2.3 활성화 시점

**S0 stage에 활성화**. Codex가 W5/AUTO를 만들기 전 활성화해두면 첫 publish가 즉시 작동.

### 2.4 안전 옵션

처음엔 **Private repo + Pages private** 가능 (GitHub Pro $4/월 또는 Enterprise). 외부 노출 부담스러우면:
- Repo Settings → Pages → "Visibility: Private" 선택 (Pro+ 만)
- 또는 별도 public repo (`r1000-public-report`) 생성 → Codex AUTO가 그쪽으로 push

처음에는 **private repo + private pages** 권장. 공개는 신뢰성 확립 후 (S3 끝) 결정.

---

## 3. Phase 2 — CAGR/MDD 올리기 우선순위 (Stage 4)

Phase 1 (S0-S3) 끝나야 의미 있음. 그러나 미리 우선순위 결정:

### 3.1 4개 lever 평가 (검증 기반)

| # | Lever | 예상 효과 | 비용 | 위험 | 사전조건 |
|---|---|---|---|---|---|
| **L1** | Bull-floor promote (이미 S0에 포함) | +1pp Main/Conc IS, MDD -1.4pp | 1일 | 낮음 | 없음 — S0에서 진행 |
| **L2** | Crisis paper bridge → production cash | MDD -2~3pp | 1주 | 중 (false positive cash raise) | F2 audit + paper 결과 검증 |
| **L3** | Era-aware scoring challenger → production | IS-CAGR +3-8pp **(가장 큰 lever)** | 2-3주 | 높음 (per-regime overfit) | per-era IC GO/NO-GO 게이트 통과 |
| **L4** | Conc continuation-winner relaxation | Conc CAGR +2-3pp | 1주 | 중 (winner-hold 편향) | 없음 (독립 A/B) |

### 3.2 Phase 2 실행 순서 (우선순위 + 의존성)

```
L1 (S0에 이미 포함) ───────────────────┐
                                       │
S3 완료                                │
   ↓                                   │
P2.0  per-era IC 매트릭스 확인  [1주]   │
      └─ era_leadership_sidecar 출력 분석                │
      └─ "2020 software era에서 profitability_inflection IC<0?"
      └─ GO/NO-GO 게이트: positive면 L3 진행, negative면 L3 스킵
                                       │
P2.1  L4 Conc continuation A/B  [1주] ←┤  (병렬 가능)
      └─ 가장 안전, 빠른 측정                            │
                                       │
P2.2  L2 Crisis bridge production [1주]   ║
      └─ paper → production cash override                │
      └─ MDD lever, 알파 lever와 독립적                  │
                                       │
P2.3  L3 Era-aware production A/B [2-3주]  ← GO일 때만   │
      └─ 가장 큰 lever, F1 22% IS 천장 깨기              │
      └─ env-gated, ledger 측정                          │
                                       │
P2.4  통합 측정 [1주]                                    │
      └─ 9 indicator로 "credible 35/50 달성" 판정        │
```

### 3.3 Phase 2 우선순위 결정 근거

**L1 즉시 (S0)**: 검증됨 + 공짜.

**L4 먼저 (Conc continuation)**: 안전성 + 빠른 측정. L3 결과 기다리는 동안 병렬.

**L2 (Crisis bridge)**: MDD lever — CAGR lever와 독립. 알파 lever 진행 중 동시에 가능.

**L3 마지막 + 조건부 (Era-aware)**: 가장 큰 lever지만 가장 위험. **per-era IC 게이트 (P2.0) 통과 후에만**. IC가 era별로 의미 있는 차이 없으면 (예: profitability_inflection IC가 2020/2024 둘 다 positive) era 분리 정당화 안 됨 → 스킵.

### 3.4 Phase 2 종료 — "credible 35/50 달성" 기준 (9 indicator)

S2.7에서 확정한 9개 신뢰성 지표가 다음을 만족할 때 "Phase 2 완료":

| Indicator | Source | 통과 기준 |
|---|---|---|
| 1. Full CAGR | broker_replay metrics | Main ≥ 35%, Conc ≥ 50% |
| 2. IS CAGR | account_evaluation Tier-2 | Main ≥ 28%, Conc ≥ 30% |
| 3. OOS/IS ratio | Tier-2 | ≤ 3.0x |
| 4. Factor α-share | B2 | ≥ 30% |
| 5. Start-date robustness | B3 | not FRAGILE (range ≤ 15pp) |
| 6. Bootstrap CI | B4 | not LOOSE (width ≤ 25pp) |
| 7. MDD | broker_replay | Main ≥ -25%, Conc ≥ -25% |
| 8. Cost robustness | B5 | 100bps에서 CAGR > 25% |
| 9. Regime concentration | B6 | not DIRECTIONAL |

**9개 모두 통과 = 진짜 목표 달성.** 1-2개만 fail이면 추가 lever 또는 측정 보완.

---

## 4. 즉시 다음 7일 행동 (구체)

| 날 | 행동 | 담당 | 산출 |
|---|---|---|---|
| **D1 (오늘)** | GitHub Pages 활성화 §2.2 | 사용자 | URL 라이브 |
| **D1** | A1 7Y lock PR 시작 | Codex | `codex/lock-7y-window-20260619` |
| **D2** | A1 PR 리뷰 + 머지 | ChatGPT Pro + 사용자 | A1 merged |
| **D2** | Bull-floor promote PR 시작 | Codex | `codex/promote-bull-floor-default-on-20260619` |
| **D3** | bull-floor PR 머지 → 다음 weekly cron 트리거 | 사용자 | bull-floor 실제 ON, 다음 ledger row +1pp 예상 |
| **D4** | W1 Embargo Audit PR 시작 | Codex | `codex/wf-embargo-audit-20260619` |
| **D5** | W2 True 7Y WF OOS CAGR PR 시작 | Codex | `codex/wf-true-oos-cagr-20260619` |
| **D6** | W1 머지 + W4 시작 (parallel) | Codex | `codex/wf-decision-provenance-20260619` |
| **D7** | W2 머지 + B2 시작 | Codex | `codex/cagr-factor-alpha-20260619` |

7일 후: A1 + bull-floor + W1/W2 머지 → **이미 신빙성 절반 + 검증된 +1pp 달성**.

---

## 5. Codex prompt 전달 순서

각 stage 시작 시 Codex에 던질 prompt:

| Stage | prompt 파일 | 어디서 시작 |
|---|---|---|
| **S0 A1** | `docs/CODEX_IMPLEMENTATION_PLAN_7Y_FULL_CAGR_PIT.md` §4 | Workstream A 만 발췌 |
| **S0 bull-floor** | 별도 prompt (Stage 0.3 bull-floor only) | 신규 작성 가능, 또는 §5.5 참조 |
| **S1-S2** | `docs/CODEX_WALKFORWARD_PUBLIC_REPORT_PLAN.md` 전체 | W1-W5 + AUTO |
| **S2 (B 도구들)** | `docs/CODEX_IMPLEMENTATION_PLAN_7Y_FULL_CAGR_PIT.md` §5 | Workstream B 발췌 |
| **S3** | 같은 파일 §6 | Workstream C 발췌 |
| **S4 (Phase 2)** | §3.2 흐름대로 별도 prompt 작성 | per-era IC 결과 후 |

### 5.1 권장 — STAGE 0/1/2를 통합 prompt로

지금 commit 된 두 plan을 stage 단위로 발췌해 Codex에 한 번에 던지면 효율적. 다음 prompt 작성 시 `STAGE_0_1_2_COMBINED_PROMPT.md` 형태로 가능.

---

## 6. 정직한 caveat

### 6.1 STAGE 3 (PIT universe) 후 headline 떨어질 가능성

- 현재 우주는 2024-25 승자 위주 (ADR/cycle YAML 2026-05 손큐레이션).
- PIT-clean 적용 시 Conc full CAGR 45% → **~35-38% 예상** (압축).
- 이게 진짜 credible 출발선. **떨어지는 게 후퇴 아님 — 처음 보는 정직한 숫자**.
- Phase 2 lever들이 이 credible 기준에서 다시 50%로.

### 6.2 STAGE 4 (Era-aware)가 negative일 가능성

- per-era IC 매트릭스가 era별 의미 있는 차이를 안 보일 수도.
- 그 경우 L3 스킵 + L1/L2/L4 만으로 진행.
- 최대 효과: +4-5pp credible (L4 + bull-floor + crisis MDD 개선).
- 그래도 35/50까지는 부족할 수 있음 → "credible 출발선 + 4-5pp"가 진짜 엔진 천장일 가능성.

### 6.3 Phase 2 후에도 9 indicator 모두 통과 못 할 가능성

- 가능. 그건 **엔진의 진짜 모습**이 그것이라는 정직한 결론.
- 그 경우 CLAUDE.md targets 재정의 (사용자 결정).
- 또는 추가 alpha source 발굴 (alternative data, 새 feature family).

---

## 7. 한 줄 요약

**STAGE 0 이번 주 = GitHub Pages 활성화 + 7Y lock + bull-floor promote (공짜 +1pp).**
**STAGE 1-3 = Phase 1 신뢰성 (W1-W5 + AUTO + B 도구 + PIT universe).**
**STAGE 4 = Phase 2 CAGR/MDD 올리기 (L1 즉시, per-era IC 게이트 후 L3/L4/L2).**
**최종 = 9 indicator 모두 통과 시 credible 35/50 달성.**

---

**End of Master Priority Roadmap — 2026-06-19 KST.**
참조: `docs/CODEX_IMPLEMENTATION_PLAN_7Y_FULL_CAGR_PIT.md` (v2), `docs/CODEX_WALKFORWARD_PUBLIC_REPORT_PLAN.md`, `docs/CREDIBLE_TARGET_ROADMAP_20260619.md`.
업데이트: 각 stage 종료 또는 GO/NO-GO 게이트 결과 후 재작성.
