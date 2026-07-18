# Run287 CAGR/MDD 병목 판정 — 2026-07-15

## 결론

현재 성능 강화는 중단된 것이 아니라 **검증 가능한 다음 arm을 선정하는 단계**다. 공식 Run287 역사 artifact를 다시 분해한 결과, 오늘 즉시 열 수 있는 역사 challenger는 0개이며 상태는 `BLOCKED_NO_ELIGIBLE_HISTORICAL_CHALLENGER`다.

이는 더 이상 연구하지 않는다는 뜻이 아니다. 현재 selector edge를 훼손할 가능성이 큰 기존 cash/exit/execution 재튜닝을 닫고, 다음 두 경로 중 먼저 증거가 준비되는 경로에서 단 하나의 A/B를 시작한다.

1. `50 security / 200 event` 외부 PIT estimate-revision source가 통과하면 역사 source screen → fixed-book A/B를 즉시 시작한다.
2. 외부 source가 없으면 individual-risk forward archive가 표본 게이트에 도달한 뒤에만 신규매수 freeze 또는 가장 작은 risk mechanism을 사전등록한다.

fullrun은 두 독립 포트 후보가 모든 게이트를 통과한 뒤 별도 승인 전까지 실행하지 않는다.

## 현재 목표까지 남은 폭

| 포트 | generated baseline | 목표 | 남은 폭 |
|---|---:|---:|---:|
| Main | CAGR 34.4032% / MDD -25.3619% | 35% / -25% | CAGR +0.5968%p, MDD +0.3619%p |
| Concentrated | 49.0971% / -22.9552% | 50% / -25% | CAGR +0.9029%p, MDD 통과 |

아래 역사 attribution의 broker-ledger 수치는 진단 경로다. 위 generated baseline을 대체하지 않는다.

## 병목별 판정

### 1. 종목선정: 보존

선택된 ex-ante leader는 미선택 leader보다 두 포트 모두 21/63/126일 평균과 중앙 SPY 초과수익이 높았다.

| 포트 | 21D 평균 spread | 63D 평균 spread | 126D 평균 spread | 63D 중앙 spread |
|---|---:|---:|---:|---:|
| Main | +2.3192%p | +5.1205%p | +11.8519%p | +2.0887%p |
| Concentrated | +2.0488%p | +5.6467%p | +18.3284%p | +2.8046%p |

따라서 현재 핵심 문제를 “selector가 좋은 종목을 못 고른다”로 해석하면 안 된다. selection edge는 보호한다.

### 2. 현금의 광범위 재투자: 기각

cash 이유로 놓친 ex-ante leader의 63일 결과는 양수가 아니었다.

| 포트 | 표본 | 평균 SPY 초과수익 | 중앙 SPY 초과수익 |
|---|---:|---:|---:|
| Main | 845 | -0.1028% | -1.3763% |
| Concentrated | 846 | -0.7874% | -1.9838% |

과거 cash drag 자체는 Main 약 -8.7%, Concentrated 약 -4.7%로 진단됐지만, “현금을 줄여 놓친 leader를 모두 산다”는 처방은 수익률 evidence와 맞지 않는다. broad gross floor와 cash floor도 이미 실패 registry에 있다.

### 3. 일반 exit-delay: 기각

매도 종목과 같은 날 replacement의 이후 수익을 비교한 결과가 63/126일에서 일관되게 양수가 아니었다.

| 포트 | 63D 매도종목-minus-replacement 평균 / 중앙 | 126D 평균 / 중앙 |
|---|---:|---:|
| Main | +0.7785%p / -1.5204%p | -1.6769%p / -2.2341%p |
| Concentrated | -0.1067%p / -3.0440%p | -2.4742%p / -3.8941%p |

`premature_sell_candidate`라는 진단 행이 많다는 사실만으로 보유기간을 늘리면 안 된다. 기존 stop/exit-delay lane과 replacement rule은 재실행하지 않는다.

### 4. execution·position-risk overlay: 기각

기존 broker baseline 대비 진단 delta는 다음과 같다.

