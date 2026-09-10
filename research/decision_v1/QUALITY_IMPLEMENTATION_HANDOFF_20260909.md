# [PROJECT_HANDOFF] Quality evidence V1 구현 — 2026-09-09

**첫 코드·fixture·실제 제한 표본 연결을 완료. 전체 투자 의사결정 시스템 완성 아님.**
RESEARCH_ONLY / OPT_IN / PORTFOLIO_UNWIRED / orders_allowed=false.

## 실제 변경

#401의 계획을 #400의 실제 `evaluate_security`/`scenario_price`에 연결하는 신규 H2다.
기존 H1/H2 파일·수치 설정·브랜치는 수정하지 않았다. 신규 모듈은
`quality.py`(주장/근거/검토), `quality_bridge.py`(기존 가치평가 adapter),
`quality_index.py`(독립 검토·실행 인덱스)다. 새 테스트·재현 helper·계약과
한정된 실제 캡처/실행 snapshot을 추가했다. 자동 LLM 추출기는 만들지 않았다.

- 기본 미국 HEAD: `8ccbd478e05ff34c6dd70e410be0cae793c9863e`.
- 의존 H1 #399: `1c5e1c0eaeb7885d35bd6713aba93ff931460c81`.
- 직접 의존 H2 #400: `52b119ab653016bb1706cf4ff706890e820e131d`.
- 계획 #401: `14d3ad6ecc3a43e4672ebfc79abdf3cb730ce67f`.
- KR #2: `3c40210b8675267121d7f40f3dcd8d158720a4e8` (이번 KR 변경 없음).
- 새 코드 commit: `ce17c84aa3d1adf54ccfc421d1be7a5ede2314d6`.
- #403/#404 역발상 작업과 #401의 수작업 투자 댓글은 확인했지만 가져와 혼합하지 않았다.

## 달라진 판단 흐름

가격이 없으면 기존 함수는 조기 반환한다. 새 adapter는 그 전에 기업 근거를
심사하므로, 가격·자금 부족과 무관하게 확인된 주장/반론을 보존한다.
`company_quality=pass` 단독 입력은 기업 판단 근거가 아니다. 숫자를 임의로 채우거나
같은 근거로 마진·멀티플·품질점수를 중복 올리지 않는다. 원문 안의 지시는 데이터다.

근거와 숫자의 연결은 직접 수정하는 자동 점수가 아니다. 사전 제시된 baseline과
현재 시나리오의 변수·방향·기간·통화·범위를 대조한다. 동일 가격에서의 반사실 계산은
기존 V1 함수를 호출한다. 합성 테스트에서 Base margin 0.10→0.11, 나머지 고정 시
목표가 차이 2.4를 확인했다. 이는 실제 종목 전망이나 과거 계좌 변화가 아니다.

## 실제 표본 실행

캡처 cutoff: **2026-09-08 15:59:56 UTC / 2026-09-09 00:59:56 KST**.
이는 주가 종가 cutoff가 아닌 웹 근거 관찰시점이다. 정밀 공개시각을 임의로 만들지
않고 이용 가능 시점을 보수적으로 이번 관찰로 둔다.

| 대상 | 제한된 원문 대사 + 모델 검토 | 해석 경계 | 회사 전체/가격/비중 |
|---|---:|---|---|
| EME | 3 claims | RPO·FY2026 가이던스·FIX 비교. RPO≠현금; FY2026≠향후12개월 | 미완료/차단/차단 |
| NVDA | 2 claims | 회사의 분기 매출·양산 발표. 독립 성능/고객 경제성 검증 아님 | 미완료/차단/차단 |
| SK하이닉스 | 2 claims | HBM4 출하 발표·자사주 계획. 계획≠완료 소각 | 미완료/차단/차단 |

원문: EME 공식 IR, NVIDIA 공식 IR, SK hynix newsroom, 비교후보 FIX 공식 IR.
정확한 URL·발췌·위치는 `quality_evidence_20260909/pilot_capture.json`에 있다.
일부는 웹 검색결과의 공식 페이지 발췌만 확보했다. 전체 HTTP 원문/공시 바이트 인증은
아니다. 해시는 실제 보존한 짧은 UTF-8 캡처를 검증한다. 모델 검토 receipt는 독립
리뷰·서명 인증·역사적 PIT 증명이 아니다. 회사 주장의 진실성과 장기 우위는 추가
검토가 필요하며 일곱 축의 미확인 질문을 전부 남겼다.

EME의 매출 상향 방향은 FY2026 구간에만 연결했다. 새 12개월 매출·목표가·확률은
입력하지 않았다. SK의 소각 계획으로 희석주식수를 줄이지 않았다. FIX의 backlog는
경쟁 비교의 시작점일 뿐, EME 점유율 하락 증거로 처리하지 않았다.

