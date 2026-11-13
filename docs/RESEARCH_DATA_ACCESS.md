# 다른 채팅·에이전트의 공통 연구 데이터 이용

필라델피아 연준의 과거 빈티지는 [RTDSM 계약](A4_RTDSM_VINTAGES_V1.md)과
`tools/a4_rtdsm_sources.py`의 고정 원본 Reader를 사용한다. 고용·CPI의 월별
빈티지와 실업률의 분기별 빈티지를 구분하며, 관측 월을 실제 발표 시각으로
해석하지 않는다. 이 자료는 기존 원발행기관의 현재 수정 이력과 별도인
`DATE_ARCHIVE_RESEARCH_ONLY` 자료이며, 가격 이용 권한·검토된 학습 정책을
대신하지 않는다. 기존 학습 보류와 운영 설정은 유지한다.

A4 연준 원발행기관 자료는 [전용 구성요소 계약](A4_PRIMARY_DATA_OPERATIONS.md)을
따른다. 같은 연구 전송 경로의 `shared-research-v1/macro-primary`에 원본·정규화
해시와 실제 수집 시각을 보존한다. 이 구성요소의 저장 성공이 기존 Lake의
누락 실행 영수증을 복구하거나, 과거 PIT·학습·포트폴리오 승인을 부여하지 않는다.

A4의 현재 진단·과거 평가·미래 시나리오별 자료 상태는
[통합 연구 목록](A4_DATA_CENTER_V1.md)으로 확인한다. 같은 원본을 새 모델마다
수집하지 않고 기존 Reader와 정확한 실행 해시로 재사용한다. 과거 버전은
이력으로 남기며, 현재 수정 역사·목록상의 존재를 과거 투자 입력 검증으로
간주하지 않는다. 최신 수집 실패는 이전 성공으로 대체하지 않는다.

이 문서와 [기계 판독 색인](research_data_access.json)은 R1000 장기 재무·거시
자료를 찾는 공통 입구다. GitHub에는 코드와 계약을, 원본·정정 버전과 실행
영수증은 연결된 Google Drive에 보존한다. 최신 자료 상태는 고정된 이 문서의
날짜가 아니라 실제 catalog와 실행 영수증에서 확인한다.

## 먼저 확인할 것

1. 저장소 기본 브랜치의 정확한 SHA와 AGENTS.md를 읽는다. 이 파일이나
   collector가 PR에만 있으면 배포된 기능으로 취급하지 않는다.
2. `Durable financial and macro history`의 최신 실행·attempt·실패 단계를
   확인한다. 오래된 성공으로 최신 실패를 가리지 않는다.
3. 연결된 Drive에서 아래 연구 경로의 commit chain을 확인한다. catalog와
   pack은 이름인 SHA256과 실제 바이트가 일치해야 한다. `Lake` 복원은 모든
   과거 catalog가 참조하는 pack/멤버를 검증한다. 파일 목록만 읽은 경우에는
   바이트 검증 미완료라고 표시한다.
4. 해당 catalog를 참조하는 `executions` 영수증과 영수증에 연결된 quality
   보고서를 읽는다. catalog만 있으면 저장 증거이고 분석 완주 증거는 아니다.
5. 데이터별 실제 시작/종료일·결측·status·evidence·시점 정책을 확인한다.
   PARTIAL catalog에서 성공한 자료로 탐색은 가능하지만 전체 성공으로
   표현하지 않는다. 실패/STALE_RETAINED 자료는 기본 소비 경로가 차단한다.

## 경로와 자료

Drive의 기존 구성 base 아래:

`research/macro_technical_evidence/v1/scheduled/long-history-v1/`

root-folder ID를 지정하지 않은 기존 구성은 base 앞에
`r1000_top30_institutional/`이 붙는다. 특정 개인의 root ID나 인증값을
복사하지 말고 현재 승인된 연결을 사용한다. PR413의 작은 checkpoint,
paper_archive, accepted 계좌 원장은 별도 경로다.