| 포트 | mechanism | dCAGR | dMDD |
|---|---|---:|---:|
| Main | execution policy | -0.5982%p | -3.2345%p |
| Main | position risk | -3.7020%p | -0.4926%p |
| Concentrated | execution policy | -5.7516%p | -10.1556%p |
| Concentrated | position risk | -10.8167%p | +0.0684%p |

특히 Concentrated position-risk는 MDD 개선이 0.07%p뿐인데 CAGR를 10.82%p 잃는다. 기존 composite execution과 generic technical risk control을 다시 조정하지 않는다.

### 5. Concentrated 단일종목 MDD: 가장 강한 위험 진단, 아직 action 금지

2025-02-18~2025-04-08 MDD 구간에서 PLTR은 상위 30개 음의 position P&L 중 34%인 약 -$57,128을 기여했고 최대 비중은 33.6%였다.

이것은 현재 가장 강한 MDD 병목 진단이지만, 곧바로 cap grid·stop·cluster cap을 만들 수는 없다. 해당 계열은 이미 실패했고, individual-risk forward archive는 현재 1 decision week, resolved outcome 0이다. 기존 ALERT/WATCH/NORMAL 결과가 성숙할 때만 가장 작은 신규매수 freeze mechanism을 검토한다.

## CAGR/MDD 강화는 언제 시작되는가

### 가장 빠른 경로: 외부 PIT source

무료 또는 승인된 sample이 v2 schema/PIT gate와 source screen을 통과하면 기다릴 달력 조건이 없다. 그 즉시 단일 fixed-book A/B를 실행할 수 있다. 단, 현재는 다음 두 blocker가 남아 있다.

- `external_pit_source_gate_not_ready`
- `external_pit_source_screen_not_passed`

### 시간 기반 경로: forward evidence

현재 risk archive는 2026-07-13의 1 decision week와 0 resolved outcome이다.

- 첫 21거래일 결과: 대략 2026년 8월 중순부터 보이지만 조기 진단일 뿐이다.
- 첫 63거래일 결과: 대략 2026년 10월 중순부터 보이지만 단일 cohort로는 행동할 수 없다.
- 12개 decision week와 63D 성숙·200개 outcome을 함께 요구하면, 매일 수집이 정상적으로 이어질 경우 **가장 이른 실질 review 창은 2026년 11월 말~12월 말**이다.
- true-forward event 축적 속도가 현재보다 느리면 2027년 1분기로 밀릴 수 있다.

이 날짜는 승격 보장이 아니라 review를 열 수 있는 이론상 최단 창이다.

## 이번 작업의 결정

- 현재 selection edge를 보호한다.
- broad cash deployment, generic exit delay, 기존 execution/risk overlay를 열지 않는다.
- 단일종목 위험은 forward review 전용으로 유지한다.
- 역사 성능 개선의 우선 경로는 외부 PIT revision source 하나뿐이다.
- 모델, score, rank, selector, target, cash, order는 변경하지 않았다.
- 새 역사 backtest와 fullrun은 실행하지 않았다.

## 증거

- `docs/run287_performance_bottleneck_contract_v1.json`
- `tools/audit_run287_performance_bottlenecks.py`
- `outputs/run287_performance_bottleneck_decision_20260715/manifest.json`
- `outputs/run287_performance_bottleneck_decision_20260715/selection_spread.csv`
- `outputs/run287_performance_bottleneck_decision_20260715/cash_rejection_evidence.csv`
- `outputs/run287_performance_bottleneck_decision_20260715/exit_counterfactual.csv`
- `outputs/run287_performance_bottleneck_decision_20260715/component_decision.csv`

첫 진단 `outputs/run287_performance_bottleneck_audit_20260715/`은 artifact wrapper를 legacy sidecar input으로 준 탓에 missing input으로 차단됐다. 삭제하지 않고 보존했다. `outputs/run287_performance_bottleneck_audit_20260715_v2/`는 실제 `outputs/` root를 사용해 trade-attribution과 operating-event를 복원했다. entry/exit·cash raw input은 공식 artifact에서 일부 pruning됐으므로 공식 artifact에 이미 포함된 hash-pinned completed audit를 최종 aggregator가 직접 사용했다.
