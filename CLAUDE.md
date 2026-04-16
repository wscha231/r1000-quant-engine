# r1000 Quant Engine - Project Guide

## Project Overview
Russell 1000 기반 Top 30 기관급 퀀트 종목 선정 엔진. S&P 500 초과수익 목표.

## Key Files
- `r1000_top30_institutional.py` — 메인 엔진 (~25,600+ lines)
- `r1000_data_collector.py` — 데이터 수집 + 검증 파이프라인
- `colab_run.ipynb` — Colab 실행 런북 (GitHub master pull → collector → pipeline → validation)
- `PHASE_ROADMAP.md` — **Phase 1..6 멀티-세션 작업 플랜 (새 대화 시작할 때 먼저 읽기)**
- `PROPOSAL_defensive_upgrades.md` — Phase 6 (tail protection) 상세 설계 문서
- `PROPOSAL_growth_regime_offense_defense.md` — Phase 4 참고용 아키텍처 문서

## Current Engine Version
- `ENGINE_REUSE_VERSION = "2026-04-16-phase2-keepcols-fix"`
- Cache invalidation: 버전 문자열이 바뀌면 `cache_*`/`feature_store` 아티팩트가 자동 재생성됨.
- **Next run must be FULL rebuild** (QUICK_RESCORE_ONLY=False) because this version bump forces regeneration of `feature_store_latest.parquet` with Phase 2 columns restored. After one FULL run the cached feature_store has Phase 2, so you can return to `QUICK_RESCORE_ONLY=True` for subsequent iterations.

## Environments
- **Local**: `C:\Users\Andrew Cha\Documents\codex`
- **Colab**: `/content/drive/MyDrive/r1000_top30_institutional`
- **Python**: `py -3` (Windows에서 `python`/`python3`은 App Store redirect되므로 사용 금지)

## Known Issues
- Alpha Vantage 무료 키: 일일 25콜 제한, `alpha_vantage_free_tier_mode=True`

## Pipeline Execution Order (Colab)
1. `%pip install` dependencies
2. Drive mount + sys.path setup
3. `collector_lean_full_run_cfg()` → `run_data_collection(cfg)`
4. `run_default_pipeline(cfg)` → `run_full_validation_suite(cfg)`

## Config Presets
- `collector_full_run_cfg()` — 전체 신규 실행
- `collector_lean_full_run_cfg()` — comparison 생략한 경량 실행
- `collector_reuse_step2_cfg()` — 캐시 재사용 빠른 실행
- `pipeline_quick_rescore_cfg()` — **fast-iter용 preset (~15-25min). feature_store + 모델 재사용, scoring + backtest만 다시 실행. 시그널 공식 변경은 반영 안 됨 (캐시됨) — sleeve 가중치 / phase toggle 튜닝 전용.**

## Fast-Iteration Workflow
새 phase 실험할 때 매번 1.5-4시간 FULL rebuild 돌리지 말 것.

### `colab_run.ipynb` cell 2 knobs
```python
QUICK_RESCORE_ONLY = True            # True=15-25min, False=FULL rebuild
PHASE1_ALPHA_ENABLED = 'auto'        # 'auto' | '0' | '1' (Phase 1 on/off)
PHASE2_INDUSTRY_ENABLED = 'auto'     # 'auto' | '0' | '1' (Phase 2 on/off)
```

### 모드 선택 규칙
| 변경 종류 | 모드 |
|---|---|
| sleeve 가중치 튜닝 | QUICK |
| phase A/B env toggle 측정 | QUICK |
| portfolio/cash cap 조정 | QUICK |
| 시그널 공식 변경 (`compute_*` / `build_*` / `add_*`) | FULL |
| `ENGINE_REUSE_VERSION` bump | FULL |
| walk-forward / embargo / 모델 구조 변경 | FULL |

### Phase toggle 매커니즘
- 엔진 최상단 `phase_is_enabled()` 헬퍼가 `PHASE_<KEY>_ENABLED` 환경변수 읽음.
- phase disable 시 관련 컬럼은 **삭제가 아니라 0.0으로 채움** (downstream sleeve 코드의 KeyError 방지).
- 새 phase 추가 시 반드시 같은 패턴 따를 것.

### 새 phase 추가 시 feature_store 생존 규칙 (2026-04-16 phase2-keepcols-fix)
`build_feature_store.keep_cols` 는 **명시적 whitelist** 다. `build_universe_monthly` 에서 붙인 컬럼이라도 whitelist 에 없으면 `fs = universe[keep_cols].copy()` 에서 drop 된다. 드롭되면:
1. `feature_store_latest.parquet` 에서 빠짐
2. walk-forward 가 훈련/스코어링할 때 `cross_sectional_robust_z` → NaN → 0.0 으로 fallback 돼서 시그널 contribution 이 **조용히 0 이 됨** (에러 없음)
3. `scored_latest.csv` 에도 안 나타남

**Phase 1 은 `compute_strategy_blueprint_columns` 가 `score_latest_month`/`prepare_latest_scored_data` 에서 재실행되므로 drop 돼도 최종 CSV 에는 나타난다** — 그래서 Phase 1 은 버그를 가려줬다. Phase 2 는 재계산 안 됐기 때문에 완전히 사라졌다.

