# PR #702 병합 후 Source 시간표·캐시·호출량 점검

점검일: 2026-10-31 KST. 저장소: `wscha231/r1000-quant-engine`.
기준 master/merge: `8880797df528d76f978f7987674745a7444e8624`.
비교 기준: PR 직전 master `afa8cf585b700cee70ac3c57e21898f3e94970df`.
이 문서는 병합 재심사가 아니라 코드·합성 검사·기존 실행 로그의 후속 분석이다.

## 판정

- **시간 경계 수정은 유효하다.** 완료된 NYSE 거래일 D를 유지하면서,
  private SIP 수집기의 별도 `D 23:59:59Z + 15분` 경계를 통과한다.
- **최신 거래일 데이터 완전성을 보장하지는 않는다.** legacy 가격 작업은
  `refresh_through_date`를 전달하지 않는다. D-1까지 있는 캐시는 새 슬롯에서도
  age2로 재사용되며, `completed`라도 개별 실패와 오래된 바가 남을 수 있다.
- **추가 호출은 가능하지만 실측 증가로 확정할 수 없다.** 자정을 넘기는 실행
  지연이 이미 있었다. 동일 캐시·동일 입력을 가정한 정시 슬롯 비교와 실제 실행
  관측을 분리해야 한다.
- **80개/첫 배치40과 기존 승인·한도는 유지된다.** 이 숫자는 HTTP 요청 상한이나
  USD 예산이 아니다. 기존 private 승인·핀·기간·누적 비용 제한을 확장하지 않는다.
  새 슬롯의 실제 운영 성공이나 현재 유효한 standing 수집 승인은 확인하지 않았다.

## 1. 읽은 코드와 변경 범위

