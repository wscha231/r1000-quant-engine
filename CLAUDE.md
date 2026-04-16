# r1000 Quant Engine - Project Guide

## Project Overview
Russell 1000 기반 Top 30 기관급 퀀트 종목 선정 엔진. S&P 500 초과수익 목표.

## Key Files
- `r1000_top30_institutional.py` — 메인 엔진 (~25,500+ lines)
- `r1000_data_collector.py` — 데이터 수집 + 검증 파이프라인
- `colab_run.ipynb` — Colab 실행 런북 (GitHub master pull → collector → pipeline → validation)

## Current Engine Version
- `ENGINE_REUSE_VERSION = "2026-04-16-phase1+2-turnaround-value-industry-rs"`
- Cache invalidation: 버전 문자열이 바뀌면 `cache_*`/`feature_store` 아티팩트가 자동 재생성됨.

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
