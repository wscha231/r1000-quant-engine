# Codex A/B 실행 계획 — Clean 7Y CAGR/MDD 강화

- 작성일: 2026-06-20 KST
- 작성 주체: Claude
- 근거 run: Full Rebuild #213 `27861341084` (conclusion=success), 결과 commit `e092513`, 브랜치 `codex/clean7y-evaluation-window-20260620`
- 모든 baseline 수치는 `cloud_results/full_rebuild/latest_global_alpha_universe/account_evaluation/official_metrics.json` + `broker_replay/*/equity_curve.csv`를 직접 읽어 검증한 값.
- 이 문서는 측정/challenger 전용 A/B 계획이다. **production target/cash/scoring mutation, promotion, live trading은 user 승인 전까지 금지.**

---

## 0. 목적

Clean 7Y(2019-07 시작, COVID 포함) 정직 baseline에서 acceptance 타깃(Main CAGR≥35%/MDD≥−25%, Conc CAGR≥50%/MDD≥−25%)을 **미달**한다. 이 문서는 두 결함축을 A/B로 측정해 강화 근거를 만든다. **이 단계는 evidence 생성까지만**; ship/promote는 별도 user 결정.

---

## 1. 확정된 Clean 7Y Baseline (run #213)

window: **2019-07-01 → 2026-06-18**, 6.965년, Main 1752 / Conc 1733 거래일. COVID 크래시(2020-02/03) 포함.

| 지표 | Main | Concentrated |
|---|---:|---:|
| CAGR | **34.53%** | **45.49%** |
| MaxDD | **−26.06%** | **−24.57%** |
| Sharpe | 1.261 | 1.413 |
| IS CAGR | 20.37% | 18.87% |
| OOS CAGR | 79.73% | 144.51% |
| OOS/IS | **3.91x** | **7.66x** |
| avg cash | 26.42% | 41.94% |
| latest cash | 14.77% | 5.78% |
| positions | 13 | 5 |
| gate | invalid_window(6.965y<7.0) | invalid_window |
| pit_universe_label_clean | False | False |
| valid_for_production | False | False |

타깃 대비: Main CAGR 34.53% < 35% ❌, MDD −26.06% > −25% ❌(돌파) / Conc CAGR 45.49% < 50% ❌, MDD −24.57% ✅.

직전(2020-05 시작) 대비: CAGR −5pp, MDD 악화. 직전 헤드라인은 COVID·유리한 시작점 제외로 부풀려진 값이었음.

---

## 2. 진단 — 2개 결함축 (연도별 증거)

