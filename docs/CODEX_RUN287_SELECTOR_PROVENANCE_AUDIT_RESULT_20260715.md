# Run287 selector provenance P0 결과 — 2026-07-15

## 결론

GPT Pro의 두 검토 답변에서 공통으로 제안한 첫 작업인 2026-07-13 selector provenance audit를 완료했다.

상태는 `READY_SELECTOR_PROVENANCE_INTENTIONAL_PARALLEL_PATH`다. `MRVL`, `DELL`, `FLEX`, `UMC`, `COHU` 5개가 advisory에는 선택되고 daily operating book에는 없었던 직접 원인은 **종목별 탈락이나 미체결이 아니라 서로 다른 생성 시각과 쓰기 권한을 가진 병렬 selector 경로**였다.

- daily operating target book 생성: `2026-07-14T04:37:16.457950Z`
- no-write advisory 생성: `2026-07-14T08:51:03.706479Z`
- advisory가 operating보다 늦은 시간: `15,227.248529초` = 약 4시간 13분 47초
- advisory 계약: target 생성 금지, target mutation 금지, order 생성 금지, execution 금지

따라서 이번 5개 차이에서 recoverable implementation leakage는 `0`이다. 이 결과를 alpha 결함으로 간주해 역사 replay나 포트 변경을 시작하면 안 된다.

## P0 게이트 결과

| 게이트 | 결과 |
|---|---:|
| selector archive 재현 | 50/50 |
| archive 행 설명 | 50/50 |
| 전체 advisory-operating-paper 합집합 | 83행 |
| preregistered divergence | 5/5 |
| scenario weight conservation | 3/3 |
| selector weight 최대 오차 | 0 |
| archive weight 최대 오차 | 0 |
| unknown/other reason code | 0 |
| input availability 위반 | 0/7 |
| paper 정수주식 exact | 20/20 |
| paper cash 최대 오차 | $0.00 |
| recoverable implementation leakage | 0 |

## 다섯 종목

| 종목 | advisory 선택 scenario | operating/paper | causal reason |
|---|---|---|---|
| COHU | Main strict | 미선택 | `ADVISORY_CREATED_AFTER_OPERATING_NO_WRITE` |
| DELL | Main strict·bridge, Concentrated strict | 미선택 | 동일 |
| FLEX | Main strict·bridge | 미선택 | 동일 |
| MRVL | Main strict·bridge | 미선택 | 동일 |
| UMC | Main strict·bridge, Concentrated strict | 미선택 | 동일 |

이 reason code는 “종목이 나빠서 탈락”이라는 뜻이 아니다. operating book이 이미 만들어진 뒤 advisory가 생성됐으며, advisory에는 operating target으로 persistence할 권한 자체가 없었다는 뜻이다.

## 현금 waterfall

### Advisory selector

| 포트·scenario | 최종 advisory cash | 구성 |
|---|---:|---|
| Main bridge | 7.5889% | 초기 미배분 3.0000% + top-N filter 잔여 4.5889% |
| Main strict | 8.5985% | 초기 미배분 3.0000% + top-N filter 잔여 5.5985% |
| Concentrated strict | 34.0937% | 초기 3.0000% + hold-decay trim 18.6373% + weak-RS/new-entry cap 8.9877% + regime 0.95 multiplier 3.4688% |

Concentrated의 34.09% advisory cash는 새 macro call이나 임의 cash target이 아니라 기존 cap·trim·capacity 단계에서 생긴 deterministic residual이다. 이를 낮추기 위한 gross-floor나 cash knob 재튜닝은 금지한다.

### Daily operating target과 paper bootstrap

daily operating target은 Main 17종목, Concentrated 3종목에 stock weight 100%를 배정했다. $100,000 simulated account에 정수주식으로 bootstrap하면서 다음 잔여 현금이 생겼다.

| 포트 | operating target cash | paper cash | 원인 | cash 재현 오차 |
|---|---:|---:|---|---:|
| Main | 0% | 1.3670% | integer-share rounding | $0.00 |
| Concentrated | 0% | 0.7140% | integer-share rounding | $0.00 |

fill, pending order, rejection, transaction fee는 모두 0이었다. 즉 이 snapshot의 paper cash는 미체결이나 위험 회피가 아니라 bootstrap rounding이다.

## 중요한 시스템 해석

현재 저장소에서 “operating book”이라는 이름은 하나의 Run287 causal chain을 의미하지 않는다.

1. frozen official/generated Run287 book
2. daily operating selection refresh가 만든 별도 target book
3. 이후 생성되는 exact Run287 no-write advisory
4. daily operating target에서 bootstrap된 paper account

이 네 경로가 같은 날짜에 존재하지만 자동 승격·persistence 관계는 아니다. 이번 감사는 이 분리를 정확히 설명했지만, 전체 operating selector가 각 종목을 왜 선택했는지에 대한 per-ticker causal taxonomy까지 완성한 것은 아니다.

## CAGR/MDD 영향

Main `34.4032% / -25.3619%`, Concentrated `49.0971% / -22.9552%`는 변하지 않았다. 숨은 deterministic defect가 발견되지 않았으므로 이번 divergence를 고쳐 목표 격차를 메우는 성과 replay는 열지 않는다.

GPT Pro가 정한 fallback에 따라 다음 bounded gate는 다음 두 가지다.

1. forward archive는 기존 비용 circuit breaker 안에서 계속 축적한다.
2. 신규 역사 alpha lane은 `50 unique securities + 200 event rows` PIT estimate/guidance sample의 schema·timestamp·delisted·ADR identity 검증부터 시작한다.

유료 비용이 발생하거나 역사 A/B를 열기 전에는 사용자 승인을 요청한다.

## 생성물

- `docs/run287_selector_provenance_audit_contract_v1.json`
- `tools/audit_run287_selector_provenance.py`
- `tests/run287_selector_provenance_audit_smoke.py`
- `outputs/run287_selector_provenance_audit_20260715_close_20260713_v2/selector_provenance_long.csv`
- `outputs/run287_selector_provenance_audit_20260715_close_20260713_v2/divergence_reconciliation.csv`
- `outputs/run287_selector_provenance_audit_20260715_close_20260713_v2/cash_waterfall.csv`
- `outputs/run287_selector_provenance_audit_20260715_close_20260713_v2/execution_persistence_ledger.csv`
- `outputs/run287_selector_provenance_audit_20260715_close_20260713_v2/input_availability_audit.csv`
- `outputs/run287_selector_provenance_audit_20260715_close_20260713_v2/manifest.json`

첫 실행 `outputs/run287_selector_provenance_audit_20260715_close_20260713/`은 projection에 이미 존재하는 explicit `CASH` 행을 감사 코드가 residual cash로 다시 계산해 `selector_weight_reproduction`으로 fail-closed된 진단 run이다. 삭제하지 않고 실패 증거로 보존했다. v2에서 explicit cash semantics를 수정하고 synthetic smoke로 회귀를 고정했다.
