
# GitHub·ChatGPT 자동화 재점검 및 정리 — 2026-09-12 19:43 UTC / 09-13 04:43 KST

### 이번에 실제로 변경한 ChatGPT 작업
연결된 예약은 총 5개이며 이 중 R1000 관련 4개, ETH 별도 프로젝트 1개다. R1000 작업 4개의 설정을 대조했다.

| 작업 | 조치 | 현재 역할 |
|---|---|---|
| PR #390 상태 알림 | **비활성화 완료** | 2026-09-03 이미 병합된 PR의 감시 종료 |
| AI 인프라 일일 연결 점검 | **이름·지시문·일정 수정 완료** | R1000 데이터·후보 변화 점검. 매일 KST 22시경 유연 실행. 최신 실행/실제 자료일/Drive 영수증·결측 확인, 중요한 변화만 알림 |
| AI 인프라 투자순위 점검 | **지시문 수정 완료** | 토요일 KST 10시경 주간 심층 분석 유지. 기존 검증 자료 재사용, 정성·거시·RS 연결, 불필요한 자동화 점검 |
| 후보주 발굴·진입 점검 | 기존 비활성 상태 유지 | 예전 고정 가중치·진입 규칙의 별도 반복 실행을 재개하지 않음 |

ETH 갱신 복구 점검은 다른 프로젝트의 독립된 역할이라 변경하지 않았다. 전체 활성 예약은 4개에서 3개로 줄었으며 R1000은 일일 점검과 주간 분석 2개가 활성 상태다. 도구가 설정 저장 성공을 확인했다. 수정 후 첫 예약 실행 성공까지 확인한 것은 아니다.

일일 점검은 정상·무변화 때 알리지 않으며, 같은 장애는 원인·상태·필요 조치가 바뀔 때 알린다. 지속 장애의 반복 요약은 확인 가능한 이전 기록을 기준으로 주 1회 이내로 제한한다. 비교 기록이 없으면 첫 관측이라고 표시한다. 주간 유지보수는 R1000의 완료된 일회성 감시·명백한 중복만 근거를 남겨 비활성화하도록 했다. 자료가 안 바뀌었다는 이유만으로 핵심 수집기나 장기 원본을 제거하지 않는다.

### GitHub 현황: 파일 43개, 정기 실행 정의 22개
master e39d4f5338b186acdd7753a6007dfbea92211a51의 workflow 43개를 전부 읽었다. schedule이 있는 파일 22개, cron 정의 25개다. 이 수는 GitHub 관리 화면의 enabled 개수와 같다고 단정할 수 없다. 연결 도구가 workflow 관리 목록 endpoint를 지원하지 않아 소스와 실제 schedule 실행 기록을 대조했다.

| workflow | 판단·다음 조치 |
|---|---|
| agent_board_manual | **정기 실행 제거 패치**. 현재 committed full-rebuild 결과를 매일 재정리하는 역할. 수동 진단은 유지 |
| daily_autolearning_scan | **정기 실행 제거 패치**. 고정 latest 경로로 여러 과거 replay를 반복. 새 연구는 데이터·실험 ID를 고정한 수동 경로 |
| live_extension_daily | **정기 실행 제거 패치**. 실제 09-12 실행이 06-23 포트/19행을 기준으로 81일 연장. 현재 accepted 포트로 오인하기 쉬움 |
| after_close_daily | 유지. 가격/거시/ETF/스캐너 수집과 낡은 점수 소비를 분리하고 각각 현재성 표시 |
| daily_crisis_monitor | 유지·보완. 복원/동기화 실패를 숨기는 경로와 오래된 local fallback의 상태를 드러내도록 수정 필요 |
| daily_operating_selection_refresh | 유지하되 무작정 재실행 금지. accepted risk-outcome 복구가 막혀 가격/판단까지 도달하지 못함. 가벼운 사전 검사로 반복 비용 줄이기 |
| free_data_daily_update | 유지·분리. 정기 SEC companyfacts는 false이고 매일 proxy backtest도 수행. 원본 수집과 반복 연구를 분리 |
| data_readiness_preflight | 유지·통합 대상. free-data와 중복 복원/정적 감사 줄이고 동일 catalog 기준으로 검사 |
| earnings_estimates_daily | 유지. job 성공과 실제 estimates collector 차단/부분 coverage 구분 |
| sec_form4_daily_refresh | 유지. 공시 accession·접수시각 기준 증분 수집과 중복 방지 |
| sec_13f_quarterly_refresh | 유지. 보고 분기·공시일·정정 버전 기준으로 관리 |
| smart_money_top30_refresh | 유지. 정상 SEC 원본을 소비하게 복원 경로 확인; 과거 인증 실패만으로 폐기하지 않음 |
| sec_13f_manager_reselection | 유지·의존 자료 확인. 매니저 변경과 신규 투자 신호 승인 구분 |
| etf_holdings_monthly_refresh | 유지. 실제 holdings 기준일·구성 변경·중복 수집 검사 |
| adr_candidate_monthly | 유지. ADR 증권과 발행기업·상장/통화/ADS 변경 이력 연결 |
| weekly_data_refresh | 유지. 실제 변경된 원본만 수집하고 결과/commit 실패까지 보고 |
| quarterly_auto_learning | 제안 기능 유지. 새 데이터/실험 식별자로 중복 평가를 막고 모델 승격은 리뷰 경로 |
| monthly_research | 후속 정리 대상. 실제 소비자·입력 변경 여부를 확인해 수동/변경 시 실행으로 축소 |
| unified_monthly | 후속 정리 대상. 현행 Run287 accepted 운영과 역할·출력 중복을 확인한 뒤 통합 |
| layer4_monthly_swap | 후속 정리 대상. 오래된 fallback 포트·별도 swap 기록을 현재 운영과 혼동하지 않게 분리 |
| run287_daily_research_monitor | 핵심 상태판으로 유지. 녹색 job과 데이터 사용 가능 상태를 별도 표시 |
| pages_deploy | 유지. 이미 수집/monitor 완료 event와 cron fallback이 존재. 같은 입력 재배포는 hash 기준 생략 검토 |