연도별 broker-ledger (run #213 equity curve 직접 계산):

| 연도 | Main 수익 | Main MDD | Main 현금 | Conc 수익 | Conc 현금 | 해석 |
|---|---:|---:|---:|---:|---:|---|
| 2019(H2) | +11.3% | −6.8% | 12% | +2.6% | 29% | |
| 2020 | +64.1% | **−26.1%** | 24% | +88.1% | 38% | **COVID 급락 방어 실패 (=Main MDD)** |
| 2021 | +8.5% | −19.0% | 11% | +2.4% | 36% | **불장 과방어(Conc 36% 현금) → IS CAGR drag** |
| 2022 | −9.5% | −11.8% | 65% | −10.7% | 81% | **느린 약세장 방어 성공** |
| 2023 | +13.5% | −15.4% | 29% | +11.9% | 52% | **불장 과방어(Conc 52%) → drag** |
| 2024 | +47.2% | −13.6% | 15% | +58.7% | 26% | |
| 2025 | +41.0% | −24.3% | 24% | +95.9% | 32% | |
| 2026(H1) | +84.6% | −12.8% | 22% | +116.1% | 32% | |

**결함축 A — 빠른 크래시 방어 실패 (MDD 돌파 원인).**
2020 COVID 2-3주 급락에서 Main −26.1%, 현금은 24%뿐. 반면 2022 느린 약세장은 현금 65~81%로 −9.5% 방어. 즉 위기 현금 오버레이가 **slow-crisis는 잡지만 fast-crash는 못 잡음.** 이것이 Main −25% 돌파의 직접 원인.

**결함축 B — green/bull cash drag (CAGR 미달 + OOS/IS 과대 원인).**
2021·2023 불장에서 과도한 현금(특히 Conc 36%/52%)이 IS bull-year 수익을 눌러 IS CAGR을 20%/19%로 떨어뜨림 → OOS/IS 3.91x/7.66x. `is_attribution`가 이미 Conc 2021·2023을 `structural_underinvestment_bull`로 태깅.

---

## 3. 선행 필수 — C1 Cash-Trap Attribution (A/B 전에)

A/B는 진단 위에서만 유효하다. 먼저 현금을 2버킷으로 분해:
- **crisis-defense cash** (MDD를 줄인 현금: 2020·2022) → 보존 대상
- **green/bull cash** (CAGR만 깎고 DD 개선 없는 현금: 2021·2023) → 축소 대상

입력: `cash_reentry_quality/`, `is_attribution/`, `mdd_cash_overlay_research/`, `trade_attribution/`.
산출: 연도×regime별 (현금 pp, CAGR 손실 pp, MDD 개선 pp) 표 → Family A/B의 변수 범위 결정.
이건 측정 전용(ship gate 무관). 단일 PR.

---

## 4. A/B Family A — Fast-Crash Defense (MDD lever)

**가설**: 급락 속도(drawdown velocity)/VIX 스파이크/breadth collapse에 반응하는 빠른 현금 차단기를 추가하면 COVID형 −26% DD를 −25% 이내로 줄이되, 느린 약세장(2022)·불장 성과는 건드리지 않는다.

**변수 (한 번에 하나)**:
- A1 (QUICK 가능): 기존 `regime_capacity_cash_target` / `crisis_lane_weight_multiplier` / `daily_crisis_state` 임계를 **fast-trigger 방향으로** 튜닝 (단기 변동성·dd-velocity 민감도 ↑). 시그널 공식 불변 → QUICK rescore.
- A2 (FULL 필요): 신규 **fast-crash 피처** 추가 (예: 5/10일 dd-velocity, VIX 1일 급등, breadth 붕괴). 신규 시그널 공식 → `PHASE<N>_FASTCRASH_COLUMNS` 상수 + `build_feature_store.keep_cols` + `hard_sanitize` + phase toggle zero-placeholder 동기화 (CLAUDE.md 규칙). FULL rebuild 1회.

**측정 (challenger 경로)**:
- 비교: A OFF(baseline) vs A ON. 핵심 산출 `broker_replay/*/metrics.json`의 `max_dd`, COVID 구간(2020-02-15~04-15) DD, 그리고 2022 DD·불장 CAGR.

**Family A gate (MDD-repair 전용, 표준 gate와 다름 — user 승인 필요)**:
- 1차: **Main MDD ≥ −25%** 달성 (현재 −26.06% → ≥ −25%, 즉 ΔMDD ≥ +1.1pp)
- 2차: **ΔCAGR ≥ −1.0pp** (MDD 수리를 위한 소폭 CAGR 희생 허용) **AND ΔSharpe ≥ −0.05**
- 회귀 가드: 2022 약세장 방어 불변(2022 DD 악화 ≤ +1pp), early_scout ≥ 4

> ⚠️ 표준 ship gate(ΔCAGR ≥ +0.5pp)와 다름. MDD 컴플라이언스가 목적이므로 별도 gate. **반드시 user 승인 후 적용.**

---

## 5. A/B Family B — Green/Bull Cash Drag 축소 (CAGR + OOS/IS lever)

**가설**: 확인된 bull/green regime(2021·2023형)에서만 현금을 줄이면 IS CAGR이 오르고 OOS/IS 비율이 정상화된다 — crisis cash는 유지하므로 MDD는 보호된다(dual-objective).

**변수 (한 번에 하나)**:
- B1 (QUICK): `regime_capacity` 오버레이의 **bull regime 현금 target 하향** (green/bull에서만). C1이 정량화한 green-cash pp만큼. sleeve 가중/phase toggle 튜닝이므로 QUICK.
- B2 (QUICK): bull regime에서 leader 신규진입 cap 완화 (현재 `*_new_entry_cap` 계열). cash 거절(`stock_selection_quality` rejection `cash` 1286건) 감소 측정.

> ⚠️ 이건 cash 정책 변경이므로 **challenger 경로에서 측정만**. user가 명시 금지한 **bull-floor promote 와는 다름**(승격 아님, 측정임). production 반영은 user 승인 후.

**측정**: B OFF vs B ON. 산출: CAGR, IS_CAGR(↑ 기대), OOS/IS(↓ 기대), 그리고 **2020·2022 MDD 불변 확인**(crisis cash 보존 증거).

**Family B gate (표준 강화 gate)**:
- **ΔCAGR ≥ +0.5pp AND ΔSharpe ≥ −0.05 AND ΔMaxDD ≥ −1.0pp** (MDD를 더 악화시키면 안 됨 — 현재 이미 −26%)
- 추가: **IS CAGR 단조 ↑ AND OOS/IS 비율 ↓** (robustness)
- early_scout ≥ 4

---

## 6. A/B 실행 프로토콜

1. **선행**: §3 C1 attribution 완료 (변수 범위 확보).
2. **격리**: 한 번에 한 레버만. A1 → A2 → B1 → B2 순. 동시 변경 금지.
3. **모드**: 시그널 공식 불변(A1/B1/B2)이면 QUICK rescore(`run_local.py` / `phase_ab_quick_rescore_manual.yml`). 신규 피처(A2)면 FULL rebuild.
4. **baseline 고정**: 이 clean 7Y(run #213, commit `e092513`)를 A/B baseline으로. `run_local.py CURRENT_BASELINE`에 clean7y 수치 추가(측정용).
5. **비교 산출**: 각 run의 `account_evaluation/official_metrics.json` diff → CAGR/MDD/Sharpe/IS/OOS/avg_cash.
6. **challenger-only**: 모든 변형은 `era_aware_scoring_challenger` / `auto_policy_challenger` 경로로. `production_mutation_allowed=false` 유지. promote 금지.
7. **보고**: 각 레버의 (ΔCAGR, ΔMDD, ΔSharpe, ΔIS, ΔOOS/IS, COVID-DD, 2022-DD) 표. ship 판정은 user.

---

## 7. 강화 성공 정의 (production 승격 조건 — 별도 user 결정)

- window: clean 7Y `valid=true` (현재 6.965y로 미세 미달 → eval_start 2주 보정 또는 시간 경과로 충족) **AND** `pit_universe_label_clean=true` (멤버십 PIT 복원, 별도 B1 작업).
- tier2 전 항목 pass: `oos_is_cagr_ratio_max`(≤3.0), `is_cagr_min`(Main≥0.25, Conc≥0.30).
- **Main CAGR ≥ 35% AND MDD ≥ −25%**; **Conc CAGR ≥ 50% AND MDD ≥ −25%**.
- `system_acceptance_audit.hard_blocker_count = 0`.

> 현재 baseline은 위 전부 미달. A/B는 이 격차를 좁히는 evidence 생성 단계.

---

## 8. 측정 명령어

```bash
py -3 tests/smoke_test.py
python tools/run_pr_validation.py
py -3 run_local.py --verdict-only          # baseline verdict
py -3 run_local.py --phase<lever>=0        # A/B OFF
py -3 run_local.py --phase<lever>=1        # A/B ON
# QUICK A/B (Colab): phase_ab_quick_rescore_manual.yml
# FULL (A2 신규피처): full_rebuild_manual.yml (universe=global_alpha_universe, years=7, skip_collector=false)
```

---

## 9. 금지사항 (전 단계 공통)
- production target/cash/scoring mutation, promotion, live trading → **user 승인 전 금지**.
- user 명시 보류: **T3/recovery A/B, bull-floor promote, "목표 달성" 판정, 8Y/10Y/proxy**.
- Family B는 bull-floor promote 가 **아님**(측정 전용). 혼동 금지.
- 신규 피처 추가 시 PIT(merge_asof backward) 유지 + keep_cols/hard_sanitize/phase-zero 동기화.
- 각 레버 = 단일 PR. challenger 경로. CHANGELOG 영어 + KST 타임스탬프.

---

## 10. 우선순위 (한 줄)
**C1 cash-trap attribution → A1(fast-crash QUICK 튜닝) → [필요시 A2 FULL 신규피처] → B1(bull-cash 축소) → B2(bull leader cap 완화).**
MDD 돌파(−26.06%)가 가장 시급하므로 **Family A(MDD) 우선**, 이어 Family B(CAGR/OOS-IS). 멤버십 PIT(B1, 별도)는 promotion 전 필수. 모든 ship은 user 승인.