**새 phase 추가 시 반드시**:
- `PHASE<N>_<NAME>_COLUMNS` 상수 만들고 (e.g. `PHASE2_INDUSTRY_COLUMNS`)
- `build_feature_store.keep_cols` 에 `+ PHASE<N>_<NAME>_COLUMNS` 추가
- 숫자 컬럼이면 같은 함수의 `hard_sanitize` 호출 리스트에도 추가
- phase toggle disabled 브랜치의 zero-placeholder 리스트와 동기화 유지

### A/B 측정 레시피
1. `PHASE_<KEY>_ENABLED=1` 로 QUICK run → metrics 기록.
2. `PHASE_<KEY>_ENABLED=0` 로 QUICK run → metrics 기록.
3. `outputs/concentrated_backtest_metrics.json`의 `strategy_cagr` / `sharpe` / `max_dd` diff.
4. phase ship 기준: Δ CAGR ≥ +0.5pp AND Δ MaxDD ≤ +2pp.

## Key Config Parameters
```python
cfg["reuse_existing_artifacts"] = True      # 캐시된 데이터 재사용
cfg["resume_partial_walkforward"] = False   # walk-forward 처음부터
cfg["macro_slow_release_lag_months"] = 1    # 매크로 지연 반영
cfg["companyfacts_refresh_days"] = 3        # SEC 데이터 갱신 주기
```

## Architecture
- Walk-forward training: 126일 embargo (look-ahead 방지)
- Ensemble: Ridge + LogisticRegression + CatBoost (reg/cls/rank)
- Point-in-time fundamentals: SEC accepted timestamp 기준
- Dual-sleeve portfolio: Core (70-95%) + Speculative (5-15%) + Cash (0-55%)
- Speculative hard stop-loss: -25%

## API Keys
- Alpha Vantage: 환경변수 `ALPHA_VANTAGE_API_KEY`
- SEC EDGAR: User-Agent 필요 (email)

## Changelog Writing Rules
- Write all CHANGELOG entries in **English only** — no Korean.
- Always include a real `HH:MM KST` timestamp. Never write `### KST -` without a time.
- Always include `symbols_added`, `symbols_changed`, `config_fields_added`, `breaking_changes` fields — use `none` when not applicable.
- List function/class names explicitly in `symbols_added`/`symbols_changed`, not prose descriptions.
- See the "Agent Update Contract" at the top of `CHANGELOG.md` for the full required format.

## Result Analysis
백테스트 결과에서 확인할 핵심 지표:
- `excess_cagr` > 0 → S&P 500 초과수익
- `ir` (Information Ratio) > 0.5 → 통계적 유의미
- `max_dd` — 최대 낙폭
- `beat_month_ratio` — 월간 승률
- `acceptance_checks` — 전체 통과 여부

## Phase 1+2 (2026-04-16) Alpha Columns to Check
새로 추가된 시그널 컬럼 (sanity check 용):
- Phase 1 (turnaround/value/uptrend):
  - `fundamental_turnaround_acceleration_score`, `cashflow_inflection_under_loss_score`
  - `value_inflection_score`
  - `uptrend_continuation_score`, `uptrend_breakdown_penalty`
- Phase 2 (industry RS / O'Neil leadership):
  - `industry`, `industry_group`, `subindustry` (from yfinance)
  - `rs_industry_{1,3,6,12}m`, `rs_industry_group_{1,3,6,12}m`
  - `industry_breadth_above_ma200`, `industry_group_breadth_above_ma200`
  - `industry_group_strength_score`, `industry_within_leader_rank`
  - `oneil_leadership_score`, `industry_rotation_signal`

## Phase 1+2 Baseline Comparison
직전 baseline (`outputs/concentrated_backtest_metrics.json`, 2026-04-15 rebalance):
- CAGR 21.80%, Sharpe 0.73, MaxDD -36.86%
- 새 실행 후 CAGR 개선 + MaxDD 유지/개선이 성공 기준.

## Multi-Session Phase Plan
**Phase 1..6 전체 계획 = `PHASE_ROADMAP.md` 에 저장됨.**

새 대화 시작할 때 순서:
1. 이 파일 (`CLAUDE.md`) 읽기 — 프로젝트 베이직.
2. `CHANGELOG.md` 마지막 ~150줄 읽기 — 최신 상태.
3. `PHASE_ROADMAP.md` 읽기 — 어디까지 했고 다음에 뭘 할지.
4. `outputs/concentrated_backtest_metrics.json` 확인 — 가장 최근 baseline.
5. Roadmap의 PR 순서대로 진행 (Phase 3 → 4 → 5 → 6a → 6b → 6c).

현재 상태:
- Phase 1 ✅ DONE (turnaround/value/uptrend alpha)
- Phase 2 ✅ DONE (industry RS / O'Neil leadership)
- Phase 3 📋 PLANNED — sleeve weight 감사 + 재정규화
- Phase 4 📋 PLANNED — regime-conditional dynamic sleeve weights
- Phase 5 📋 PLANNED — sub-industry leader/laggard pair
- Phase 6 📋 PLANNED — risk-off tail protection (drawdown breaker + VIX guard + vol targeting)