실제 명령은 `quality_evidence_20260909/validation_receipt.json`에 있다.
helper의 예상 exit=2와 실제 exit=2가 일치했다. 별도 프로세스 두 번의 **7개 산출물
바이트 해시가 모두 동일**했다. 이 실행은 H1 가격/재무 admission의 재실행이 아니다.
기존 0/3 투자 입력을 통과시킨 것이 아니며, 새 실제 투자순위·비중도 없다.

## 테스트·환경과 남은 gate

신규 합성 테스트 **47/47**, `python -I`와 `python -I -O` 각각 통과.
확인된 기존 data.py/valuation.py/__init__.py Git blob과 로컬 재구성 바이트가 일치한다.
사용자 체크아웃은 이 환경에 없고 GitHub git DNS 접근도 실패했다. 검증된 부분 소스
스냅샷에서 작성/검사 후 격리 bare object store의 명시적 index로 staging했다.
새 git worktree나 사용자 파일 변경 없이 동일 blob만 Git object API로 게시했다.
로컬 patch tree는 전체 저장소 tree가 아니다. 새 PR의 정확한 변경 파일 비교가 필요하다.

현재 환경에는 upstream이 요구하는 pandas_market_calendars 5.4.0이 없고 tzdata도
2026.2로 요구 2026.3과 다르다. 이번 테스트는 그 거래일/보고일 경로를 호출하지 않는다.
기존 전체 42-test H2/39-test H1, Windows, protected Tier-1 등록, 전체 checkout CI는
이번에 수행하지 않았다. 과거 #400의 두 CI green을 새 테스트의 CI 실행으로 쓰지 않는다.
정확한 새 HEAD의 독립 리뷰·원래 launcher/export/portfolio 통합이 남아 있다.

Financial Datasets EME TTM 조회는 잔액 0달러로 한 번 실패했다. 재호출·키 생성·구매는
하지 않았다. 기존 수집기의 현재가/기업행사/TTM·순부채·주식수·FCF, 12개월 시나리오,
위험/FX/자금을 이 구현으로 모두 연결했다고 주장하지 않는다.

직접 읽은 검토 thread는 H1 6개, H2 3개가 미해결이었다. 후속 실행은 다시 확인한다.
H1에는 게시 불일치 잔여물·source URL/session·feed 표기·thesis 타입·KR 식별 타입,
H2에는 신뢰 Git executable·비용 차감 후 NAV/현금·FX/자금 오류 분리 검토가 남았다.
이 신규 H2 PR에서 해당 H1 또는 기존 포트 계산 문제를 수정했다고 하지 않는다.

## 다른 채팅의 시작점

`research/decision_v1/RESEARCH_INDEX.json`을 **이 구현 PR의 정확한 HEAD**에서 읽는다.
각 회사의 latest_reviewed_snapshot은 현재 모델의 **partial** 검토이며 independent=false다.
latest_execution_manifest는 투자 차단 실행이다. 최신 성공 포트가 없으므로 성공 포인터는
null이다. artifact 경로는 인덱스를 담은 commit에 상대적이고 source_sha는 실행 코드다.
기본 브랜치 구현/승인/계좌로 해석하지 않는다. 기존 snapshot을 덮어쓰지 않는다.

## 다음 작업·중단 조건

1. 전체 checkout에서 새 테스트의 protected 등록과 exact-head 독립 리뷰.
2. 담당 H1/H2 범위에서 남은 반례 수정·검증; 새 quality adapter의 downstream 연결.
3. EME 한 곳부터 최근 재무·가격과 회사 핵심 축 및 실질적 경쟁 근거를 완결하고
   실제 12개월 시나리오를 출처·가정과 연결. 그 후 NVDA/KR 표본과 5+2로 확장.

필수 자료 부족은 해당 투자 결정을 차단한다. 원문 실패·미래정보·중복 가점·기존
source SHA 변화가 발견되면 영향 범위를 재검증한다. 5+2 숫자를 채우기 위한 허위
자료나 자동 확률은 금지한다. 비용/FX 검토 전 portfolio ready를 켜지 않는다.

구현 첫 slice: 완료. 제한 실제 주장 연결: 완료. 전체 정성/원자료/투자 제안: 미완료.
OOS/성과/MDD: 미검증. 병합/fullrun/migration/schedule/promotion/장부/주문: 변경 없음.
확신도: 수행한 제한 테스트와 캡처 대사 범위 높음, 일반 예측력·투자성과 미평가.
