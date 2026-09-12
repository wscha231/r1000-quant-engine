# 다른 채팅·에이전트의 공통 연구 데이터 이용

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
직접 `get_records`로 읽은 행도 이를 우회하여 PIT 자료로 취급하지 않는다.
SEC의 filed 날짜와 ALFRED vintage 날짜는 실제 장중 공개시각과 다르다.
원문이 필요한 경우 dataset의 raw_objects를 get_bytes로 읽어 gzip 해제하며,
파생값에는 사용한 원본·코드·mapping·cutoff 식별자를 남긴다.

## 다른 채팅에 전달할 짧은 요청

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
