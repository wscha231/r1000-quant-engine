# Codex 작업 진행 계획서 — PR #146 리뷰 결론 + CAGR/MDD 강화 로드맵

- 작성일: 2026-06-20 KST
- 작성 주체: Claude (PR #146 독립 검증 리뷰어)
- 검토 대상 PR: https://github.com/wscha231/r1000-quant-engine/pull/146 (`codex/fullrun-measurement-artifacts-20260619`, head `63c5aaf1`)
- 검토 대상 full run: GitHub Actions `27814870719` (결과는 `cloud_results/full_rebuild/latest_global_alpha_universe/`에 커밋되어 있음, commit `ca211c1`)
- 이 문서의 모든 수치는 위 커밋된 산출물(`official_metrics.json`, `broker_replay/*/equity_curve.csv`, `alphaops_vnext/selected_latest.csv`, `is_attribution/`, `system_acceptance_audit/`, `cash_contract/`, `universe_health/`)을 **직접 읽어 검증한 값**만 사용함. 추정치 없음.

---

## 0. 이 문서의 사용법

- 이 문서는 Codex가 다음 작업을 **오류 없이 단일 PR 단위로** 이어가도록 만든 핸드오프 계획서다.
- 각 Phase는 **측정 우선(measurement-first)** 으로 설계됐다. 전략/스코어링/타깃북/현금정책/게이트/유니버스의 **production mutation은 명시적 user 승인 전까지 금지**다 (run 27814870719의 `production_mutation_allowed=false`, `system_acceptance_audit.live_trading_allowed=false` 준수).
- 작업 순서: **Phase A → B → C → D → E**. B(멤버십 PIT)가 가장 중요한 production blocker이므로 D(CAGR/MDD 강화 실험)보다 먼저다.
- 모든 ship 판정은 `CLAUDE.md`의 ship gate를 따른다: **ΔCAGR ≥ +0.5pp AND ΔSharpe ≥ −0.05 AND ΔMaxDD ≥ −3pp**, plus `early_scout ≥ 4`.

---

## 1. 검증 결론 요약

### 1.1 PR #146 자체 — 머지 가능 (측정/아티팩트 전용 확인됨)
- GitHub 권위 데이터: **6파일 / +228 / −62 / 2커밋**. 패킷 주장과 일치.
- 변경 파일 전부 측정/아티팩트 plumbing. selection/scoring/cash/target/gate/live 변경 없음.
- 유일한 뉘앙스: `tools/run_full_rebuild_sidecars.py`가 full-run 본 경로에서 `build_daily_market_snapshot`을 **새로 빌드**한다. "측정만 읽음"이 아니라 "아티팩트를 추가 생성"하는 것 — 전략 영향은 없으나 PR 설명에 이 한 줄을 명시할 것.
- `cagr-walkforward-v3` 스키마는 수학적으로 건전 (§2.2 참조).

### 1.2 헤드라인 지표 — 정확하지만 production-valid 아님

| 포트 | CAGR | MDD | Sharpe | 평균현금 | 최신현금 | IS CAGR | OOS CAGR | OOS/IS | tier2 실패 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Main | 39.56% | −24.46% | 1.389 | 26.51% | 15.54% | 25.36% | 76.43% | 3.01x | `oos_is_cagr_ratio_max` |
| Concentrated | 50.62% | −23.83% | 1.518 | 42.25% | 6.33% | 22.35% | 135.19% | 6.05x | `is_cagr_min`, `oos_is_cagr_ratio_max` |

- 위 값은 `cloud_results/full_rebuild/latest_global_alpha_universe/account_evaluation/official_metrics.json`과 100% 일치(직접 확인).
- 그러나 `valid_for_production=false`, `verdict_status=invalid_window`, `production_promotion_allowed=false`, `pit_universe_label_clean=false`.

---

## 2. 검증된 사실 (증거 경로 포함)

### 2.1 연도별 분해 (broker-ledger equity curve 직접 재계산)

`broker_replay/{main,concentrated}/equity_curve.csv` (`equity_usd` 컬럼)로 계산:

| 연도 | Main 수익 | Main 평균현금 | Conc 수익 | Conc 평균현금 |
|---|---:|---:|---:|---:|
| 2020(5월~) | +84.1% | 14% | +85.8% | 29% |
| 2021 | +8.6% | 10% | +3.1% | 37% |
| 2022 | −9.5% | 65% | −9.8% | 81% |
| 2023 | +15.9% | 29% | +11.9% | 52% |
| 2024 | +46.3% | 15% | +58.8% | 26% |
| 2025 | +42.7% | 24% | +95.9% | 32% |
| 2026(~6/17, 5.5개월) | +75.7% | 23% | +99.8% | 32% |
| 전체 배수 | 7.72x | | 12.31x | |

진단:
- CAGR이 **양 끝(2020 유리한 출발 + 2024~2026 반도체/AI 랠리)** 에 쏠림. 중간 2021~2023은 flat~+16%.
- 2026 연율화(245%/358%)는 5.5개월을 연율화한 허수 — v3가 reference-only로 격리한 것은 정당.

### 2.2 신뢰성 차단 사유 (시스템 자체 진단)
- `system_acceptance_audit/summary.json`: `hard_blocker_count=5`, `live_trading_allowed=false`.
- manual review task 2건 (main/concentrated): *"OOS CAGR is too high relative to locked IS CAGR; inspect whether the result is a narrow era/name lottery."*
- 윈도우: 6.1273년 (main 1540 / conc 1521 거래일) < 7년 요구(1764일).
- 데이터 누수 버그는 아님: `is_attribution/summary.json`의 `leak_year_tags` 대부분 `healthy` → 단일 leak 연도가 아니라 **진짜 regime 의존성**. 숫자는 "진짜"지만 robust하지 않음.
- `cagr-walkforward-v3` 수학 검증 통과:
  - full-year 평균(2020–2025) partial 제외 ✅
  - day-weighted(arithmetic+geometric) partial 포함 ✅
  - MDD는 path-based라 day-weight 평균 안 함, full/worst-full-year/partial-reference로 분리 ✅

### 2.3 종목 선별 / 리밸런싱 메커니즘 (`selected_latest.csv` 직접 확인)
- 현재 simulated holdings (상태 `DO_NOT_TRADE`):
  - Concentrated: SNDK 37.3%, BE 22.2%, WDC ~22%, CIEN 8%, LITE 5%, CASH 6% → 메모리/스토리지+연료전지+광통신 80%+
  - Main 13종목: SNDK·WDC·MRVL·STM·MU·ON·TER·KEYS·COHR·LITE·CIEN(반도체 클러스터) + PWR·FIX
- 선별 레인: 전부 `primary_lane=MARKET_LEADER`, `lane_reason=MARKET_LEADER_score_selected`, sleeve `future_winner`.
- **리밸런싱: 월간** (`active_rebalance_interval_months=1.0`, `decision_frequency=monthly_replay_plus_latest_close_hold_forward`).
- **교체 로직: sigma hysteresis** (`hold_replace_threshold_sigma≈0.76`, `hold_replace_broken_threshold_sigma≈0.35`), `hold_replace_decision`: keep_prior_holding ↔ new_entry.
- **하드 스탑: speculative −25%**.
- **실제 평균 보유: main 60일 / concentrated 54일** (`journal_avg_holding_days`), win_rate 55~58%, profit_factor ~4.2 → 부진 종목 약 1~2개월 내 교체.
- 핵심: SNDK는 2026-03-02 진입(`pit_evidence_blocked=False`) → 미래누수 아님. **의도된 주도주 집중이 맞음.** "lottery"는 운이 아니라 **robustness/regime 편중**의 문제로 재정의.
- 단, `is_attribution`이 concentrated **2021·2023을 `structural_underinvestment_bull`(불장 과방어)** 로 태깅 → 과거 부진은 종목발굴 실패가 아니라 **현금 과방어**가 원인.

### 2.4 Point-in-time 상태 (엔진 코드 직접 확인)

| 데이터 | PIT 여부 | 근거 |
|---|---|---|
| 가격 | ✅ | broker replay next_close, adjusted_close, replay_price_cache(실측 bar) |
| 재무제표 | ✅ | `r1000_features.py:797` `accepted = period + 45일` lag, `:1351` `merge_asof(left_on=rebalance_date, right_on=trend_accepted, direction="backward")`. 2020 재무 커버리지 69% |
| 매크로 | ✅ | `macro_slow_release_lag_months=1` |
| Form4 / 13F / ETF(N-PORT) | ✅ | `available_from` + as-of join (`run_sec_enriched_candidate_replay`, `sec_pit_available_from_smoke` 27 assertion). 현재 `sec_evidence_research_only=True`(단독 매수근거 차단) |
| **R1000 멤버십** | ❌ **PIT 아님** | `universe_health/universe_membership_by_month.csv`: `universe_source=current_constituents_proxy_static_seed`, `fallback_used=True`, **`pit_universe_label_clean=false`** |

→ **유일한 PIT 약점 = 유니버스 멤버십**. 2020 평가에 2020 당시 실제 R1000 명단이 아니라 오늘 명단을 정적 seed로 프록시 → survivorship/membership bias. 이것이 `proxy_8y_10y_evidence_blocked=true`의 직접 원인.

---

## 3. 진단: production-valid를 막는 3대 blocker

1. **B1 — 멤버십 PIT 미복원** (`pit_universe_label_clean=false`). 7Y CAGR을 "실력"으로 확정 불가.
2. **B2 — OOS/IS 비율 초과** (main 3.01x, conc 6.05x; 한도 3.0). + concentrated IS CAGR 22.3% < 30% 한도. = robustness 부족.
3. **B3 — 윈도우 6.13년 < 7년**. (단 8Y/10Y/proxy 작업은 user가 명시적으로 보류 → 본 계획은 7Y 경로만.)

부가 레버(버그 아님, 정책):
- **C — green/bull cash drag**. cash_contract drift는 0.1~0.2pp로 미미(버그 아님). 2021/2023 불장 과방어가 IS CAGR을 눌러 B2를 악화시킴 → CAGR 강화의 핵심 레버.

---

## 4. 작업 계획 (Phase별, 각 = 단일 PR)

### Phase A — PR #146 마감 (측정 전용)
- A1. PR #146 설명에 "`run_full_rebuild_sidecars.py`가 daily market snapshot을 신규 빌드한다"는 한 줄 추가.
- A2. `cagr-walkforward-v3` 그대로 머지 (수학 검증 통과).
- A3. user_current 파일명 계약 불일치(`08_broker_rule_backtest.json` 존재, `08_rebalance_decision.json`/`07_name_rationales.csv` 부재)는 **이 PR에 넣지 말고 defer** → Phase C2.
- 종료조건: PR #146 draft → ready, CI green, user 승인 후 머지(자동 머지 금지).

### Phase B — 멤버십 PIT 복원 (B1 해소, **최우선**, 측정 전용)
- B1-1. 2020-05 ~ 현재 **월별 실제 R1000(IWB) 멤버십 시계열** 확보. 후보 소스: IWB historical holdings, 또는 보유 중인 `data_static/iwb_holdings_seed.csv`(현재 정적)를 월별 시계열로 확장.
- B1-2. `candidate_replay_book.csv` 생성 단계에서 각 `rebalance_date`에 **그 시점 멤버십**만 후보 풀로 사용하도록 join(현재는 `current_constituents_proxy_static_seed`).
- B1-3. 측정 산출물: `universe_health/`에 `pit_universe_label_clean=true` 달성 여부 + 프록시 대비 후보 풀 차이(추가/삭제 종목 수) 리포트.
- B1-4. **재평가 영향 측정**: 멤버십 PIT 적용 전/후 broker-ledger CAGR/MDD/Sharpe/IS/OOS 비교(A/B). 이 차이가 곧 survivorship bias의 크기.
- 게이트: `pit_universe_label_clean=true` AND `account_evaluation` 재산출. (성과가 떨어져도 이것이 "진짜" baseline — 떨어지는 것을 실패로 보지 말 것.)
- 금지: 멤버십 복원 과정에서 selection/scoring 공식 변경 금지.

### Phase C — Cash-trap attribution + 선별근거 아티팩트 (측정 전용)
- C1. **Cash-trap attribution** (CAGR 강화의 진단 기반).
  - 입력: `cash_reentry_quality/`, `is_attribution/`(이미 2021/2023 `structural_underinvestment_bull` 태깅됨), `mdd_cash_overlay_research/`.
  - 산출: 현금을 2버킷으로 분해 — **(a) crisis-defense cash**(MDD를 줄인 현금, 2022) vs **(b) green/bull cash**(CAGR만 깎고 DD 개선 없는 현금, 2021/2023).
  - 각 버킷의 연도별 기여도(pp CAGR 손실, pp MDD 개선)를 표로. → Phase D 실험의 근거.
- C2. **`07_name_rationales.csv`** 아티팩트 추가. `selected_latest.csv`의 `primary_lane`/`lane_reason`/`selection_reason`/`holding_state_reason`/`hold_replace_decision`/주요 스코어 컬럼을 holding별로 1행 요약. user_current 파일명 계약도 이때 정리.
- 게이트: 측정 전용이므로 ship gate 무관. 스키마 smoke test 추가.

### Phase D — CAGR/MDD 강화 실험 (§5 상세, A/B 측정 → 승인 시에만 ship)
- C1의 진단을 바탕으로 green/bull cash만 축소하는 regime-capacity 오버레이 변형을 **A/B로 측정**.
- production mutation 전 반드시 user 승인. 측정 단계는 challenger 경로(`era_aware_scoring_challenger`/`auto_policy_challenger`)에서 수행.

### Phase E — 7Y 윈도우 확정 & 재평가 (B3, B-완료 후)
- B(멤버십 PIT) + D(강화) 적용된 상태에서 full rebuild 재실행.
- `account_evaluation_window_gate`가 `valid=true` 되는지 확인(윈도우는 시간이 지나며 자연 충족되거나, 시작점을 PIT-clean 상태로 앞당겨 확보).
- 8Y/10Y/proxy는 **이 계획 범위 밖**(user 보류).

---

## 5. CAGR/MDD 강화 상세

### 5.1 목표 (broker-ledger next-close 기준)
- 공식 acceptance: **Main CAGR ≥ 35% / MDD ≥ −25%**, **Concentrated CAGR ≥ 50% / MDD ≥ −25%**.
- 현재 헤드라인은 이미 충족(39.56%/−24.46%, 50.62%/−23.83%)하나, **production-valid가 아님**. 따라서 "강화"의 정의는 헤드라인 상향이 아니라:
  1. **production-valid화**: B1(멤버십 PIT) + B3(7Y) 충족.
  2. **robustness 상향**: OOS/IS 비율 ↓ (= IS CAGR ↑). 특히 concentrated IS CAGR 22.3% → ≥30%.
  3. **MDD 마진 확보**: 현재 −24.46%/−23.83% → −25% 한도까지 여유 0.5~1.2pp뿐. 마진을 넓힐 것.

### 5.2 레버 → 효과 매핑

| 레버 | 메커니즘 | CAGR 효과 | MDD 효과 | 출처 |
|---|---|---|---|---|
| green/bull cash 축소 | 2021/2023 불장 노출 ↑ → IS CAGR ↑ | **↑ (IS↑, OOS/IS↓)** | 중립~소폭 악화 | C1 attribution |
| crisis cash 유지 | 2022 방어 현금 보존 | 중립 | **보호(−25% 마진)** | mdd_cash_overlay_research |
| 멤버십 PIT 복원 | survivorship 제거 | ↓(정직화) 가능 | 변동 | B1 |
| position-level 스탑 강화 | speculative −25% 스탑 정밀화 | 소폭↓ | **↑** | hold_replace_broken_sigma |
| sigma 교체 임계 튜닝 | 부진 종목 회전 속도 | ± | ± | hold_replace_threshold_sigma |

**핵심 원리(dual objective)**: green/bull cash만 제거하면 CAGR↑ + OOS/IS↓(B2 해소)를 동시에, crisis cash는 유지해 MDD 마진을 지킨다. C1 attribution이 이 분리를 정량화해야 D 실험이 가능하다.

### 5.3 강화 실험 절차 (A/B, `CLAUDE.md` 레시피 준수)
1. baseline = B1(멤버십 PIT) 적용 후의 새 broker-ledger metrics. (B 완료 전엔 강화 실험 무의미 — 오염된 baseline 위에서 튜닝 금지.)
2. challenger = green/bull cash 축소 변형 1개씩만 (한 번에 한 레버).
3. QUICK rescore A/B → `outputs/account_evaluation/official_metrics.json` diff.
4. ship gate: **ΔCAGR ≥ +0.5pp AND ΔSharpe ≥ −0.05 AND ΔMaxDD ≥ −3pp AND MDD ≥ −25% AND early_scout ≥ 4**.
5. 추가 robustness gate: **OOS/IS 비율 ↓ (개선 방향) AND concentrated IS CAGR 단조 증가**.
6. 통과 시에도 **user 승인 전 production mutation 금지** — challenger 산출물로만 보고.

### 5.4 강화 성공 정의 (production 승격 조건)
- `valid_for_production=true` (윈도우 valid + `pit_universe_label_clean=true`).
- tier2 전 항목 pass: 특히 `oos_is_cagr_ratio_max`(≤3.0) AND `is_cagr_min`(main ≥0.25, conc ≥0.30).
- MDD ≤ −25% 한도 내 + 마진 ≥ 2pp 권장.
- `system_acceptance_audit.hard_blocker_count=0`.

---

## 6. 제약 / 금지사항 (전 Phase 공통)
- 8Y/10Y/proxy 작업, T3/recovery A/B, bull-floor promote, live trading, target/canonical mission 변경 **시작 금지** (user 보류).
- production mutation(`production_mutation_allowed`이 막는 모든 경로) 은 **명시적 user 승인 후에만**.
- `target_contract_status=unresolved_user_decision_required` 상태의 canonical vs interim 게이트 재정의 금지.
- 미래누수 방지: 모든 신규 join은 PIT(merge_asof backward) 패턴 유지. 새 피처 추가 시 `build_feature_store.keep_cols` + `hard_sanitize` + phase toggle zero-placeholder 동기화(`CLAUDE.md` 규칙).
- 각 Phase는 단일 PR. feature_store 스키마 변경 시 FULL rebuild 1회 필수.

---

## 7. 검증 명령어 / 게이트

```bash
# pre-commit (로컬 <10s)
py -3 tests/smoke_test.py

# 측정 검증
python tools/run_pr_validation.py
python tests/workflow_artifact_smoke.py
python tests/cagr_walkforward_smoke.py

# 결과 verdict (run 후)
py -3 run_local.py --verdict-only

# A/B 격리 (해당 phase toggle)
py -3 run_local.py --phase<key>=0   # OFF
py -3 run_local.py --phase<key>=1   # ON
```

Ship gate: **ΔCAGR ≥ +0.5pp AND ΔSharpe ≥ −0.05 AND ΔMaxDD ≥ −3pp**, plus **early_scout ≥ 4**.
강화 추가 gate: **OOS/IS 비율 개선 AND concentrated IS CAGR ↑ AND MDD ≥ −25%**.

---

## 8. 단일 PR 체크리스트 (각 Phase 공통)
- [ ] 측정 전용인가? production mutation 없으면 OK. 있으면 user 승인 있는가?
- [ ] `py -3 tests/smoke_test.py` 통과
- [ ] `python tools/run_pr_validation.py` 통과
- [ ] 새 산출물에 대한 smoke test 추가(같은 커밋)
- [ ] PR 설명에 scope 명시 (measurement-only 여부, 빌드 산출물 생성 여부)
- [ ] FULL rebuild 필요 변경이면 트리거 + verdict 절차 명시
- [ ] CHANGELOG 영어, `HH:MM KST` 타임스탬프, `symbols_added/changed`, `config_fields_added`, `breaking_changes` 포함
- [ ] draft PR 생성, 자동 머지 금지

---

## 9. 우선순위 한 줄 요약
**A(PR146 마감) → B(멤버십 PIT 복원, 최우선 blocker) → C1(cash-trap attribution) → D(green/bull cash 축소 A/B = CAGR/MDD 강화) → E(7Y 재평가).**
멤버십 PIT가 깨끗해지기 전에는 어떤 CAGR/MDD 수치도 production 근거로 쓰지 말 것.
