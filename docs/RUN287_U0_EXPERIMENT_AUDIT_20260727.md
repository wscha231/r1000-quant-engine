# Run287 U0 기능·실험 감사 — 2026-07-27

## 결론

과거 실험 목록은 이제 21/21건 모두 분류됐지만, 승격에는 사용할 수
없다. 현재 상태는 `VALID_INVENTORY_PROMOTION_BLOCKED`다.

- registry 누락: 0건
- 분류 완료: 21건
- 승격 차단: 21건
- 현재 master 계보에서 빠진 PR 증거 참조: 21개
- 동일 trial을 중복 계산할 수 있는 개념 중첩군: 4개
- 이번 작업으로 허용된 fullrun, champion 변경, production, live trading:
  모두 없음

여기서 `VALID`는 감사 목록의 구조와 차단 사유가 정확하다는 뜻이다.
성과가 유효하거나 개선됐다는 뜻이 아니다.

## 처음부터 다시 본 결과

기존 do-not-repeat registry는 실패 아이디어를 반복하지 않는 데는
유용했지만, 다중검정 모집단으로는 충분하지 않았다.

1. 일부 항목은 결과 파일이 아니라 계획 문서만 근거로 삼고 있었다.
2. 2026-07-07~09의 PR #226~#240은 GitHub에서 병합 기록이 남아 있지만
   현재 master의 조상 계보에는 없다. 그 PR들의 요약 JSON과 arm CSV는
   orphaned commit에만 남아 있다.
   inventory에 기록한 Git blob OID는 해당 파일을 다시 찾기 위한 불변
   locator일 뿐이며, 그 자체를 일별 수익률 또는 승격 증거로 인정하지 않는다.
3. PR 본문과 요약 메트릭은 남아 있어도 synchronized daily after-cost
   return은 대부분 보존되지 않았다.
4. 하나의 실제 trial이 여러 registry 이름에 겹쳐 있다.
   이를 항목별로 각각 세면 다중검정 수를 부풀리거나, 반대로 임의로
   하나만 고르면 누락시킬 수 있다.
5. source screen, no-signal, no-op, portfolio A/B가 한 가지
   `REJECTED` 의미로 섞여 있었다.
6. registry가 가리키는 로컬 결과 5개는 현재 폴더와 Git에 없다.

따라서 요약 CAGR/MDD를 daily return으로 바꾸거나, 결과가 없는 실험을
`performance_evaluated=false`로 편의상 처리하지 않는다.

## 분류

| 평가 유형 | 건수 | 처리 |
|---|---:|---|
| Portfolio return | 11 | exact manifest와 daily return 복구 전 승격 차단 |
| Source + portfolio 혼합 | 2 | 두 평가를 분리하고 중복 제거 전 차단 |
| Source return screen | 3 | source-selection 다중검정 보정 전 차단 |
| No signal | 1 | 시도 횟수에는 반영하되 가짜 zero-return 생성 금지 |
| Portfolio no-op | 1 | 시도한 family로 보존; champion과 동일한 열을 정확히 복구 |
| Invalid/incomplete | 1 | 성과 증거로 사용 금지 |
| 근거 미확인 legacy 주장 | 2 | 원 run 발견 또는 정식 schema migration 전 차단 |

## 중복 계산 방지

다음 네 관계를 명시적으로 고정했다.

- `weak_source_fusion`과 `direct_growth_tilt`
- `static_actual_profitability`와
  `technical_macro_risk_financial_proxy`
- `ownership_13f_form4`와 `w4_sec_percentile_tilt`
- `sec_market_confirmed_fundamental_event`와
  `sec_filing_quality_event`

이 관계는 같은 원 trial 또는 같은 source-screen 계보를 이름만 달리해
두 번 세는 것을 막는다.

## 현재 CAGR/MDD 해석

새 fullrun은 실행하지 않았다. 따라서 여전히 사용할 수 있는 수치는
checksum-locked fixture뿐이다.

| Portfolio | Fixture CAGR | Fixture MDD | 목표까지 남은 차이 |
|---|---:|---:|---:|
| Main | 34.4032% | -25.3629% | CAGR +0.5968%p, MDD +0.3629%p |
| Concentrated | 49.0968% | -22.9560% | CAGR +0.9032%p |

이 값은 corrected rebaseline이 아니며 최근 시장을 반영한 새 성과 주장도
아니다.

## 복구 순서

1. orphaned PR의 summary/arm table을 commit, path, Git blob OID로 복구한다.
2. 각 family의 모든 파라미터를 분리하고 중복 trial을 하나의 ID로
   정규화한다.
3. 동일 날짜축의 daily after-cost excess return을 복구한다.
4. source screen과 no-signal 시도에는 별도 selection-multiplicity
   penalty를 구현한다.
5. 21건 전체가 정확한 모집단으로 고정되기 전에는 새 challenger
   백테스트를 시작하지 않는다.
6. 그 후 materially new한 인과 가설 하나만 사전등록한다.
7. PIT·비용·유동성·과최적화 preflight가 모두 통과한 경우에만 별도
   사용자 승인으로 corrected fullrun 한 번을 실행한다.

## CAGR/MDD 개선 원칙

앞으로의 개선은 기존 실패 family의 임계값 재조정으로 만들지 않는다.
새 후보는 다음 조건을 동시에 만족해야 한다.

- 기존 reconstruction과 다른 인과 메커니즘
- 결정 시점에 실제 이용 가능했던 PIT 데이터
- Main과 Concentrated의 별도 성과·위험 귀속
- spread, slippage, ADV, impact가 포함된 비용
- Full/OOS/OOS2와 regime·block robustness
- DSR, PBO, Reality Check 통과
- 목표를 못 넘으면 champion 유지

현재 가장 먼저 해야 할 일은 새 수치를 만드는 것이 아니라 누락된
과거 모집단을 정확히 복구하는 것이다. 그래야 이후의 CAGR/MDD 개선이
우연한 승자나 반복 실험의 산물이 아니라고 말할 수 있다.

기계 판정 계약은
`docs/run287_u0_experiment_audit_contract.json`, 전체 목록은
`docs/run287_u0_experiment_inventory.json`, 검증기는
`tools/audit_run287_u0_experiment_inventory.py`에 있다.
