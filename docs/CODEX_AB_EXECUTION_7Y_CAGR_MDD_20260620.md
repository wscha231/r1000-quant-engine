# Codex 실행 설계 — 7Y CAGR/MDD 극대화 A/B (즉시 실행용)

- 작성일: 2026-06-20 KST
- 작성 주체: Claude
- 선행: clean 7Y full run on master (run #214 `27873592126`) 완료 후 baseline 확정. 그 전까지는 run #213(clean7y 브랜치) 수치를 잠정 baseline으로 사용.
- 성격: 측정/challenger 전용. **production target/cash/scoring mutation, promotion, live 금지(user 승인 전).** bull-floor promote / T3 / 8Y·10Y / "목표 달성" 판정 제외.
- 모든 knob/메커니즘은 master(`origin/master`) 코드에서 직접 확인한 실제 필드명.

---

## 0. Baseline (run #214 확정 시 갱신)

run #213 잠정값 (master+R1에서 재확인 예정):

| | Main | Conc | 타깃 |
|---|---:|---:|---|
| CAGR | 34.53% | 45.49% | 35% / 50% |
| MaxDD | **−26.06%** | −24.57% | −25% / −25% |
| IS CAGR | 20.37% | 18.87% | ≥25% / ≥30% |
| OOS/IS | 3.91x | 7.66x | ≤3.0 |

2개 결함축: **(A) fast-crash 방어 실패**(2020 COVID Main −26.1%, 현금 24%뿐) / **(B) green-bull cash drag**(2021·2023 과방어 → IS CAGR↓, OOS/IS↑).

---

## 1. A/B 주입 메커니즘 (검증됨)

`full_rebuild_manual.yml` 입력 **`experiment_env_json`** = JSON object. 제약(워크플로 line 191~210에서 강제):
- 키는 정규식 `^(PHASE_|R1000_|ALPHAOPS_)[A-Z0-9_]+$` 만 허용. 그 외 키는 run 거부(exit 2).
- 값은 문자열로 GITHUB_ENV에 기록 → 엔진이 env로 읽음.

**전제(lever별 step-0)**: 대상 cfg 필드가 위 prefix env로 override 가능해야 한다. `PHASE_<KEY>_ENABLED`는 `phase_is_enabled()`로 이미 읽힘. 그러나 `drawdown_breaker_level_1_threshold` 같은 float 필드는 **env-override 훅이 없으면 experiment_env_json으로 못 바꾼다.** → 각 lever 첫 작업 = 해당 cfg 필드에 `R1000_<FIELD>` env-read 훅 1줄 추가(예: `cfg.drawdown_breaker_level_1_threshold = float(os.environ.get("R1000_DD_BREAKER_L1_THRESHOLD", default))`). 이 훅 추가는 측정 인프라이지 정책 변경이 아니다(기본값 불변).

대안(코드 무변경): challenger 경로 `tools/run_era_aware_scoring_challenger.py` / `auto_policy_challenger.py` / `phase_ab_quick_rescore_manual.yml` 가 이미 정책 변형을 측정한다 — 단 cash-overlay 파라미터를 노출하는지 확인 필요.

---

## 2. Family A — Fast-Crash Defense (MDD lever)

### 진단 (실제 기본값)
COVID 급락(2-3주)에서 발동이 느리거나 약함:
- `drawdown_breaker_level_1_threshold=0.12` (DD 12%에서야 1단계), `level_1_cash_floor=0.15`
- `vix_level_tier1_threshold=22.0` → `tier1_cash_floor=0.10`, tier2(28)→0.25
- 2020 실제 현금 24%뿐 → 급락 속도에 floor가 못 따라감.

### A/B 변형 (한 번에 하나)
| ID | 변경 knob (env key 후보) | 가설 |
|---|---|---|
| **A1** | `R1000_DD_BREAKER_L1_THRESHOLD` 0.12→0.08, `L1_CASH_FLOOR` 0.15→0.25 | DD breaker를 더 빨리/세게 → COVID DD 축소 |
| **A2** | `R1000_VIX_TIER1_CASH_FLOOR` 0.10→0.20, `VIX_TIER2_CASH_FLOOR` 0.25→0.40 | VIX 스파이크에 현금 floor↑ → 급락 방어 |
| **A3** | 신규 **dd-velocity** 트리거 (5/10일 낙폭 속도) | 절대 DD가 아닌 *속도*로 선제 차단 (신규 피처 = FULL) |

A1/A2 = cash-overlay 파라미터 → broker replay 단계 → **QUICK/Tier-2 가능**(feature_store 불변). A3 = 신규 시그널 → **FULL rebuild** + `PHASE_FASTCRASH_*` 토글 + keep_cols/hard_sanitize 동기화.

### Family A gate (MDD-repair 전용 — user 승인 필요)
- 1차: **Main MDD ≥ −25%** (현재 −26.06% → ΔMDD ≥ +1.1pp)
- 2차: **ΔCAGR ≥ −1.0pp AND ΔSharpe ≥ −0.05**
- 회귀가드: **2022 약세장 방어 불변**(2022 연도 DD 악화 ≤ +1pp) — crisis cash가 약해지면 안 됨. early_scout ≥ 4.

---

## 3. Family B — Green/Bull Cash Drag 축소 (CAGR + OOS/IS lever)

### 진단 (실제 기본값 — C1 attribution이 정밀화)
- `cash_target_growth_cap=0.0`, `cash_target_balanced_cap=0.0` → growth/balanced regime cap은 **이미 0**. 따라서 2021/2023 과방어(Conc 36%/52%)의 원인은 cap이 아니라:
  - `concentrated_regime_cash_vix_threshold=25.0` (Conc는 VIX>25에 현금) — 2021/2023 변동성 구간에서 과민?
  - `vix_level_tier1_cash_floor=0.10` 등 VIX guard floor가 불장에도 현금 유지
  - sleeve sizing / `growth_reentry_strength=0.38` (재진입 강도 약함 → 현금에 오래 머묾)
- **→ C1 cash-trap attribution이 어느 knob이 bull-drag를 만드는지 먼저 특정해야 B 변형이 정확.**

### A/B 변형 (C1 결과로 확정)
| ID | 변경 knob (후보) | 가설 |
|---|---|---|
| **B1** | `R1000_CONC_REGIME_CASH_VIX_THRESHOLD` 25→30 | Conc 현금 트리거 완화 → 불장 노출↑ → IS CAGR↑ |
| **B2** | `R1000_GROWTH_REENTRY_STRENGTH` 0.38→0.55 | 급락 후 재진입 가속 → 현금 잔류 시간↓ |
| **B3** | `R1000_VIX_TIER1_CASH_FLOOR` 0.10→0.05 (불장 한정) | green regime에서만 VIX floor 완화 |

대부분 cash-overlay → QUICK/Tier-2 가능.

### Family B gate (표준 강화 gate)
- **ΔCAGR ≥ +0.5pp AND ΔSharpe ≥ −0.05 AND ΔMaxDD ≥ −1.0pp**(이미 −26%라 더 악화 금지)
- 추가: **IS CAGR 단조 ↑ AND OOS/IS 비율 ↓** (robustness)
- 회귀가드: **2020·2022 MDD 불변**(crisis cash 보존 증거). early_scout ≥ 4.

---

## 4. 실험 매트릭스 & 프로토콜

1. **선행**: C1 cash-trap attribution (crisis cash vs bull-drag cash 분해, `is_attribution`/`cash_reentry_quality`/`mdd_cash_overlay_research` 입력) → Family B knob 확정 + 각 lever env-hook 추가.
2. **baseline 고정**: run #214(master clean 7Y + R1). `run_local.py CURRENT_BASELINE`에 clean7y 수치 등록.
3. **격리**: 한 번에 한 lever. 순서 **A1 → A2 → (필요시 A3) → [C1] → B1 → B2 → B3**. MDD 돌파가 시급 → **Family A 우선**.
4. **모드**: cash-overlay(A1/A2/B*) = QUICK/Tier-2 replay (feature_store 불변). 신규 피처(A3) = FULL.
5. **주입**: challenger run에 `experiment_env_json={"R1000_...":"..."}`. production target/cash는 불변(challenger 산출물로만 측정).
6. **비교**: 각 run `account_evaluation/official_metrics.json` diff → CAGR/MDD/Sharpe/IS/OOS-IS + 연도별(2020 COVID-DD, 2022-DD, 2021/2023 현금).
7. **보고**: lever별 (ΔCAGR, ΔMDD, ΔSharpe, ΔIS, ΔOOS/IS, 2020DD, 2022DD) 표. ship 판정은 user.

---

## 5. Overfit 가드 (7Y 단일창 튜닝의 핵심 리스크)
- **OOS/IS를 가드로**: 어떤 변형도 OOS/IS 비율을 악화시키면 reject (단일창 fit 신호).
- **연도별 회귀가드**: 2022 방어·2020 crisis cash가 약해지는 변형 reject.
- **walk-forward 무결성**: cash-overlay는 per-date 적용이므로 look-ahead 없음 — 단 신규 피처(A3)는 PIT(merge_asof backward) 유지.
- **lever 수 제한**: 한 번에 하나, 누적 변경 ≤ 3개. grid search 금지.
- **10Y 백신**: 근본 overfit 방어는 B1 membership PIT(별도 트랙)로 IS 표본을 늘리는 것 — A/B와 병행.

---

## 6. 검증 명령
```bash
py -3 tests/smoke_test.py
python tools/run_pr_validation.py            # cash_contract / regime_capacity_filter / macro_circuit_breaker / drawdown breaker smokes 포함
py -3 run_local.py --verdict-only            # baseline
# QUICK A/B: phase_ab_quick_rescore_manual.yml  또는  py -3 run_local.py (env override)
# FULL (A3): full_rebuild_manual.yml -f experiment_env_json='{"PHASE_FASTCRASH_ENABLED":"1"}' -f skip_collector=true
```
관련 기존 smoke(회귀 안전망): `crisis_state_engine_smoke`, `regime_capacity_filter_smoke`, `macro_circuit_breaker_filter_smoke`, `daily_crisis_monitor_long_crisis_smoke`, `bull_floor_overlay_smoke`, `cash_contract_smoke`.

---

## 7. Scope / 금지
- 측정/challenger 전용. production target/cash/scoring mutation·promotion·live는 user 승인 전 금지.
- env-hook 추가는 측정 인프라(기본값 불변) — 정책 변경 아님.
- 보류: bull-floor promote, T3/recovery A/B, 8Y/10Y(membership PIT 전), "목표 달성" 판정.
- 각 lever = 단일 PR. challenger 경로. CHANGELOG 영어 + KST.

---

## 8. 순서 (한 줄)
**run #214 baseline 확정 → C1 cash-trap attribution → Family A(A1·A2 fast-crash, MDD −26%→−25% 이내) → Family B(B1·B2·B3 bull-cash 축소, IS CAGR↑·OOS/IS↓) → 매 단계 challenger 측정·user 승인.** 병행: B1 membership PIT(10Y 해금 + overfit 백신).
