# Run287 일일 증거 파이프라인 내구성 보강 결과 — 2026-07-16

## 결론

2026-07-15 미국장 종가가 아직 확정되지 않은 01:21 KST 시점에는 포트와 `score_latest`를 갱신하지 않았다. 대신 직전 완료 세션인 2026-07-14를 처리한 자동화에서 발견된 두 가지 실제 결함을 보강했다.

1. 가격 캐시 전체의 마지막 날짜가 최신이어도 개별 보유 종목의 exact close가 빠질 수 있었다.
2. 동일 거래일 재실행이 첫 forward overlay를 자기 자신의 prior-rank 기준으로 사용해 불필요한 immutable conflict를 만들 수 있었다.

수정 후에도 포트 종목, 비중, 현금, 점수, 순위, 매수·매도 기준은 바뀌지 않는다. 이번 작업은 CAGR/MDD 후보를 신뢰성 있게 판정할 forward 증거가 매일 누적되도록 만드는 운영 기반 보강이다.

## 확인된 실제 상태

### 최신 forward archive

GitHub Actions run `29387336555`는 성공했고 다음 상태를 만들었다.

- decision date: `2026-07-14`
- signal observations: `154`
- decision dates: `3`
- unique tickers: `74`
- distinct true-forward tickers: `14`
- completed 63D true-forward outcomes: `0`
- 판정: `UNDERPOWERED`

따라서 forward lane은 정상적으로 전진했지만 아직 CAGR/MDD 변경 근거는 아니다.

### operating refresh 실패

GitHub Actions run `29388570121`은 `missing exact completed-session close for AMAT on 2026-07-14`로 차단됐다. 집계 manifest의 최대 날짜는 2026-07-14였지만 이는 다른 종목의 최신 날짜였고, AMAT 캐시는 7월 14일 exact bar를 포함하지 않았다. 기존 캐시 빌더는 종목별 exact-date 계약을 확인하지 않아 앞 단계에서 `completed`로 표시했다.

### 동일 세션 ledger 충돌

run `29303018492`가 2026-07-13 첫 관측 60건을 정상 기록한 뒤 run `29304288757`이 같은 decision date를 다시 계산했다. 두 계산의 실제 신호와 현재 순위는 같았지만 두 번째 실행이 첫 결과를 prior baseline으로 사용하면서 `prior_free_data_selection_rank`와 rank delta만 바뀌었다. ledger는 기존 이벤트를 수정하지 않고 충돌을 차단했으므로 데이터 손상은 없었다.

## 적용한 보강

### 종목별 exact close

`build_replay_price_cache.py`에 `--required-session-date`를 추가했다.

- market-session gate가 선택한 날짜의 bar가 모든 선택 종목에 있는지 검사한다.
- batch 응답에서 최신 bar가 누락된 종목만 한 번 개별 재요청한다.
- 그래도 누락되면 `blocked_missing_required_session`으로 실패한다.
- manifest에 누락 전·후 종목과 retry 결과를 남긴다.

실제 AMAT 단일 종목 검증은 2026-07-14 exact bar를 확보했고 `required_session_missing_after_count=0`, `status=completed`로 끝났다.

### 동일 세션 멱등성

earnings-estimates workflow는 durable archive에서 복원한 overlay의 decision date가 현재 completed session과 같으면 새 overlay를 계산하지 않고 첫 snapshot을 그대로 재사용한다. 이후 ledger는 기존 신호를 duplicate/no-op으로 처리하면서 새로 도달한 next-close와 forward outcome만 추가할 수 있다.

## 검증

- `replay_price_cache_smoke: PASS`
- `earnings_estimate_workflow_rotation_smoke: PASS`
- `free_data_forward_paper_ledger_smoke: 17/17 PASS`
- `workflow artifact smoke passed`
- Python compile: PASS
- 두 workflow YAML parse: PASS
- `git diff --check`: PASS

## CAGR/MDD 강화와의 관계

현재 generated-book 기준선은 그대로다.

| 포트 | 현재 CAGR | 현재 MDD | 목표까지 남은 차이 |
|---|---:|---:|---:|
| Main | 34.4032% | -25.3619% | CAGR +0.5968%p, MDD +0.3619%p |
| Concentrated | 49.0971% | -22.9552% | CAGR +0.9029%p, MDD 통과 |

과거 진단상 broad cash 투입, generic exit-delay, 기존 execution/position-risk overlay는 개선 근거가 없었다. 현재 가장 가까운 유효 경로는 다음 두 가지다.

1. 외부 PIT estimate/guidance source가 50-security/200-event 계약과 source screen을 통과하면 단 하나의 fixed-book A/B를 연다.
2. 외부 source가 없으면 이번에 보강한 forward archive로 개별 종목 위험과 selection overlay의 21D/63D 결과를 누적한 뒤 사전등록된 gate에서만 판단한다.

이번 수정은 두 번째 경로가 AMAT 같은 단일 종목 누락이나 같은 날짜 재실행 때문에 멈추는 것을 방지한다. 하지만 표본이 아직 부족하므로 threshold, cash floor, cap, stop 또는 종목 비중을 조정하지 않았다.

## 다음 자동 실행

2026-07-15 미국 정규장은 2026-07-16 05:00 KST에 완료된다.

- after-close daily: 명목상 07:45 KST
- earnings/forward archive: 명목상 09:35 KST
- operating selection refresh: 명목상 10:15 KST

GitHub scheduled job은 지연될 수 있다. 다음 완료 run에서 2026-07-15 exact close, 동일 세션 no-conflict, AMAT 포함 종목별 close coverage를 확인한 뒤에만 최신 포트·홈페이지 자료가 유효하다고 판정한다.

fullrun, production/live trading, 포트 변경은 수행하지 않았다.
