# R1000 — 병목·해자 인과진단 V1 구현 및 인계

- TASK_KEY: `R1000-A23-MOAT-BOTTLENECK-DIAGNOSTIC-T2-20261025`
- Parent: #610/#612, #479, #516, #670
- Repository: `wscha231/r1000-quant-engine`
- Observed baseline master: `f535167a55f1f5dd79cdeb414e7a2aa2da9a2012` (재확인 필요)
- Scope: **RESEARCH_ONLY / T1 COMPUTE + T2 PREPARE / ADD-ONLY CANDIDATE**
- State: `LOCAL_IMPLEMENTED_SYNTHETIC_TESTED / NOT_NATIVE_APPLIED / NOT_REAL_INPUT_ADMITTED`

## 이미 존재하는 코드와 중복금지 경계

- 그대로 유지: `research/moat_quality_v2.py`의 기존 6차원, 원문/증거의 hash·시각 검증 및 정성 연구 점수.
- 그대로 유지: `research/investment_methodology_v1.py`, `research/a3_candidate_packet_v1.py`, `research/candidate_registry_v1.py`.
- 추가한 1개 library: `research/moat_bottleneck_diagnostic_v1.py`.
- 직접 import되지 않는 보조 연구층. 새 scheduler/reader/source collector/selector 없음.
- 기존 SEC·IR과 A2 이벤트는 #612, #503, #516의 원래 검증 경계를 통과해야 함. 뉴스/영상/텔레그램의 서술은 투자 근거로 인정하지 않음.

## 기능 구현

1. 기존 Moat V2 **결과의 원본 바이트 해시**, asset/issuer, 상태, 시계 및 경제권한 false 검증 후 연결한다. 단, 이 단계는 원본 인증·독립 A6·실제 A3 승인을 의미하지 않는다.
2. 원인의 네 범주를 분리한다: `capital_intensity`, `technical_complexity`, `accumulated_knowhow`, `institutional_protection`.
3. 각각 EVIDENCED/CONTESTED/WEAK/UNKNOWN/NOT_APPLICABLE, 인과기전, 반대 논거, 훼손조건, 참조 검증 근거를 기록한다. 강한 장벽은 독립 근거 필요, 미상은 허위 증거 금지.
4. 산업의 `capacity_growth_yoy_pct - demand_growth_yoy_pct`를 **기간·측정범위가 일치할 때만 단순 계산**한다. 양수=증설속도가 빠를 수 있다는 진단이지 병목 해소 판정이나 자동 매도 신호가 아니다.
5. `roic_pct - wacc_pct`를 동일 기간·basis에서만 percentage points로 계산한다. 미확보·불일치 시 null과 원인을 반환한다.
6. 입력별 시각: observed/published/available/collected/verified/valid-through. 식별자·raw SHA256·독립성·존재/차단 조건을 확인하며 SHA 단독은 공급자 인증이 아니다.

## 호출 계약

```python
from research.moat_bottleneck_diagnostic_v1 import evaluate
research_result = evaluate(
    diagnostic_packet,
    cutoff="<TRUSTED_TIMEZONE_AWARE_DECISION_CUTOFF>",
    raw_resolver=approved_readonly_resolver,
)
```

`diagnostic_packet`은 `schema`, `asset_id`, `issuer_id`, `as_of`, `reviewed_at`, `review_status`, `moat_result_ref`, `evidence[]`, `barriers{}`, `metrics[]`를 갖는다. 합성 실행 fixture는 `tests/test_moat_bottleneck_diagnostic_v1.py` 참조. 원본 파일 경로·토큰을 직접 입력하지 말고 A0/A3의 승인된 artifact resolver를 주입한다.

`moat_result_ref`는 existing Moat V2 result bytes를 가리킨다. **Moat 결과의 저장된 hash가 일치하더라도 Moat V2 원본 packet의 독립 재실행 검증이나 A0 current admission을 대신하지 않는다.** 이전 리뷰/정본 증거가 없으면 현행 사용은 BLOCKED다.

반환: `moat_v2_score_unchanged`, 4개 barrier 진단, 입증 원본 참조, 선택적 `capacity_minus_demand_growth_pp`, `roic_minus_wacc_pp` 및 누락/비교불가 상태. 모두 `research_only=true`, `selector_eligible=false`, `er_eligible=false`, `portfolio_weight_effect=0`, `orders_allowed=false`.

## 명확한 한계 및 다음 단계

- 네 원인 평가를 Moat 기존 6축에 더해 가산하지 않는다. 개인/기관 뉴스 발표는 V0 discovery일 수 있지만 evidence가 아니다.
- WACC 등 산출값과 원시 바이트 hash의 결합만으로 수치가 실제 원문과 일치함을 증명하지 않는다: `metric_values_externally_reconciled=false`.
- 실측 전 수익 개선·병목 해소 시점·주가 방향성을 판정할 수 없다.
- 검증된 실제 A3 Moat result/원문·지표가 준비되면 기존 #612 분석에 **연구-only sidecar ref**로 붙이고, 선택한 실제 후보의 1회 scoped ACK를 얻는다. #516 canonical Registry를 자동 갱신하지 않는다.
- 훗날 PIT·OOS가 준비되면 control 대비 `revised_ER`, missed winner, winner tenure, FCF/마진 인과 갱신 효과를 측정한다. 기존 holdout 재튜닝 금지.

## 설치·검증

현행 source writer, main writer 소유권을 교차 확인한 후 단일 Main lane에서 다른 원인 변경과 섞지 말고 **별도 Draft PR**로 추가한다. 원파일 수정 0, 신규 3개 파일만 적용. 검증:

```
python -m unittest -v tests/test_moat_bottleneck_diagnostic_v1.py
python -O -m unittest -v tests/test_moat_bottleneck_diagnostic_v1.py
```

PR에 등록해야 할 기존 Native smoke/CI 경로는 보호된 공용 런너를 먼저 확인한 뒤 담당자가 최소 변경으로 처리한다. 이 로컬 검증은 Repo-native/실제-input 검증이나 A6 결과가 아니다. `AGENT_SHARED_LESSONS_LEDGER.md` 변경은 현재 Main owner의 통합 단계에서 기존 기록과 대조하여 별도 반영한다.

**공유 교훈 제안:** 새로운 정성 해자 원인을 기존 Moat 6축에 가산하면 중복 계산된다. Moat 원인, 이익 포착, 공급 증설은 인과·기간·측정범위가 다른 자료다. 원본 해시만으로 시장/PIT/정량 수치의 진실을 인증하지 않는다.
