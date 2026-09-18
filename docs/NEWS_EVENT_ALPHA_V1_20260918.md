# News Event Alpha V1 — 역사 백필 + Forward 누적 연구 시스템

Status: RESEARCH_ONLY  
Date: 2026-09-18  
Target: wscha231/r1000-quant-engine

## 목적

Theme Radar가 발견한 신규 사업 관계와 뉴스/공시 사건을
**당시 알 수 있었던 근거 → 가격 확인 → 미래 SPY 초과수익**으로 연결해 반복 검증한다.

사전 가설:

> 공식 사업근거 + DIRECT 노출 + 발표 후 5~20 세션 상대강도 + 동종주 breadth 확대 조합은
> 그 확인 시점 이후 1~6개월 SPY 초과수익을 예측하는가?

이 모듈은 가설을 검증하고 RESEARCH_CHALLENGER_REVIEW_ELIGIBLE 제안까지 만들 수 있지만
selector, target book, portfolio, 주문, champion을 변경할 권한은 없다.

## 기존 시스템 재사용

- research/theme_etf_runtime_v1: LINK/UNLINK, 미국 COMMON/ADR 자격, base-universe UNION.
- tools/run_sec_submissions_collector.py: accepted_at/available_from 기반 SEC filing PIT metadata.
- tools/run_free_data_forward_paper_ledger.py: 정확한 NYSE 세션과 pending forward outcome 계약.
- docs/RESEARCH_DATA_ACCESS.md: Drive verified catalog/execution receipt가 실제 데이터 사용 권한의 기준.
- Issue #433: Theme Radar 설계/패키지 인수인계이며 실시간 운영 완료 증거가 아니다.

## 사건 단위

한 economic_event_id를 통계 표본 1개로 본다. 같은 보도자료 전재, 동일 wire 기사,
같은 경제 사건 반복보도는 별도 성공사례로 세지 않는다.

핵심 필드:

- event_id / economic_event_id / security_id / issuer_id
- available_at: 실제 이용 가능해진 timezone-aware timestamp
- event_type
- role: DIRECT / ENABLER / INDIRECT / NARRATIVE
- source_tier: OFFICIAL / PRIMARY / TIER1_NEWS / OTHER
- official_evidence
- business_relation_new
- economic_value_confirmed
- economic_amount_usd
- economic_amount_kind: GUARANTEED / EXPECTED_DELIVERIES / CEILING 등
- theme_peer_ids
- independent_source_groups
- dilution_risk / cashflow_risk / balance_sheet_risk
- sample_origin: HISTORICAL_BACKFILL / FORWARD_SHADOW

ceiling을 backlog나 매출로 바꾸지 않는다.

## 시간축 / 누수 방지

명시적 NYSE session + market_close_utc 표를 입력받는다.

- 장 마감 전 이용 가능: 해당 세션 종가까지 확인한 뒤 T0.
- 장 마감 후 이용 가능: 다음 실제 NYSE 세션이 T0.
- 휴장/주말을 단순 달력일로 추정하지 않는다.

T0 이전까지만 pre_rs20/pre_rs60을 계산한다.

Checkpoint는 T0 / T+5 / T+10 / T+20이다.
각 checkpoint에서 post-event RS와 peer breadth를 다시 계산한다.

중요: T+5 RS를 feature로 사용하면 미래수익은 T+5 종가부터 새로 계산한다.
T+5 정보를 사용하고 T0→T+21 수익을 label로 쓰는 누수를 허용하지 않는다.

## Forward horizon

각 checkpoint 이후 실제 세션 기준:

- 5: 약 1주
- 10: 약 2주
- 21: 약 1개월
- 63: 약 3개월
- 126: 약 6개월
- 252: 약 1년

저장값:

- absolute total return
- SPY return
- SPY excess return
- max favorable excess excursion
- max adverse excess excursion
- exact end session
- RESOLVED / PENDING_HORIZON / PENDING_PRICE_GAP

정확한 미래 세션 가격이 없으면 이후 가격으로 대체하지 않는다.

## 비교 arm

1. ALL
2. OFFICIAL_DIRECT
3. OFFICIAL_DIRECT_SUBSTANCE
4. CONFIRMED_COMBO

CONFIRMED_COMBO는 T+5/T+10/T+20에서:
official DIRECT + 경제적 실체(금액 또는 신규 관계) + 양의 post RS + peer breadth >= 50%.

이 구조가 GNRC형 사건과 PSQL형 사건을 분리한다.

- GNRC형: 공식/DIRECT/경제근거/신규관계/가격·breadth confirmation.
- PSQL형: 기술 스토리는 있으나 상업금액·직접노출·가격확인 부족.