| 키/경로 | 내용 | 해석 |
|---|---|---|
| `universe/cohort` | 현재 1,118증권 연구 코호트와 CIK 연결 | 과거 구성종목·전체 미국 상장 목록이 아님 |
| `sec/<10자리 CIK>` | 회사별 표준 XBRL fact와 원본·공시번호·단위·기간·정정 | 자료 존재가 완전한 3대 표/40분기/PIT를 뜻하지 않음 |
| `current/<series>` | FRED 현재 수정 역사 | 과거 컷오프로 소급해 투자 입력에 사용 금지 |
| `alfred/<series>` | 실제 반환된 vintage 이력 | 날짜 단위 가용성; 장중 발표시각을 만들어내지 않음 |
| `worldbank/<indicator>` | 5지역 연간 관측 | 현재 vintage, 국가별 결측과 실제 기간 확인 |
| `reports`, `executions` | quality·연구 결과·catalog 연결 | 실행 SHA/attempt 및 실제 소비 결과와 함께 확인 |

원본 묶음은 확장자 없는 내용 해시 이름이다. 텍스트 미리보기가 비어 있다고
빈 데이터나 삭제로 판정하지 않는다. 아래 검증된 reader 또는 승인된
Drive 다운로드로 바이트를 확인한다. 대형 SEC fact 전체를 채팅에 붙이지
말고 필요한 기업·기간·항목만 추출해 출처와 함께 사용한다.

## Python 읽기 예제

현재 환경에 승인된 rclone 연구 연결이 구성되어 있을 때만 실행한다.
아래는 수집·업로드를 수행하지 않는다. workspace는 재생성 가능한 로컬 캐시다.

```python
import json
import os
from pathlib import Path
from tools.long_history_lake import Lake, RcloneTransport, materialize

lake = Lake(RcloneTransport(os.environ['MACRO_RESEARCH_REMOTE']),
            Path('research-read-cache'))
if lake.parent is None:
    raise ValueError('No verified history commit')
commit = json.loads(lake.read_hash('commits', lake.parent))
execution = lake.verified_execution()  # Missing/mismatched receipt or report fails.
print({'execution_receipt': execution['execution_receipt_sha256'],
       'quality_status': execution['quality_status'],
       'study_recomputed_from_drive': execution['study_recomputed_from_drive']})
if not execution['study_recomputed_from_drive']:
    raise ValueError('Stored data has no completed study in this cycle')
key = 'current/UNRATE'
dataset = lake.catalog['datasets'][key]
if dataset['status'] not in {'COLLECTED', 'UNCHANGED'}:
    raise ValueError('Dataset is blocked or stale')
rows = lake.get_records(key)
print({'commit': lake.parent, 'catalog': commit['catalog'],
       'dataset': key, 'status': dataset['status'],
       'evidence': dataset.get('evidence'), 'rows': len(rows)})
# Optional SQL materialization uses an explicit research cutoff:
# materialize(lake, Path('macro.sqlite'), [key], 'YYYY-MM-DD')
```

SQL materialize는 현재 수정 자료를 과거 시점으로 소급하는 요청을 차단한다.
위 예제의 verified_execution은 해당 commit·catalog에 대응하는 실행 영수증과
연결된 보고서의 해시를 검증한다. 저장 이후 중단되어 영수증이 없거나 보고서가
누락된 최신 commit은 공통 소비 예제에서 차단되며, 이전 성공으로 대체하지 않는다.
PARTIAL이면 표시된 dataset 상태·coverage를 따로 확인하여 연구에 한정한다.
직접 `get_records`로 읽은 행도 이를 우회하여 PIT 자료로 취급하지 않는다.
SEC의 filed 날짜와 ALFRED vintage 날짜는 실제 장중 공개시각과 다르다.
원문이 필요한 경우 dataset의 raw_objects를 get_bytes로 읽어 gzip 해제하며,
파생값에는 사용한 원본·코드·mapping·cutoff 식별자를 남긴다.