[PR #702](https://github.com/wscha231/r1000-quant-engine/pull/702)는
2026-10-30 15:34:30 UTC(10-31 00:34:30 KST)에 병합됐다.
병합 tree는 `379bbd7086b9704dc319818d2fce0c41752e98a0`이다.
runtime 알고리즘 변경 없이 공유 cron 및 문서·계약 검사가 바뀌었다.
아래 네 Python 파일은 PR 직전 master 대비 동일하다.

| 경로 | 확인한 역할 |
| --- | --- |
| [.github/workflows/free_data_daily_update.yml](https://github.com/wscha231/r1000-quant-engine/blob/8880797df528d76f978f7987674745a7444e8624/.github/workflows/free_data_daily_update.yml) | 공유 cron, legacy/managed 조건, 90분 timeout, 복원·동기화 |
| [tools/run_daily_market_session_gate.py](https://github.com/wscha231/r1000-quant-engine/blob/8880797df528d76f978f7987674745a7444e8624/tools/run_daily_market_session_gate.py) | NYSE 달력, 완료된 거래일, 신선도·휴일·조기폐장 |
| [tools/alpaca_sip_managed_refresh.py](https://github.com/wscha231/r1000-quant-engine/blob/8880797df528d76f978f7987674745a7444e8624/tools/alpaca_sip_managed_refresh.py) | inclusive endpoint, 배포 핀, 권리·OWNER 승인·누적 예약 |
| [tools/run_free_data_lake_bootstrap.py](https://github.com/wscha231/r1000-quant-engine/blob/8880797df528d76f978f7987674745a7444e8624/tools/run_free_data_lake_bootstrap.py) | 가격 시작일2016-01-01, 기본80개/배치40, end/refresh-through 미전달 |
| [tools/build_replay_price_cache.py](https://github.com/wscha231/r1000-quant-engine/blob/8880797df528d76f978f7987674745a7444e8624/tools/build_replay_price_cache.py) | UTC 날짜+2 종료일, age>2, 티커별 재시도, 실제 바 기반 manifest |

## 2. 정시 실행 전후

D는 직전 미국 거래일이고, 덧셈·age는 거래일 수가 아닌 **달력일 수**다.
예: D=2026-10-29이면 새 UTC 실행일은10-30, 요청 종료일은11-01이다.

| 항목 | 이전 정시 슬롯 | 새 정시 슬롯 |
| --- | --- | --- |
| cron | `30 23 * * 1-5` | `30 0 * * 2-6` |
| UTC / KST | D 23:30 / 다음날08:30 | D+1 00:30 / 같은날09:30 |
| 선택 NYSE 거래일 | D | D |
| 실제 close 이후 경과(겨울/여름) | 150/210분 | 210/270분 |
| private inclusive endpoint+15분 | 미도달 | 00:14:59 이후, 15분1초 여유 |
| legacy 요청 end(exclusive) | D+2 | D+3 |
| D까지 있는 캐시 age | 0 | 1, 재사용 |
| D-1까지 있는 캐시 age | 1 | 2, 재사용; D 누락 가능 |
| D-2까지 있는 캐시 age | 2, 재사용 | 3, 재요청 |
| D-3 이하/누락/읽기 불가 | 이미 요청 대상 | 계속 요청 대상 |

legacy gate는 close+90분, managed gate는 close+120분과 endpoint+15분을
각각 검사한다. 새 슬롯은 두 close buffer도 통과한다. 금요일→토요일, DST
전환 전후 월요일, 조기폐장을 합성 검사했다. 휴일 다음날과 과도하게 지연된
실행은 기존18시간 신선도 제한으로 건너뛴다. 늦은 실행을 강제로 성공 처리하지 않는다.

**D+3은 yfinance 호출의 종료 인자이며 실제 관측 범위가 아니다.**
private SIP 요청의 inclusive D23:59:59Z와 서로 다른 경로다.
manifest `end`는 보유 바 중 가장 늦은 날짜, `common_coverage_end`는 선택된
각 티커의 마지막 바 중 가장 이른 날짜다. 후자도 전체 역사 구간의 무결성을
증명하지는 않는다. 요청 end를 실제 데이터 종점으로 대체하거나 시계를 역산하지 않는다.

## 3. 추가 호출량 계산

동일한 복원 캐시·티커 집합·시작 시각 외 조건에서 이전 대상 N, 자정 이동으로
새로 age3이 된 티커 K라 두면 `0 <= N+K <= 80`이다. 신규 age 전환 효과만으로는
`0 <= K <= 80`이다. 실행 사이 데이터/입력/복원 결과가 달라지면 이 비교 가정은 깨진다.

정상 NYSE 바만 있는 보통 월요일에는 직전 금요일 캐시가 이미 age3이고 새 슬롯에서는
age4이므로 이 주말 효과만으로 추가 대상이 생기지 않는다. 보통 화요일의 D-2는
일요일이므로 역시 해당 경계 바가 없다. 추가 K의 실제 크기는 요일·휴일과 티커별
마지막 보유 날짜에 달려 있으며 매일80개가 추가된다는 뜻이 아니다.

수집기는 최초 배치 후 **실패한 티커만 최대2회 개별 재시도**한다.

| 단위 | 대상 n개의 범위(n>0) | 최대80개일 때 |
| --- | --- | --- |
| 첫 downloader/yfinance 함수 호출 | `ceil(n/40)` | 2 |
| 재시도 포함 downloader 함수 호출 | `ceil(n/40)` .. `ceil(n/40)+2n` | 2 .. 162 |
| 함수에 전달된 티커의 누적 시도 수 | n .. 3n | 80 .. 240 |
| 실제 HTTP 요청·청구 단위 | 라이브러리 내부 인증·재시도·캐시·계약에 따라 다름 | 위 숫자로 상한 확정 불가 |

전체 K범위를 통틀어 **추가 최초 함수 호출0..2**, 추가 티커 시도0..240,
추가 함수 호출0..162가 가능한 경계다. 최악의 증가는 N=0, K=80이다.
전부 첫 시도에 성공하면
추가 티커 시도는0..80이다. 같은 기존 티커들의 응답 결과가 유지된다는 가정에서
추가 함수 호출의 최악값은 `ceil((N+K)/40)-ceil(N/40)+2K`다.
배치 경계를 안 넘으면 K>0이어도 첫 함수 호출 증가가0일 수 있다.
N40→41 전체 실패 예에서는 함수 호출81→84로3회 증가한다.

이는 **한 번의 legacy 가격 자식 작업**에 대한 경계다. 반복 실행이면 누적되고,
별도 macro snapshot(SPY/VIX/FRED 등), 라이브러리 내부 HTTP, Drive, private SIP,
GitHub runner 비용까지 포함한 workflow 총량 상한이 아니다. scheduled bootstrap은
required/operating ticker union을 넘기지 않아80개 상한이 적용된다. 다른 CLI 호출의
required/operating union은 이 상한 밖의 별도 계약이다.

기존 바가 그대로 돌아와도 nonempty이면 accepted가 되어2016년부터의 범위를
다시 요청·병합할 수 있다. 마지막 바가 계속 오래되면 다음 실행에도 stale이다.
빈 응답 티커는 매 실행 최대3시도다. 이 경로에는 마지막 실패/무변화 응답에 대한
거래일별 negative cache가 없다. 따라서 추가 시도가 추가 바를 뜻하지 않는다.

확인한 코드·승인 자료에는 이번 legacy yfinance 경로에 적용할 계정별 단가나
HTTP/청구 계약이 없다. **실제 금액은 추정하지 않는다.** 무료 경로라는 이름도
통신·runner·저장 비용0의 증거가 아니다.

## 4. 기존 실제 실행에서 확인한 사실

관측 시각2026-10-31 00:14 UTC의 schedule 목록에서 기준 merge SHA 실행은0건이었다.
목록 범위는 `actions/runs?event=schedule&head_sha=<merge>&per_page=25`, total_count0.
새 슬롯 실행 성공·후속 비용 변화는 아직 이 증거로 판정할 수 없다.

직전 목록에서 확인된 기존 실행
[40994021962](https://github.com/wscha231/r1000-quant-engine/actions/runs/40994021962),
attempt1, head `8d4ddec66cd8430fc3867fc806984084e5fa6f84`,
[daily_update job123862829917](https://github.com/wscha231/r1000-quant-engine/actions/runs/40994021962/job/123862829917)의
기존 로그를 읽었다. workflow 생성은10-30 02:50:40 UTC, gate 관측은02:56:43 UTC다.
**이전 cron도 이 사례에서는 이미 자정을 넘어 실행됐다.** 따라서 D+3/age3은
새 cron에만 발생하는 현상이 아니며, 정시 슬롯의+1일 효과를 이 실행 대비
실측 증가로 계산해서는 안 된다.

| 기존 로그 항목 | 관측값 |
| --- | --- |
| 선택 거래일 D | 2026-10-29 |
| ticker_count / missing_before / stale_before | 80 / 0 / 2 |
| requested_start / requested_end | 2016-01-01 / 2026-11-01(D+3) |
| 대상 | AVB, BLD |
| download_batch_audits | attempt1[AVB,BLD], attempt2[BLD], attempt3[BLD] |
| 합계 | 함수 호출3회, 티커 시도4회; HTTP 수·금액은 미확인 |
| 결과 | written1(AVB), failed_count1(BLD, empty_download), status completed |
| 공급자 반환 마지막 날짜 | AVB2026-08-14, BLD 없음 |
| 보유 바의 end / common_coverage_end | 2026-10-28 / 2026-07-02 |
| refresh_through_date / exact_coverage | 빈 값 / null |
| managed private job | skipped(job123862831900) |

이 사례는 과거 관측이며 현재 캐시의 상태를 대신하지 않는다. 다만 녹색
workflow나 `completed`를 D의80개 가격 완전성으로 읽으면 안 된다는 직접 증거다.
이번 점검에서 이 workflow를 재실행하거나 가격/Drive 데이터를 수집하지 않았다.

## 5. 승인·비용 제한과의 관계

| 경계 | 판정 |
| --- | --- |
| 기존80개/첫 배치40 | 충돌 없음. 숫자는 그대로이며 재시도는 기존 동작이다. |
| 추가 호출·비용 수용 | PR에 명시된 수용 범위와 일치. 고정 HTTP 횟수/금액 보장은 없음. |
| private 수집 승인 | cron 변경은 grant 갱신이 아니다. workflow 자체가 PIN_PATHS에 들어가 이전 workflow SHA는 MANAGED_CODE_DRIFT로 거절된다. |
| private 비용 제한 | 기존 opening usage, 누적 ceiling, full5400초 예약, 실패 비용 보존, 권리·실행 기간은 유지된다.80/40으로 private821개 범위를 승인했다고 해석할 수 없다. |
| 만료된 개별 연구 목적 | #590의 후속 로컬 SPY 목적도19:19:33Z에 종료됐다고 기록되어 있다. 이는 신규 provider 수집 승인이 아니다. |
| 실제 단가/현재 secret·OWNER 재결속 | 확인하지 않음. 현재 수집 활성화나 예산 준수를 실측 인증하지 않는다. |

[Source 병합 종결](https://github.com/wscha231/r1000-quant-engine/issues/590#issuecomment-6526744299)과
[후속 로컬 목적 종결](https://github.com/wscha231/r1000-quant-engine/issues/590#issuecomment-6531747496)을
확인했다. private 재가동은 배포된 핀·현재 유효한 control/OWNER·잔여 누적 한도의
일치를 기존 검증기로 확인해야 한다. 이 점검은 그 실행을 승인하거나 수행하지 않는다.

추가 운영 충돌은 **소비자 순서**다. readiness는00:15 UTC로 Source00:30보다15분
앞이고, selection01:15도 Source가90분을 다 쓰면 완료02:00보다45분 앞이다.
queue 지연은 더해진다. 기존 고정 cron만으로 Source→소비자 최신성/ACK는 보장되지 않는다.
이 점검은 거래·영속 상태 경로의 재예약이나 실행을 변경하지 않는다.

## 6. 최소 변경과 검증

runtime·cron·캐시 age·요청 범위·재시도·승인·비용 gate를 변경하지 않았다.
수용된 UTC 효과를 되돌리거나 시계를 backdate할 근거가 없기 때문이다.
새 `tests/source_slot_impact_smoke.py`의8개 unittest와 Tier-1 등록만 추가했다.
검사는 모두 합성 parquet/주입 downloader이며 socket/provider guard로 외부 호출을 차단한다.

- 새8개: 정시/DST/금요일/조기폐장, endpoint 초 경계, 휴일·과도 지연,
  age2→3, D 누락 재사용,81개 중80개/배치40, 같은 오래된 응답 반복,
  실패 재시도162함수/240티커시도, 실패 후 원본 캐시 보존을 검증한다.
- 관련 PR validation: replay_price_cache, source_slot_impact, workflow_artifact,
  daily_market_close_gate **4/4 파일 PASS**, 26.82초. 전체235/236파일 suite 실행 주장이 아니다.
- Python3.12.14, pandas2.2.3, pyarrow18.1.0, pandas_market_calendars5.5.0.
- 새8개 unittest는 `-O`에서도8/8 PASS(3.51초). unittest 검증은 최적화로 제거되지 않는다.
- 기존 ManagedExecutionTests **46/46 PASS**(15.14초). 배포 핀·권리·기간·전체 예약·
  누적 예산·재실행 거절 등 기존 보호 조건이 포함된다. 앞선 PR702 집중3개 PASS는
  이46개의 부분집합이며 별도46개에 더해 세지 않는다.
- 기존 free_data_lake_bootstrap_smoke의 dry-run manifest 검사 PASS.
  bare assert가 제거되는 `-O` 실행으로 이 일반 검사를 대체하지 않았다.

현재 결론은 **시간 게이트 수정 유효 / 데이터 완전성 미보장 / 실측 비용 증가 미확인**이다.
다음 운영 수락은 이미 생성된 새 실행의 세션·요청 감사·failed_count·실제 바 종점·
final meter·소비자 영수증을 읽는 방식으로 검증해야 한다. 신규 유료 호출이나
수집 재실행은 이 보고서의 전제에 포함하지 않는다.
