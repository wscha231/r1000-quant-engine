# 데이터 복구 진행과 다음 필요사항

기준: 2026-09-14 UTC. 확인한 master:
`bcb14c06613e34420ce7988e5bb1ac5547b22b57`.

## 이번 수정

ALFRED의 20만 행 제한 때문에 대형 vintage 자료가 중단된다. 페이지를
최대 200개까지 읽되 총 200만 행/원본 320 MiB 한도와 총건수·offset 검사를
적용했다. 초과하면 명시적으로 실패하며 일부만 성공으로 게시하지 않는다.
[FRED 공식 API](https://fred.stlouisfed.org/docs/api/fred/series_observations.html)는
limit와 offset을 지원한다. 요청당 10,000행은 유지한다.

페이지 제한 확대 후 발생할 수 있는 복원 실패도 함께 처리했다. 정규화된
자료를 8 MiB 단위로 나누고 순서·해시·행수 manifest로 연결한다. 기존의 작은
자료는 같은 해시를 유지하고, SQL 읽기는 순차 처리한다. 원본·과거 catalog와
pack 검증 및 RESEARCH_ONLY 경계는 유지한다.

로컬 검증: source 17 + history 45 + cycle 17 = **79개 테스트 통과**.
20만 행을 넘는 21페이지 수집, 128 MiB 초과 자료 복원, 중복 업로드 방지,
페이지/건수 오류와 파일 손상을 포함한다. 실제 NFCI 수집 성공을 뜻하지 않는다.

게시 승인: 앞선 GitHub push는 자동 승인 검토에서 명시적 외부 게시 승인
부족으로 차단됐다. 사용자가 코드·문서 7개를 새 브랜치와 검토용 PR로
게시하는 요청에 2026-09-14 "진행해"로 승인했다. 이전 임시 폴더 소실 후
같은 master에서 복원한 파일 tree는 `4947323f56305814d24f2d9c9080a1eb10cabe0f`로
이전 검증 버전과 정확히 일치했고, 관련 테스트 79개가 다시 통과했다.
현재 게시 대상은 `wscha231/r1000-quant-engine` /
`codex/alfred-pagination-20260913`이다. 원격 PR/CI 결과와 실제 수집 실행은
별도 증거로 확인한다. 이번 승인은 검토용 게시이며 운영 복구 완료가 아니다.

## 현재 증거와 한계

- [장기자료 run 34719702944](https://github.com/wscha231/r1000-quant-engine/actions/runs/34719702944)
  의 job 103623160703 및 로그를 직접 확인했다. source는 `1c48a92587f5b31c355804e694f03ece2cc52acd`.
- Drive executions 폴더의 영수증 3개를 확인했다. 최신 파일 바이트의 SHA256은
  `bbc28eac3c21a859e0be22b21d34079119299599a2e6e818aadba4a98c58c76b`와 일치한다.
  catalog는 `23ebbf52f26b5ea46ff8b82e59f7ad41942d93fde627123049cf4735b8812227`,
  commit은 `cf6f88321a2c1f86da5719af1771cf711668059e06203202d2c6e00bcf1c9475`.
- 영수증의 품질은 PARTIAL, 실제 소비 153,749행, selector 허용 false다.
  catalog와 연결된 quality 보고서의 원본 바이트 해시도 일치했다. quality 해시는
  `44ab9218220f6b3585705b3980ea1b29c9174002ff2e7f0cc467e18ad8d0a2b6`이다.
  차단 원인은 NFCI `alfred_page_limit`, SEC 두 기업 `HTTP_404`로 직접 확인됐다.
  이번 점검에서 기존 27개 pack 전체를 다시 다운로드한 것은 아니다.
- 최신 모니터 [34759617119](https://github.com/wscha231/r1000-quant-engine/actions/runs/34759617119)는
  현재 master에서 성공했다. 작업 성공을 점수·포트 최신성으로 대체하지 않는다.
- [PR #406](https://github.com/wscha231/r1000-quant-engine/pull/406)은 Draft,
  head `785e7324e36508008fb5046ee74c7a0d3b426c70`, 미병합이며 현재 master와
  충돌한다. 오래된 점수의 매도안 차단 기능은 현재 master에 재구성해야 한다.
- [PR #426](https://github.com/wscha231/r1000-quant-engine/pull/426)은 Draft,
  head `4721ee507ffe699cac1af93e0e2e93d4ae6624fd`. 내부 데이터 준비도와
  구독서비스 기초 작업이며 회원 인증·결제·유료 출시 완료가 아니다.

## 필요한 후속 작업

| 우선순위 | 작업 | 완료 증거 | 사용자 입력 필요 |
|---|---|---|---|
| 1 | 이 수정의 정확한 commit 검토와 master 반영, 장기자료 검증 실행 | NFCI dataset의 실제 전체 count/행수/기간, clean restore와 실행 영수증 | 현재 추가 키·유료 결제 불필요 |
| 1 | #406 기능을 현재 master에 재구성 | 오래된 가격·점수로 생성된 유효 매도안 0건, 정상 입력 대조시험 | 코드 작업에는 불필요 |
| 2 | ICICI Bank/Bank OZK 대체 재무 어댑터 | 원문 공시·회계기간·통화·수정 이력·공개시점 연결 | 우선 공식 무료 공시로 진행 |
| 2 | 후보별 최신 가격·재무·추정치·점수 동시점 결합 | 전체 후보 coverage/결측 사유, 실제 공시 접수일과 model/run 식별자 | 유료 데이터 필요성이 입증되면 상품·권한·비용 제시 |
| 3 | 과거 universe·상폐·기업행동·PIT 연결 | 누수 없는 실행 가능한 과거 시점 패널 | 무료 범위 밖 데이터의 라이선스/예산은 추후 결정 |
| 3 | 과거 검증·Shadow 운용 후 기록 공개 | 비용 차감 OOS 성과, 거래·현금 원장과 발행 후 성과 기록 | named fullrun의 preflight 통과 후 기존 프로젝트 절차 적용 |
| 4 | 구독자 UI·회원·결제·안내 | 데이터가 오래되면 명확히 표시, 발행 시점 보존, 접근제어·결제 검증 | 서비스명/도메인, 운영 국가, 월 운영 예산, 결제 사업자 정보 |

현재 SEC CIK 0001103838은 ICICI Bank, 0001569650은 Bank OZK 관련 등록이다.
404가 나왔다는 사실만으로 임의의 새 CIK에 대입하지 않는다.
[ICICI 공식 IR](https://www.icici.bank.in/about-us/invest-relations)은 최신 실적과
연례자료를 제공한다. [Bank OZK의 SEC 등록 공시](https://www.sec.gov/Archives/edgar/data/1569650/000095012317004316/0000950123-17-004316-index.html)는
13F 공시로 확인되며, 회사 재무제표 API의 존재 증거가 아니다. Bank OZK의
회사 IR/FDIC 재무공시와 ICICI 20-F 원문을 확인·정규화하는 후속 작업을
완료할 때까지 해당 재무값은 결측이다.

새 구독 상품의 상세 법적 분류·시장 데이터 재배포 권한은 출시 국가와 서비스
내용을 확정한 뒤 확인해야 한다. 현재 수익률 목표를 상품 보장 수익으로 쓰지
않으며 테스트 데이터를 고객에게 실제 운용 성과로 제시하지 않는다.

실계좌에 대한 편입·편출 대조까지 진행하려면 계좌번호를 제외한 보유종목,
수량, 평균단가, 현금, 통화와 기준일이 필요하다. 새 모델 포트폴리오 연구에는
실계좌 입력이 필수는 아니다.

[PROJECT_HANDOFF]
- 사실: 현재 master/PR와 최신 영수증을 확인했고 대형 ALFRED 수집·복원 수정을 작성했다.
- 추론: 기존 20만 행 제한 제거만으로는 정상화를 보장할 수 없어 저장/읽기 한도까지 검증했다.
- 변경: 페이지 검증과 chunked normalization, 관련 회귀검증 및 공통 reader 안내.
- 미확인: 수정 코드의 실제 NFCI 전체 수집·Drive 영수증, SEC 404의 대체 재무 완전성.
- 다음 행동: 정확한 head 검토/CI → master 반영 → 실제 자료 상태 검증, 이후 #406 재구성.
- 중단 조건: count/offset 변경, 자원 한도 초과, hash/pack/manifest 결함, 미검증 공시·오래된 점수.
- 상태: RESEARCH_ONLY. 계좌·주문·target·selector 가중치·챔피언 변경 없음.