## 다른 채팅에 전달할 짧은 요청

### 모델 버전이 달라도 원본은 한 번 보관

`tools/research_model_inputs.py`는 기존 Reader 위의 얇은 연구 입력 어댑터다.
새 collector·scheduler·Registry·원본 저장소를 만들지 않는다. 같은 dataset,
generation, 요청 범위, 소비 application, decision cutoff를 쓰는 모델은
동일 `input_id`를 공유한다. 모델 ID/버전, 코드 SHA, 설정 SHA, feature 정의
SHA는 별도 binding으로 남긴다. 투자 엔진 버전이나 AI 연구 클라이언트가
바뀌어도 원본을 모델별로 복사하거나 provider에서 다시 받지 않는다.

```python
from tools.research_model_inputs import (
    prepare_model_inputs, store_model_inputs, replay_model_inputs,
    plan_model_input_reuse,
)

# reader, generation_sha, cutoff, components, models, private_root는 기존
# 승인된 환경에서 고정한다. models에는 model_id, model_version, code_sha,
# config_sha256, feature_recipe_sha256를 넣는다. 실제 평가 실행은 별도다.
bundle = prepare_model_inputs(
    reader, "ds.us.prices.daily", generation_sha,
    decision_time=cutoff, components=components,
    consumer_id="ohlcv-technical-feature-h1", models=models,
)
# 하나의 실제 read_components 호출 결과를 여러 모델 버전에 참조한다.
# Source qualification의 consumer_id를 모델 이름으로 바꾸지 않는다.
local_receipt = store_model_inputs(bundle, private_root)
rows = bundle.read.results["company"].rows
```

기존 research transport 아래의 `shared-research-v1/model-inputs/<input_id>`와
`shared-research-v1/model-bindings/<binding_sha256>` 형식을 사용한다.
`store_model_inputs`는 명시한 private 로컬 경계에 메타데이터만 write-once로
저장한다. raw 가격·재무 fact 값은 복사하지 않는다. 동일 쓰기는 재사용하고
다른 바이트의 덮어쓰기는 거절한다. 이 로컬 결과는 Drive 저장·readback이나
Source/PIT/ER/A5 승인 증거가 아니다. Drive에 이미 보관된 generation/object를
기존 승인된 transport로 읽으며, 새로운 원격 연결·디렉터리를 만들지 않는다.

다른 채팅/모델은 input manifest의 SHA를 고정한 뒤
`replay_model_inputs(reader, manifest_bytes, expected_input_id=..., models=...,
financial_trust=...)`를 호출한다. 저장된 영수증만 믿지 않고 원본 Reader로
hash·권한·identity·clock을 재검증한다. 재무의 typed trust는 외부에서 다시
제공하며 메타데이터에서 스스로 만들지 않는다. 과거 cutoff 재현과 최신
재평가는 다르다. 최신 판단은 새 cutoff로 `prepare_model_inputs`를 호출하여
현재 availability/expiry 검사를 통과해야 한다.

가격의 `plan_model_input_reuse`는 같은 cutoff에서 실제 exact-session 검증을
마친 부분집합만 `REUSE_EXISTING`으로 표시한다. 확인한 범위 밖은
`REVALIDATION_REQUIRED`, session 증명이 없으면 `COVERAGE_UNKNOWN`이다.
이는 결측 확정이 아니므로 재수집 목록을 자동 생성하지 않는다. 먼저 같은
generation의 Reader 범위를 확장하고, 그 후에도 입증된 공백만 기존 Source
owner의 `INCREMENTAL_ONLY`/`BACKFILL_REQUIRED` 계약으로 전달한다. 재무의
분기·연간 기간과 거시 vintage를 거래일 session으로 바꾸지 않는다.
모든 계획은 `collection_approved=false`, provider refresh 0을 유지한다.
이 wrapper는 Reader의 byte-level 연구 의미를 보존한다. 기존 Feature의 별도
외부 qualification tuple 검증이나 정식 Source/PIT 승인을 대신하지 않는다.

