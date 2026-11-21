# R1000 — 베타 2축(추세×위험) 진단 V1 구현 및 인계

- TASK_KEY: `R1000-A4-TREND-RISK-BETA-DIAGNOSTIC-T2-20261025`
- Parent: #447/#617, #526, #670
- Repository: `wscha231/r1000-quant-engine`
- Observed baseline master: `f535167a55f1f5dd79cdeb414e7a2aa2da9a2012` (재확인 필요)
- Scope: **RESEARCH_ONLY / T1 COMPUTE + T2 PREPARE / ADD-ONLY CANDIDATE**
- State: `LOCAL_IMPLEMENTED_SYNTHETIC_TESTED / NOT_NATIVE_APPLIED / NOT_REAL_INPUT_ADMITTED`

## 목적과 기존 재사용 경계

- 기존 `tools/run287_crisis_policy.py`, `tools/crisis_state_engine.py`, `tools/chameleon_market_context_v2.py`, `tools/run_daily_crisis_monitor.py`를 **수정하거나 중복 실행하지 않는다**.
- 기존 A4 `DATA_BLOCKED`를 유지한다. 위기상태·gross cap·현금비중·재진입상태로의 묵시적 매핑 **금지**.
- 추가 모듈은 독립적으로 받은 **사전 고정 정규화 관측치**로 방향(-1..+1)과 위험(0..1)을 진단한다. 영상은 정확한 가중치/정규화 공식을 공개하지 않았으므로 공식 Beta Model 재현을 주장하지 않는다.

## 계산 내용

### Trend (완전 입력에서만)

- MA21·63·126 상대 추세 세 값을 먼저 평균 → MA 가족 1개.
- 나머지 3가족: 252세션 고점대비 하락, 글로벌 상대수익, 전체 시장 breadth.
- 네 가족을 동일한 연구용 단순평균. 필수 가족 하나라도 누락 시 `trend_score=null`.

### Risk (완전 가족에서만)

- 옵션/실현변동성 `max(VIX stress, realized volatility stress)` → 가족 1개.
- 하락 거래량 집중 → 가족 1개.
- 금리/FX 충격 `max(rate, FX)` → 가족 1개.
- 신용스프레드 스트레스 → 가족 1개.
- 네 가족 동일한 연구용 단순평균. VIX/VVIX/변동성 계열이나 금리/FX 계열의 각각을 독립 투표처럼 가산하지 않는다.

4국면 진단은 `trend=0`, `risk=0.5`의 **설명용 고정 경계**를 사용하며, 경계는 `BOUNDARY_REVIEW`다. 주식 비중 60~100%, 현금 40%, 빠른 매도/느린 매수 규칙은 **설계 의도 비교용**이며 여기에는 구현하지 않았다. 우량 승자를 자동 매도하지 않는다.

### 순수 원시 입력 정규화 helper

`normalize_raw_research_inputs(raw, scales)`는 기존 피처/적격 자료가 생겼을 때 호출할 **가설적 변환**이다. `scales`는 `ma_ratio_saturation`, `drawdown_depth_fraction`, `global_rs_log_saturation` 세 양의 명시 값이며, 기본값/자동튜닝/과거 holdout 탐색은 없다. 예시 fixture는 가짜 0.10,0.20,0.10을 사용하며 투자정책 임계값이 아니다.

- 추세 MA: clip((price/MA−1)/scale, −1,1)
- 고점 drawdown: clip(1+2×drawdown/scale, −1,1)
- 글로벌 로그 상대수익: clip(log excess return/scale, −1,1)
- breadth: 2×확인된 시장폭 비율−1
- 하락 거래량: clip(2×(하락거래량비중−0.5),0,1)
- VIX·실현변동성·FX·금리·신용 충격은 **외부에서 정의된** percentile (0..1)를 사용. 과거 수정된 데이터의 오늘 기준 분위수를 당시 PIT로 재사용하지 않는다.

이 helper의 결과만으로 실제 A4 점수를 승인할 수 없다. 증거와 계산 계보를 바인딩한 이후 `evaluate`로 전달한다.

## 호출 계약

```python
from research.trend_risk_beta_diagnostic_v1 import (
    normalize_raw_research_inputs, evaluate, compare_snapshots,
)
normalized = normalize_raw_research_inputs(reviewed_raw_values, fixed_scales)
# A1/A4가 normalized values를 각 실제 source/기준시각/계산 receipt와 묶은 후:
diagnostic = evaluate(packet, cutoff="<TRUSTED_DECISION_TIME>",
                      raw_resolver=approved_readonly_resolver)
# 서로 다른 완료 세션에만, 같은 정규화 계약일 때:
research_delta = compare_snapshots(previous_result, diagnostic)
```

`packet`에는 `schema`, `market_id`, `benchmark_id`, `as_of`, `session_date`, `review_status`, `normalization_method`, `normalization_version`, `normalization_config_sha256`, `observations`를 둔다. 원본·시각·완료 세션·breadth 분모 등 적격 입력이 없으면 점수를 발명하지 않는다. 합성 fixture: `tests/test_trend_risk_beta_diagnostic_v1.py`.

`compare_snapshots`는 정상 순서의 동일 시장/벤치마크/정규화 결과의 1차 변화만 계산하며, 진짜 공급자 provenance의 독립 인증·위험 가속도(3관측 필요)는 제공하지 않는다.

출력 `trend_score`, `risk_stress_score`, `quadrant_diagnostic`, `risk_families`는 **진단용**이다. `source_authenticated=false`, `historical_pit_certified=false`, `regime_authorized=false`, `cash_weight_proposal=null`, `gross_exposure_cap=null`, `policy_action=null`을 반드시 유지한다. Risk=0.8은 하락 확률 80%가 아니다.

## 실제 A4/시장 연결의 선행조건

1. 기존 #670 A4 exact source/receipt 및 현재 freshness/PIT를 확인해 `DATA_BLOCKED` 해소. Source 원본이 없으면 합성 또는 과거 current-vintage로 대체 불가.
2. 실제 미·한 market/benchmark/data lineage, 날짜별 VIX·신용·breadth·FX·rate·distribution 동시성 및 정규화 스케일의 preregistration/A6 확인.
3. 현행 crisis 정책과 동일 원천자료를 **추가 투표**시키지 않고, A4의 별도 진단 ref만 사용. A5 총노출 변경은 별도 naming된 Control/Challenger, 체결·비용·OOS/회복·winner hold 검증 후 별도 승인.
4. R1000 과거 Family A에서 월간 현금방어 규칙만 강화해 2020 급락을 못 막았던 교훈을 반드시 유지. 신호의 관측시각과 거래 가능한 의사결정시계가 무엇보다 중요.

## 설치·검증

Main writer scope를 확인한 다음 별도 Draft PR로 신규 3개 파일만 적용(새 cron 및 기존 risk policy 수정 0).

```
python -m unittest -v tests/test_trend_risk_beta_diagnostic_v1.py
python -O -m unittest -v tests/test_trend_risk_beta_diagnostic_v1.py
```

본 패키지 테스트는 로컬 합성 입력과 독립 계산에 대한 것일 뿐, 공식 Live/Regime/PIT 또는 전체 repo CI/A6 검증이 아니다.

**공유 교훈 제안:** 위험 수준과 위험 점수의 변화를 분리한다. 서로 관련된 옵션·주가·금리 계열에 중복 투표를 부여하지 않는다. 원본 부족을 낮은 위험으로 치환하지 말고 `PARTIAL_RESEARCH_CONTEXT`를 반환한다.
