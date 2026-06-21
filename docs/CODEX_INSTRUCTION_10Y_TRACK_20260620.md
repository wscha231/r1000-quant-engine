# Codex 지시문 — 10Y 트랙 (현재 → 10Y A/B)

- 작성일: 2026-06-20 KST
- 작성 주체: Claude
- 성격: 측정/challenger 전용. **production target/cash/scoring mutation, promotion, live 금지.** 모든 >7Y 산출물은 `proxy` 라벨 강제.
- 모든 파일경로/메커니즘은 코드 직접 확인(3-way Explore). 추측 금지.
- 병행 트랙: 7Y Family A (A1 run #216 `27887125658` / A2 run #217 `27887129839`)는 이미 진행 중 — 이 문서와 독립.

---

## 0. 왜 10Y인가 + 2-tier 프레이밍

run #214 정직 baseline의 최대 구조적 약점은 **overfit**: Concentrated **OOS/IS CAGR ratio = 7.66x** (tier-2 gate ≤ 3.0), IS CAGR 18.85%. 근본 백신은 **IS 윈도우를 늘리는 것**(10Y) — IS에 더 많은 레짐이 들어가면 OOS/IS가 내려가고, Family A/B fast-crash·bull-cash 수정이 7Y 밖에서도 일반화되는지 검증된다.

**그러나 free-tier로 "10Y를 지금과 똑같이"는 불가능.** 두 tier로 분리한다:

- **Tier-A proxy-10Y (지금 free로 가능)** — robustness/overfit 스트레스 테스트. **`proxy` 라벨, official 수용 근거 아님.**
- **Tier-B official-10Y (블록)** — 유료 PIT 멤버십(CRSP/Russell) + 폐지종목 가격 필요. **범위 외.**

이 문서는 Tier-A를 현재 상태에서 10Y A/B까지 끌고 가는 우선순위 지시문이다.

---

## 1. 스트림별 정직한 갭 테이블 (Explore 검증)

| stream | 10Y 획득? | PIT? | floor / gap | 근거 |
|---|---|---|---|---|
| Prices (yfinance) | ✅ | EOD | 생존편향: 폐지종목 부재 | `tools/build_replay_price_cache.py` |
| Macro/FRED/VIX | ✅ | release-lag | 1990+ | macro loader |
| Form4 (EDGAR) | ✅ | accepted_ts | 1995+ | `run_sec_form4_parser` |
| Target books / broker replay | ✅ (재실행) | n/a | 윈도우 연장만 | `full_rebuild_manual.yml` |
| 13F (EDGAR) | ⚠️ 부분 | accepted_ts | CUSIP→ticker 빌드 필요 (현재 로컬파일만) | `r1000_pipeline.py:3227` |
| **ETF N-PORT** | **❌ pre-2020** | accepted_ts | **하드 floor ~2020, 복구 불가** | `tools/build_etf_nport_history.py` |
| **R1000 멤버십 PIT** | **❌ (free)** | — | **official blocker** | `r1000_config.py:523-531` |
| ADR 적격성 | static만 | 비-PIT | 소급적용 편향 | `load_adr_universe_frame` |

엔진은 sparse-early-data를 안전 처리: 없는 증거 = 중립(0, 페널티 없음), PIT 강제(`tools/audit_data_readiness.py:370-420` `pit_available_from_check`, future available_from > 0 → hard FAIL), 커버리지 게이트가 dead feed를 WARN/FAIL로 전환(`tools/data_coverage_gate.py`).

**결론: proxy-10Y는 돌아가지만 2016~2020 초기 4년은 ETF 0% + 13F 약함 + proxy 멤버십. official이 아니라 overfit 백신으로만 쓴다.**

---

## 2. 우선순위 작업 (P0 → P6, 각 1 PR)

### P0 — tier 결정 + proxy 라벨 락
- `pit_universe_label_clean=false` 유지. 모든 >7Y 산출물 `proxy` 스탬프.
- 근거: `r1000_config.py:523-531` (`PROXY_8Y_10Y_EVIDENCE_BLOCKED=True`, `PROXY_WINDOW_BLOCKER_REASON="pit_universe_label_missing"`), 워크플로 게이트 `full_rebuild_manual.yml:439-456` (years>7.05 AND not pit_clean → exit 2).
- **이 라벨을 우회하거나 official로 승격하지 말 것.**

### P1 — 과거 R1000 멤버십 PIT proxy 파일 (#1 blocker)
- 엔진이 **이미 소비하는** 파일을 만든다 — 새 코드 경로 발명 금지.
  - 읽기: `load_historical_universe_membership` (`r1000_pipeline.py:2870`)
  - 필터: `apply_historical_membership_filter` (`r1000_pipeline.py:2921`) — `rebalance_date` 또는 `date_from`/`date_to` PIT 범위로 월별 행 필터
  - 스키마: `["ticker","Name","sector","cik10","rebalance_date"]` 또는 `["ticker",...,"date_from","date_to"]`
- 소스 우선순위:
  1. 시계열로 아카이브된 IWB(Russell 1000 ETF) 보유 스냅샷이 있으면 그걸로 date_from/date_to 재구성
  2. 다른 free constituent-history 소스
  3. fallback = 현재 IWB 1장 → **생존편향 그대로 → proxy 라벨 필수**
- **정직한 천장 명시**: free fallback이면 "현재 구성종목을 과거에 소급"이라 탈락 종목 누락. 이걸 doc에 적고 proxy 라벨로 둔다. 절대 official로 표기하지 말 것.

### P2 — 가격 캐시 ~2016-06 연장
- `tools/build_replay_price_cache.py`. manifest `end`는 **실제 캐시된 bar**에서 쓴다(provider 요청 bound 아님 — CLAUDE.md 데이터 계약).
- 폐지종목 생존편향 caveat를 manifest/doc에 기록.

### P3 — 윈도우 연장 풀리빌드
- `full_rebuild_manual.yml`: `backtest_years=10`, `pit_universe_label_clean=false`, `skip_collector=true`(캐시 재사용).
- `data_extension_plan.json`의 5개 윈도우 blocker 해소(price_cache, target_book×2, broker_replay×2). 6번째 `pit_universe_label`은 proxy로 수용.
- 산출: **proxy-10Y baseline** (Main/Conc broker-ledger metrics).

### P4 — 열화 초기증거 수용
- 2016~2020: ETF N-PORT 0% + 13F 약함. neutral-missing + 커버리지 게이트 WARN(FAIL 아님)에 의존.
- "degraded-evidence window 2016-2020"를 doc에 명시. 이 구간 alpha 기여를 과신하지 말 것.

### P5 — readiness 프리플라이트
- `py -3 tools/check_10y_backtest_readiness.py` 실행.
- 기대: hard blocker가 **`pit_universe_label` 하나로 축소**(proxy 수용), 5개 윈도우 blocker 모두 cleared.
- `py -3 tests/ten_year_backtest_readiness_smoke.py` 통과 확인.

### P6 — 10Y A/B (트랙의 종착)
- proxy-10Y baseline 위에서 **7Y와 동일한 Family A/B 레버**를 `R1000_` env-override로 재실행.
  - 메커니즘: `FAST_CRASH_ENV_OVERRIDE_FIELDS` 훅 (commit `70538b9`, `r1000_config.py` `_apply_fast_crash_env_overrides`). `experiment_env_json`로 주입, ref는 훅이 있는 브랜치.
  - 예: `{"R1000_DRAWDOWN_BREAKER_LEVEL_1_THRESHOLD":"0.08","R1000_DRAWDOWN_BREAKER_LEVEL_1_CASH_FLOOR":"0.25"}` (A1), `{"R1000_VIX_LEVEL_TIER1_CASH_FLOOR":"0.20","R1000_VIX_LEVEL_TIER2_CASH_FLOOR":"0.40"}` (A2).
- 목적: 7Y fast-crash/bull-cash 수정이 **일반화**되는가 + 긴 IS가 **OOS/IS를 낮추는가**.
- **Gate**: ΔCAGR ≥ +0.5pp AND ΔSharpe ≥ −0.05 AND ΔMaxDD ≥ −1.0pp **AND OOS/IS ratio가 7Y baseline(Conc 7.66x)보다 엄격히 낮을 것** (overfit 백신 성공 기준). early_scout ≥ 4.

---

## 3. 제약 (기존 Codex 문서 승계)
- 측정/challenger 전용. production target/cash/scoring mutation·promotion·live 금지.
- **모든 >7Y 산출물 `proxy` 라벨 강제.** official-10Y 승격 금지(유료 데이터 전).
- 기존 메커니즘 재사용 — 새 membership/PIT 코드 경로 발명 금지.
- CHANGELOG 영어 + `HH:MM KST`. 각 P 항목 = 단일 PR. challenger 경로.

---

## 4. Critical 파일 (참조)
- `r1000_config.py:523-531` — 윈도우 캡 상수 (`OFFICIAL_BACKTEST_WINDOW_YEARS=7.0`, `PROXY_8Y_10Y_EVIDENCE_BLOCKED`, `PROXY_WINDOW_BLOCKER_REASON`)
- `r1000_pipeline.py:2870, 2921` — 멤버십 load + PIT 필터 (이미 존재, P1이 공급)
- `tools/build_replay_price_cache.py` — P2
- `tools/check_10y_backtest_readiness.py` — P5 (window_slug/window_label로 8Y/10Y 공용)
- `tools/build_etf_nport_history.py` — N-PORT floor 근거
- `.github/workflows/full_rebuild_manual.yml:40-56, 439-456` — backtest_years/pit 게이트
- `tests/ten_year_backtest_readiness_smoke.py`, `tests/data_coverage_gate_smoke.py` — 회귀 가드

---

## 5. 검증
- P1-P5 후: `py -3 tools/check_10y_backtest_readiness.py` → 남은 hard blocker가 `pit_universe_label` 하나; `tests/ten_year_backtest_readiness_smoke.py` 통과; 커버리지 게이트가 2016-2020 ETF/13F에 WARN(FAIL 아님).
- P6 후: proxy-10Y A/B metrics에서 **OOS/IS가 7Y baseline 7.66x보다 낮음** = overfit 완화 신호.

---

## 6. 범위 외
official-10Y 수용, 유료 데이터 취득, ETF N-PORT pre-2020 백필(불가능), bull-floor promote, production mutation. 7Y Family A(A1/A2 #216/#217)는 별도 근거리 트랙.

---

## 7. 순서 (한 줄)
**proxy 라벨 락(P0) → 멤버십 PIT proxy 파일(P1, #1 blocker) → 가격캐시 연장(P2) → 윈도우 풀리빌드(P3) → 열화증거 수용(P4) → readiness 프리플라이트(P5) → 10Y A/B(P6, OOS/IS↓ 검증).** 매 단계 proxy 라벨 유지·user 승인.