나머지 21개 파일은 수동/PR/이벤트 기반이다. CI·리뷰·안전 검사·수동 복구까지 불필요한 것으로 간주해 삭제하지 않는다. 감사 당시 새 장기 저장 workflow는 PR420에 있었고 master에는 없어 위 43개에 포함되지 않았다. 현재 master 기준으로 재구성한 PR423에서 통합을 진행한다.

세 수동 전환 대상은 다른 workflow의 이름 기반 참조가 없음을 43개 소스에서 확인했다. 이것은 모든 Python 소비자까지 없다는 증명은 아니므로 원본 코드·수동 실행·이력은 유지하는 변경으로 제한한다.

### 실행 상태가 보여준 실제 문제
- [일일 연구 모니터 34693116190](https://github.com/wscha231/r1000-quant-engine/actions/runs/34693116190)는 job success이지만 출력은 ATTENTION_REQUIRED, expected_us_session=2026-09-11, current_investment_ranking_ready=false, current_engine_scores_ready=false다. 수급·예상치·운영 입력의 차단과 tactical 자료의 stale을 보고했다.
- 이 모니터는 예정 UTC 08:25보다 늦은 12:14에 시작했다. 기존 ChatGPT 19시 KST 점검은 이 보고서보다 먼저 실행됐다. 일일 예약을 22시경으로 옮겼지만 미래 GitHub 지연까지 없어지는 것은 아니므로 보고서가 늦으면 원천 실행을 확인한다.
- [운영 갱신 34676369643](https://github.com/wscha231/r1000-quant-engine/actions/runs/34676369643)은 accepted risk-outcome 복원에서 BLOCKED_ONE_TIME_LEGACY_QUARANTINE_AUTHORIZATION_REQUIRED로 종료됐다. 당시 기존 상태의 as_of는 2026-07-24다. 현재 가격 manifest와 accepted transaction은 게시되지 않았다.
- Free Data, Data Readiness, Smart Money의 09-12 오전 UTC 실패는 unauthorized_client/deleted_client 계열이다. 이들은 새 토큰 발급·검증보다 이른 실행이다. 현재 Secret이 계속 실패한다고 단정하거나 같은 일을 재실행하지 않는다. 다음 승인된 정상 실행의 인증·보존 성공을 확인한다.
- [Live Extension 34663352311](https://github.com/wscha231/r1000-quant-engine/actions/runs/34663352311)은 anchor=2026-06-23, days_elapsed=81을 출력했다. 현재 운영 계좌·현재 종목선정 결과의 대체 자료가 아니다.

### 이번 GitHub 수정안의 적용 상태
이 변경은 정기 실행 3개를 없애고 수동 기능을 남긴다. 기존 장기 저장 무결성 패치와 원인이 다르므로 적용 시 별도 PR로 분리한다. 적용은 이 PR의 리뷰·검증·병합을 거친 뒤 활성화된다.

사용자가 2026-09-13 KST에 새 작업트리 생성·적용·리뷰·병합을 명시적으로 승인했다. 현재 master 기준의 로컬 작업트리에 수정안을 반영하고 검증했으며, GitHub 코드 리뷰를 거친다. Git 명령의 원격 쓰기 인증은 없으므로 로컬 커밋의 전체 tree와 일치함을 확인한 GitHub 연결로 게시한다. 장기 저장과 공통 데이터 이용 문서는 별도 [PR423](https://github.com/wscha231/r1000-quant-engine/pull/423)에서 검토한다.

### 지속 정리 기준
각 자동화에는 목적, 원본/소비자, 트리거, 마지막 성공, 실제 자료 기준일, 데이터·코드 hash, 비용, 다음 점검일을 기록한다. 다음 원칙으로 정리한다.
1. 끝난 PR/실험의 일회성 감시는 종료한다.
2. 같은 원본·같은 코드·같은 목적의 중복 계산은 대표 작업에 통합한다.
3. 실패 수집기는 필요성을 먼저 확인하고 복구한다. 실패 자체가 불필요하다는 뜻은 아니다.
4. 고정된 과거 입력으로 만드는 연구 보고는 새 입력/코드가 있을 때만 재평가한다.
5. 장기 원본·정정 이력·실패 실험 기록은 보존하고 자동 실행 비용부터 줄인다.
6. 현재성·PIT·비용·커버리지 검증 없는 점수는 현재 포트 추천으로 게시하지 않는다.
