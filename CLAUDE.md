# r1000 Quant Engine - Project Guide

## Project Overview
Russell 1000 기반 Top 30 기관급 퀀트 종목 선정 엔진. S&P 500 초과수익 목표.

## Key Files
- `r1000_top30_institutional.py` — 메인 엔진 (~15,000+ lines)
- `r1000_data_collector.py` — 데이터 수집 + 검증 파이프라인

## Environments
- **Local**: `C:\Users\Andrew Cha\Documents\codex`
- **Colab**: `/content/drive/MyDrive/r1000_top30_institutional`
- **Python**: `py -3` (Windows에서 `python`/`python3`은 App Store redirect되므로 사용 금지)

## Known Issues
- Alpha Vantage 무료 키: 일일 25콜 제한, `alpha_vantage_free_tier_mode=True`

## Pipeline Execution Order (Colab)
1. `%pip install` dependencies
2. Drive mount + sys.path setup
3. `validate_config` monkey-patch (cash_weight_max fix)
4. `collector_lean_full_run_cfg()` → `run_data_collection(cfg)`
5. `run_default_pipeline(cfg)` → `run_full_validation_suite(cfg)`

## Config Presets
- `collector_full_run_cfg()` — 전체 신규 실행
- `collector_lean_full_run_cfg()` — comparison 생략한 경량 실행
- `collector_reuse_step2_cfg()` — 캐시 재사용 빠른 실행

## Key Config Parameters
```python
cfg["reuse_existing_artifacts"] = True      # 캐시된 데이터 재사용
cfg["resume_partial_walkforward"] = False   # walk-forward 처음부터
cfg["macro_slow_release_lag_months"] = 1    # 매크로 지연 반영
cfg["companyfacts_refresh_days"] = 7        # SEC 데이터 갱신 주기
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

## Result Analysis
백테스트 결과에서 확인할 핵심 지표:
- `excess_cagr` > 0 → S&P 500 초과수익
- `ir` (Information Ratio) > 0.5 → 통계적 유의미
- `max_dd` — 최대 낙폭
- `beat_month_ratio` — 월간 승률
- `acceptance_checks` — 전체 통과 여부