거시 원본·vintage는 위의 기존 Lake commit/catalog/execution 참조를 사용한다.
이 어댑터가 거시를 price/financial schema로 변환하거나 전체 820종목의 현재
적격 입력·백테스트·모델 평가·투자 비중을 완성했다고 표시하지 않는다.

> GitHub wscha231/r1000-quant-engine의 최신 기본 브랜치와 AGENTS.md,
> docs/RESEARCH_DATA_ACCESS.md, docs/research_data_access.json을 읽고
> 연결된 Google Drive의 검증된 장기 연구 데이터를 재사용하라.
> 실제 catalog·execution·자료 기준일·coverage·PIT 상태를 먼저 밝히고,
> 요청한 분석에 필요한 기업·기간·지표만 읽어라. 부족한 자료만 추가 조사하고
> 현재 수정값을 과거 투자 판단에 소급하지 마라. 코드 구현·실제 수집·분석
> 완주·표본외 성과를 구분하고 원장·매매·모델 승격은 변경하지 마라.

다른 채팅이 이 문서를 읽었다고 자료 접근·공유 권한이 새로 생기지는 않는다.
같은 승인된 GitHub/Drive 연결을 사용하며 최신 evidence를 직접 확인한다.

## 현재 알려진 범위와 미완료 항목

2026-09-12 확대 수집은 27 pack/503,129,850바이트, SEC 1,104 발행기업과
15,173,078 fact를 보존했다. FRED 30개, ALFRED 11개, World Bank
20개 국가/지표 조합이 수집됐으며 전체 상태는 PARTIAL이었다. 이는 이전
실행의 범위이며 현재 상태는 새 catalog에서 다시 산출한다.

10년 완전 재무·과거 유니버스·30년 모든 지표·실제 전체 펀드 백테스트는
완료되지 않았다. 새 데이터가 저장돼도 미검증 신호의 selector 가중치는
활성화하지 않는다. 원래 요구사항의 구현 순서는 저장 복구→시점 재무와
가격/종목 이력→발표/효과/예측 원장→실제 종목평가·운용 검증이다.

## 이미 저장된 세대의 분석·검증 복구

수집 후 commit까지 기록됐지만 이후 재조회나 분석이 중단된 경우에는 기존
`long_history_research.yml`의 수동 입력 세 개로 해당 세대만 마무리할 수 있다.
`finalize_commit_sha256`, `finalize_catalog_sha256`, `source_head_sha`를 모두
지정한다. 값은 실제 commit·catalog·수집 당시 코드 SHA에서 고정한다. 하나만
지정하거나 형식이 잘못되면 Source 접근 전에 중단한다.

복구 모드는 기존 단일 writer를 공유한다. 보관 원본과 전체 과거 pack을 새로
검증한 뒤 같은 세대의 SQL 연구 캐시와 분석을 생성한다. 실행 영수증을 쓰기
직전에 전체 세대를 다시 검증하며, head 변경·원본 변조·분석 실패·중단에는
새 실행 영수증을 쓰지 않는다. Provider 수집과 새로운 데이터 commit은 0이다.

실행 영수증의 `run_id`는 원래 수집 commit의 식별자를 유지한다. `recovery`에는
실제 복구 run과 코드 SHA를 따로 기록한다. 원래 GitHub 실행의 실패·취소 상태는
원래 실행 기록으로 남는다. 이미 정상 완료된 영수증이 있으면 이를 읽어 재사용하며
두 번째 영수증을 만들지 않는다. 기존 불완전·중복 영수증은 복구 모드가 덮어쓰지 않는다.

`PARTIAL`·`PARTIAL_COVERAGE`의 종료 코드는 기존과 동일하게 2다. 세대의 실제
`study_recomputed_from_drive`와 개별 dataset 상태를 보고 연구 소비를 판정한다.
이 복구가 과거 PIT·투자 적격성·ER·포트폴리오 승인을 부여하지 않는다.
