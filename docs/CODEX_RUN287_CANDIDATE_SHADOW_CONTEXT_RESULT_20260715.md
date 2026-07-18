# Run287 외부 후보 shadow context 결과 — 2026-07-15

## 결론

2026-07-14 완료 종가를 기준으로 현재 989종목 문맥 밖의 후보 14개에 대해 **비순위·비선정 research shadow context**를 만들었다. 결과 상태는 `READY_PARTIAL_CANDIDATE_SHADOW_CONTEXT_NONRANKING`이다.

이 결과는 후보가 왜 기존 유니버스와 포트에 없었는지를 조사하기 위한 중간 산출물이다. 모델 예측, 종목 순위, 포트 편입, A/B, CAGR/MDD 재계산을 허가하지 않는다.

## 측정 결과

| 항목 | 결과 |
|---|---:|
| 후보 수 | 14 |
| 2026-07-14 exact-close 기술지표 | 14/14 |
| exact accepted-time 재무 panel | 12/14 |
| technical-only | 2/14 |
| frozen model feature 수 | 238 |
| raw model feature 유한값 비율 | 32.0228% |
| scaler 적용 후 유한값 비율 | 100% |
| missing-neutral 위반 | 0 |
| 미래 가격 행 | 0 |
| 미래 재무 행 | 0 |
| same-session macro feature | 0 |

스케일 후 100%는 누락값이 frozen scaler의 neutral 값으로 안전하게 변환됐다는 뜻일 뿐이다. 원천 데이터가 100% 확보됐다는 뜻이 아니며, 32.0228% raw coverage로 후보를 기존 989종목과 공정하게 순위 비교할 수 없다.

## 후보별 상태

| 상태 | 종목 | 설명 |
|---|---|---|
| partial technical + fundamental | AEIS, BELFB, CAMT, CLS, CRWV, FN, FORM, IESC, MOD, NBIS, RMBS, TSEM | exact-close 기술지표와 accepted-time Companyfacts panel 연결 |
| technical only | 000660.KS | 미국 SEC issuer proxy를 한국 상장 종목의 home-market filing으로 대체하지 않음 |
| technical only | SKHY | 2026-07-10 이후 가격 3개 bar만 존재하고 listing-specific statement가 아직 없음 |

`CRWV`, `NBIS`, `SKHY`는 짧은 상장 이력 때문에 장기 기술지표 일부가 구조적으로 없다. 이는 수집 실패가 아니라 상장 전 데이터가 존재하지 않는 경우다.

## Macro 차단

동일 2026-07-14 기준 macro sidecar를 새로 시도했으나 상태는 `BLOCKED_MACRO_CONTRACT`였다.

- 요구 종가: `2026-07-14`
- 실제 macro engine row: `2026-07-13`
- blocker: `macro_row_not_exact_close:2026-07-13!=2026-07-14`
- market component: 9/9
- FRED component: 13/13
- network request: 12/24 budget

따라서 하루 낡은 macro row를 후보에게 붙이지 않고 모든 macro model feature를 neutral로 남겼다.

## 안전성 계약

- `available_from <= observed_at`인 exact accepted-time 자료만 사용
- future price/fundamental row 0
- 원시 누락은 NaN 유지, frozen scaler 단계에서만 neutral 처리
- model scoring, ranking, selector, backtest, fullrun 미실행
- target, weight, cash, order, universe, operating portfolio 미변경
- PIT membership과 delisted outcome이 없으므로 7년 CAGR/MDD 증거로 승격 금지

## 다음 게이트

1. 989종목 기준 분포를 오염시키지 않는 외부후보 비교 방법을 먼저 확정한다.
2. same-session macro, benchmark, sector/industry와 cross-sectional comparable transform을 보완한다.
3. `000660.KS`는 DART/home-market 경로, `SKHY`는 신규 ADR의 listing-specific 재무 이력 경로를 별도 설계한다.
4. 다섯 advisory-selected/operating-book divergence의 exact selector input·persistence 원인을 복원한다.
5. 위 작업 전에는 14개 후보의 점수·순위·포트 편입을 만들지 않는다.

## CAGR/MDD와의 관계

이번 작업으로 Main 34.4032% / -25.3619%, Concentrated 49.0971% / -22.9552% 기준선은 변하지 않았다. 개선된 것은 후보 탐색의 누락 원인을 분리하고 미래 연구 표면을 넓힌 것이며, 성과 개선을 주장할 단계는 아니다.

## 증거

- `outputs/run287_candidate_shadow_context_20260715_close_20260714/manifest.json`
- `outputs/run287_candidate_shadow_context_20260715_close_20260714/report.md`
- `outputs/run287_candidate_shadow_context_20260715_close_20260714/ticker_feature_coverage.csv`
- `outputs/run287_macro_sidecar_20260715_close_20260714_shadow/manifest.json`
- `tools/build_run287_candidate_shadow_context.py`
- `tests/run287_candidate_shadow_context_smoke.py`
