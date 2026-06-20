# Codex 지시문 — PR #149 PASS_WITH_FIXES 후속 구현

- 작성일: 2026-06-20 KST
- 작성 주체: Claude (PR #149 리뷰어)
- 대상 PR: #149 `codex/clean7y-evaluation-window-20260620` (head `6cc6cd3a`, base = PR #146 브랜치, stacked)
- Verdict: **PASS_WITH_FIXES**
- 모든 파일:라인 참조는 clean7y 브랜치(`6cc6cd3a`) 기준.

---

## 0. 핸드오프 요약

PR #149는 **구조적으로 올바르고 실증 검증까지 끝났다.** 이 브랜치 코드로 full rebuild **run #213 (`27861341084`, success)** 를 돌린 결과:
- broker window **2020-05-01 → 2019-07-01** 이동 (직전 6.13y → 6.965y)
- **COVID 크래시(2020-02/03) 포함** — Main MaxDD **−26.06%** 가 곧 COVID 구간 DD
- 정직 baseline: Main 34.53% / −26.06%, Conc 45.49% / −24.57% (둘 다 타깃 미달, OOS/IS 3.91x/7.66x)

즉 fix는 작동한다. 다만 "clean 7Y"가 **데이터 우연**(rebuild가 2019 행을 만들어줬기 때문)으로 성립한 것이라, **강제 불변식**으로 못 박는 가드가 빠져 있다. 아래 R1이 그것이며 **머지 전 필수**. R2~R4는 권장.

---

## 1. R1 (REQUIRED) — broker 시작일 drift 가드

### 문제
`evaluation_start_date`는 `train_walkforward`의 `monthly_test_dates` 한 곳에만 wiring돼 있다 (`r1000_pipeline.py:9833`). broker replay / target book / `run_account_evaluation.py` window gate는 이 값을 **읽지 않고** equity_curve 시작일에만 의존한다. → 미래 rebuild가 2019 데이터 없는 캐시(예: `skip_collector=true` + 2020-start 캐시)를 쓰면 broker가 또 2020-05에서 시작해도 **에러 없이 통과**한다. clean 7Y 보장이 깨진다.

### 구현 위치
`tools/run_account_evaluation.py`

관련 기존 코드:
- `evaluate_window_gate(broker_metrics, equity_window, data_readiness, require_data_readiness)` — line 281
- `start_date = broker_metrics.get("start_date")` — line 294
- `reasons.append(...)` 패턴 — line 304~325
- gate dict 반환 (min_years/official_backtest_window_years 등 필드) — line 332~347
- 호출부: `equity_window=equity_curve_window(... "equity_curve.csv")` — line 370
- `official_metrics` write — line 663~675
- 상수: `MIN_BROKER_LEDGER_YEARS` (line 55), `OFFICIAL_WINDOW_TOLERANCE_YEARS`

`evaluation_start_date` 소스: run manifest. `r1000_pipeline.py:18814`에서 export_outputs가 manifest dict에 `"evaluation_start_date"`를 쓰고, manifest 경로는 `result_outputs["run_manifest"]`(line 18829). `run_account_evaluation.py`의 `--latest-run outputs`에서 manifest 파일을 찾아 읽으면 된다. (manifest 미존재/필드 빈 값이면 가드 skip — 하위호환.)

### 구현 스펙
1. 상수 추가:
   ```python
   BROKER_START_DRIFT_TOLERANCE_DAYS = 35  # one monthly rebalance + next-close fill lag
   ```
2. `evaluate_window_gate`에 `evaluation_start_date: Any = None` 파라미터 추가.
3. 로직 (start_date·evaluation_start_date 둘 다 파싱 가능할 때만):
   ```python
   broker_start = parse_date(start_date)
   eval_start = parse_date(evaluation_start_date) if evaluation_start_date else None
   broker_start_drift_days = None
   if broker_start is not None and eval_start is not None:
       broker_start_drift_days = int((broker_start - eval_start).days)
       if broker_start_drift_days > BROKER_START_DRIFT_TOLERANCE_DAYS:
           reasons.append("broker_start_later_than_evaluation_start")
   ```
4. gate dict에 필드 추가: `evaluation_start_date`, `broker_start_drift_days`, `broker_start_drift_tolerance_days`. `valid`는 기존처럼 `len(reasons)==0` (새 reason이 붙으면 자동 False).
5. 호출부에서 manifest의 `evaluation_start_date`를 읽어 전달. (per-portfolio 호출 line 370 근처)
6. `official_metrics.json`에도 위 3개 필드가 들어가도록 전파(이미 gate dict가 official로 직렬화되면 자동).

### 수용 기준
- eval_start=2019-06-17, broker_start=2020-05-01 → drift≈318d > 35 → `broker_start_later_than_evaluation_start` reason + `valid=False`.
- eval_start=2019-06-17, broker_start=2019-07-01 (run #213 실제값) → drift=14d ≤ 35 → 새 reason 없음 (이 가드만으로는 valid에 영향 없음).
- evaluation_start_date 없음(과거 run) → 가드 skip, 기존 동작 유지.

### 테스트
`tests/account_evaluation_window_gate_smoke.py`에 케이스 2개 추가:
- `test_window_gate_flags_broker_start_drift()` — broker 2020-05-01 / eval 2019-06-17 → reason 존재 + valid False.
- `test_window_gate_passes_when_broker_start_near_eval_start()` — broker 2019-07-01 / eval 2019-06-17 → reason 없음.
(이 테스트는 이미 `run_pr_validation.py` DEFAULT_TESTS line 116에 포함됨 → CI 자동 검증.)

---

## 2. R2 (RECOMMENDED) — 7Y 경계 미달 처리

run #213은 6.965년 / 1752 거래일로 7.0년(1764일)에 ~2주 미달 → 여전히 `invalid_window`. 원인: eval_start=2019-06-17이지만 첫 월말 test date 다음 next-close fill이 2019-07-01이라 시작이 늦음.

선택지 (택1):
- **(권장) research_7y 라벨 수용**: promotion은 어차피 `pit_universe_label_clean=false`로 차단되므로 research 용도엔 무방. `account_evaluation` 리포트에 "6.97y observed, marginally below 7.0y due to month-boundary fill; research_7y" 문구만 명시.
- (대안) `configure_last_n_years_backtest`에서 eval_start를 첫 test 월이 ≤2019-06 경계에 들어오도록 소폭 앞당김(예: `years` 버퍼 +0.05). 단 "정확히 end−7Y" 의미가 흐려지므로 비권장.

이건 코드 필수 아님. 문서/라벨 처리로 충분.

---

## 3. R3 (RECOMMENDED) — evaluation_start_date 산출물 노출

추적성을 위해 `evaluation_start_date`를 다음에 명시:
- `broker_replay/*/metrics.json` (broker replay writer)
- `account_evaluation/official_metrics.json` (R1에서 gate 경유로 들어가면 자동 충족)

현재 OOS 리포트(`r1000_pipeline.py:18380`)와 manifest(`:18814`)엔 이미 있음. broker metrics.json엔 없음 → 추가 시 broker start와 eval start를 한 산출물에서 대조 가능.

---

## 4. R4 (RECOMMENDED) — cagr_walkforward COVID-coverage persist 확인

PR #146이 `outputs/cagr_walkforward/`를 아티팩트 업로드 목록에 추가했으나, run #213의 cloud_results 커밋엔 해당 dir이 없었다(검증 불가). 확인할 것:
- full_rebuild 후 `cloud_results/.../cagr_walkforward/report.md`에 COVID-coverage 플래그가 **"covered"** 로 뒤집혔는지 (window가 2019-07이고 2020-02-19~03-23을 span하므로 covered여야 함).
- 안 들어가면 `tools/run_full_rebuild_sidecars.py` / cloud_results copy 단계에 `cagr_walkforward/` 추가.

---

## 5. Merge 순서 & 다음 단계

확정: **PR146 → PR149 → PR148**.
- PR149는 R1 추가 후 merge 권장. (R1 없이 merge해도 동작은 하나, clean 7Y가 데이터 우연에 의존 → 회귀 리스크.)
- PR148(B2 alpha/beta attribution)은 PR149 merge 후 clean window 위에서.
- 이후 실제 CAGR/MDD 강화는 별도 A/B 계획서(`docs/CODEX_AB_PLAN_CAGR_MDD_CLEAN7Y_20260620.md`) 따름: C1 cash-trap attribution → Family A(fast-crash defense, MDD) → Family B(green/bull cash 축소, CAGR/OOS-IS).

---

## 6. Scope 제약 / 금지 (R1~R4 공통)
- 이 작업은 **evaluation-window 검증/가드 + 리포팅 plumbing 전용**.
- 금지: selection/scoring/target-book/cash policy/production gate **의미** 변경. (R1은 gate에 "broker가 eval보다 늦게 시작" 검증을 **추가**할 뿐, 기존 통과 기준을 완화/강화하지 않음 — drift 없으면 기존과 동일.)
- 금지(user 보류): T3/recovery A/B, bull-floor promote, live trading, 8Y/10Y/proxy, "목표 달성" 판정, workflow dispatch(자동).
- 미래누수 방지 패턴 유지. 새 필드 추가 시 직렬화/테스트 동기화.

---

## 7. 검증 명령
```bash
py -3 tests/smoke_test.py
python tools/run_pr_validation.py            # seven_year_lock_smoke + account_evaluation_window_gate_smoke 포함
python tests/account_evaluation_window_gate_smoke.py
python tests/seven_year_lock_smoke.py
```
R1 머지 후 다음 full rebuild에서 확인:
- `official_metrics.json`에 `broker_start_drift_days` ≈ 14 (정상), reason에 `broker_start_later_than_evaluation_start` 없음.
- broker equity_curve 시작 ≈ 2019-07, COVID 포함.

---

## 8. 단일 PR 체크리스트
- [ ] R1 구현 (가드 + 필드 + 테스트 2개)
- [ ] `py -3 tests/smoke_test.py` 통과
- [ ] `python tools/run_pr_validation.py` 통과 (account_evaluation_window_gate_smoke 신규 케이스 포함)
- [ ] PR 설명에 scope 명시 (window 검증 가드 추가, 통과 기준 완화 없음)
- [ ] CHANGELOG 영어 + `HH:MM KST` + symbols_added(`BROKER_START_DRIFT_TOLERANCE_DAYS`, 수정 함수 `evaluate_window_gate`) / config_fields_added(none) / breaking_changes(none)
- [ ] R1은 PR149에 직접 추가하거나 별도 stacked PR; merge 순서 PR146→PR149(+R1)→PR148 유지
- [ ] draft PR, 자동 머지 금지

---

## 9. 한 줄 지시
**PR149에 R1(broker 시작일 drift 가드 + 테스트 2개)를 추가해 clean 7Y를 강제 불변식으로 못 박은 뒤 merge. R2는 라벨/문서, R3·R4는 추적성 보강. 그 후 PR148 → A/B 계획서 순으로 진행. production mutation/promotion은 user 승인 전 금지.**
