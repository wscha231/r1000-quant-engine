# Run287 전체 시스템 기반 리뷰 — 2026-07-27

## 결론

현재 CAGR/MDD가 개선됐다고 말할 수 없다. fullrun을 실행하지 않았고, 기존 성과 측정에는 미래 라벨 성숙시점, OOS 독립성, 벤치마크 forward-label 결합, 자동 승격 경로의 결함이 있었다. 이번 변경은 성과를 높이는 전략 변경이 아니라, 앞으로의 개선치를 믿을 수 있게 만드는 F0 기반 교정이다.

교정 후 첫 공식 fullrun은 기존 수치의 단순 연장이 아니다. 새 엔진 캐시 버전과 동일한 source manifest·target-book hash·비용·현금·lifecycle 계약으로 champion을 처음부터 다시 측정하는 corrected rebaseline이다. 별도 승인 전에는 실행하지 않는다.

## 현재 성과 기준의 불일치

| 근거 | Main CAGR / MDD | Concentrated CAGR / MDD | 문제 |
|---|---:|---:|---|
| canonical fixture lock | 34.4032% / -25.3629% | 49.0968% / -22.9560% | 종료일이 2026-01-10이고 Concentrated 필터가 N=5 |
| promotion evidence | 34.4032% / -25.3629% | 49.0968% / -22.9560% | as-of 2026-07-10이지만 fixture 값과 동일 |
| P3 crisis baseline | 33.5352% / -25.6527% | 47.6898% / -23.2216% | 다른 replay/metric identity |

따라서 Main 목표까지의 단순 격차는 CAGR +0.5968%p, MDD +0.3629%p이고 Concentrated는 CAGR +0.9032%p지만, corrected rebaseline 전에는 이 격차도 공식 최적화 기준으로 사용할 수 없다.

## F0에서 교정한 사항

1. 각 1·3·6·12·24·36개월 종목 수익과 벤치마크 수익에 실제 종료 거래일을 저장한다.
2. 양의 가중치를 가진 모든 horizon과 excess-return 벤치마크가 완성되고, 월별 분류 target에 사용되는 전체 cross-section이 관측된 뒤에만 학습한다.
3. `label_available_at < decision_date`를 walk-forward와 latest scoring 모두에 적용한다.
4. latest scoring의 미성숙 라벨 우회 fallback을 제거했다.
5. benchmark forward merge의 `_x`/`_y` 충돌을 제거했다.
6. OOS2를 2023-01-01~2024-06-30, OOS를 2024-07-01~현재로 분리하고 겹치면 실패시킨다.
7. 자동학습은 통과 여부와 관계없이 proposal-only이며 active champion 파일을 쓰지 못한다.
8. 엔진 캐시 버전을 올려 과거 모델·feature store 재사용을 차단한다.

## 전 시스템 리뷰

- 데이터/PIT: SEC accepted time 계층은 존재하지만 모든 소스가 이중시점 계약으로 통일되지는 않았다. 가격 forward label의 관측 종료일은 이번에 보완했다.
- feature/score: 상대강도·펀더멘털·실적·소유권·매크로 기능은 많지만, 여러 feature의 추가가 반복 실험 수와 연결된 통계적 벌점으로 이어지지 않는다.
- sector/leadership: PR #339의 기능은 research-only 탐지 계층이다. PR #336의 동일 계층을 포트폴리오 재구성에 적용한 결과는 Main 23.82%/-36.23%, Concentrated 16.84%/-46.69%로 기각됐다. 탐지 tape는 유지하되 같은 포트폴리오 변환은 반복하지 않는다.
- portfolio/cash: Main과 Concentrated의 목표 종목 수 계약이 산출물마다 다르고, 높은 평균현금의 단일 원인 귀속이 아직 완결되지 않았다.
- crisis/reentry: 고정 위기정책은 Main MDD를 줄였지만 CAGR을 크게 훼손했고 cash trap이 발생했다. Concentrated는 MDD도 소폭 악화했다.
- execution/capacity: 고정 bps 중심이며 half-spread, ADV 참여율, 변동성 시장충격, 0.1/0.5/1% ADV 용량 계약이 공식 promotion metric에 아직 통합되지 않았다.
- ledger/operations: durable paper 계층과 close gate는 강화됐지만, 2026-07-27 세션은 아직 완료된 NYSE 종가가 아니므로 catch-up 대상이 아니다.
- promotion/learning: 자동 승격은 이번에 차단했다. DSR, PBO, White Reality Check/SPA가 코드화된 fail-closed gate는 아직 없다.

## CAGR/MDD 개선 순서

1. corrected canonical rebaseline: 별도 fullrun 승인 후 한 번만 실행한다.
2. 체결비용·운용용량 계층: fixed 25/50/100bps와 별도로 spread/ADV/impact를 산출한다.
3. 다중검정 gate: 모든 시도 수를 ledger에서 읽어 DSR/PBO/SPA를 계산한다.
4. 단 하나의 causal challenger만 등록한다. 같은 sector reconstruction, broad cash floor, stop-grid, 13F/Form 4 tilt 등 기존 기각안을 이름이나 임계값만 바꿔 반복하지 않는다.
5. Full/OOS/OOS2, regime leave-one-out, block bootstrap, top-winner 제거, 비용/용량을 모두 통과한 경우에만 60-session forward 제안을 시작한다.

세부 기계판독 계약은 `docs/run287_system_foundation_review_20260727.json`에 고정했다.