## 영향력 표현

사건마다 임의의 +15% 효과를 부여하지 않는다.
같은 arm의 과거 실제 분포에서 구간별 영향력을 계산한다.

각 checkpoint × horizon × arm:
- n
- distinct issuers / years
- mean / median SPY excess
- positive excess hit rate
- +5%p / +10%p hit rate
- q25 / q75
- mean 95% CI

따라서 향후 화면은 “63일 예상 +12%” 같은 단정값보다
“유사 사건군 63세션 median excess X, IQR [Y,Z], n=N” 형태를 기본으로 한다.

## 처음 한 번의 역사 백필

기본 window는 최근 5년으로 한다. 이후 7~8년 sensitivity를 별도로 할 수 있다.

우선 데이터:
1. SEC 8-K/6-K 및 첨부 IR — accepted_at/available_from 기준.
2. 회사 IR/정부 공식 archive — 당시 publication timestamp 검증 시.
3. 승인된 역사 뉴스 corpus — 라이선스/보존권한과 source-family dedupe가 검증될 때만.

현재 연결 조사에서는 다년 연속 뉴스 기사 corpus가 이미 검증됐다는 증거를 찾지 못했다.
따라서 검색 결과 몇 개를 과거 전체 뉴스 corpus로 가장하지 않는다.
Drive current verified catalog/execution receipt에서 실제 SEC/가격/NYSE coverage를 확인한 뒤
bounded backfill을 실행해야 한다.

과거 백필은 empirical prior이며 그것만으로 selector 승격하지 않는다.
chronological OOS/walk-forward, delisted/실패기업, 당시 universe, ADR eligibility,
event type/regime/market-cap/liquidity 안정성을 별도 검증한다.

## 이후 누적 운영

1. 신규 뉴스/공시 → normalized economic event
2. immutable event_ledger.jsonl append
3. T0 feature 계산
4. T+5/T+10/T+20 confirmation
5. 5/10/21/63/126/252 session outcome resolve
6. cohort impact summary 갱신
7. 보고서는 Top 5만 기본 노출, 전체 사건은 ledger 보존

기존 economic_event_id payload가 바뀌면 fail closed한다.

## 승격 제안 gate

기본 checkpoint는 T+5 CONFIRMED_COMBO.

HISTORICAL_BACKFILL과 FORWARD_SHADOW 각각:
- resolved 21D >= 200
- resolved 63D >= 100
- resolved 126D >= 50
- distinct issuers >= 25
- historical distinct years >= 3
- 21/63/126 median SPY excess > 0
- historical/forward 63D mean 95% CI lower bound > 0

모두 통과하면 RESEARCH_CHALLENGER_REVIEW_ELIGIBLE.

그 상태에서도 항상:
- manual_review_required=true
- selector_eligible=false
- automatic_promotion_allowed=false
- production_activation_allowed=false

실제 승격은 별도 Experiment → WF/OOS → portfolio challenger → shadow/paper → 수동 승인 절차다.

## CLI

tools/run_news_event_alpha_v1.py

역사 백필 예:
    python tools/run_news_event_alpha_v1.py \
      --events historical_events.jsonl \
      --prices total_return_prices.csv \
      --market-sessions nyse_sessions.csv \
      --mode HISTORICAL_BACKFILL \
      --benchmark SPY \
      --output-dir outputs/news_event_alpha_v1/backfill_5y \
      --source-commit <exact_sha> \
      --data-receipt-sha256 <verified_receipt>

Forward 누적:
    python tools/run_news_event_alpha_v1.py \
      --events todays_events.jsonl \
      --existing-ledger outputs/news_event_alpha_v1/latest/event_ledger.jsonl \
      --prices total_return_prices.csv \
      --market-sessions nyse_sessions.csv \
      --mode FORWARD_SHADOW \
      --output-dir outputs/news_event_alpha_v1/latest

출력:
- event_ledger.jsonl
- checkpoint_features.csv
- forward_outcomes.csv
- impact_summary.csv
- challenger_proposal.json
- top_current_events.json
- manifest.json

## 이번 변경의 경계

하지 않는 것:
- workflow/scheduler 활성화
- Drive accepted-state mutation
- 실제 historical backfill 완료 주장
- universe 자동 편입
- selector 활성화
- target/portfolio 변경
- broker/paper ledger mutation
- 주문
- fullrun
- champion/model 자동 승격

첫 실제 5년 백필은 verified current Drive catalog/execution receipt와 해당 기간
SEC/가격/NYSE-session coverage를 확인한 후 별도 bounded research execution으로 수행한다.
