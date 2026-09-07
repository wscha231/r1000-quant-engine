[PROJECT_HANDOFF]

# 미국·한국 Research Decision V1 — 2026-09-07

계산 엔진·국가별 내보내기·테스트·독립 실행 산출물과 PR을 작성했다.
**검증된 실제 자료에 근거한 투자순위와 5+2 포트 제안은 미완료다.**
실제 2+1 표본은 실행했으나 필수 자료가 부족하여 전부 대기/0%, 연구자금은
100% 미배정으로 남았다. 합성 데이터 연결 성공은 수익성 검증이 아니다.

## 독립 판정

| 구분 | 판정 | 근거 |
|---|---|---|
| 코드 구현 | 연구 계산·내보내기 구현, 원자료 완결 연동은 미완료 | H1/H2/KR PR, 19/16/4개 신규 테스트 |
| 제한된 실제 실행 | EXECUTED_BLOCKED | US/KR export와 consumer 모두 exit 2; 검증 통과 0/3 |
| 합성 연결 | 3개 및 7개 종목 연결 통과 | 같은 코드·입력으로 두 번 실행, 결정과 파일 해시 동일 |
| OOS·수익성 | 미실행·미검증 | 과거 PIT/추정치 이력·성숙 outcome 검증 없음 |
| 운영 승격 | 미실행·승인 없음 | production_promoted=false, orders_allowed=false |
| 실계좌 대조 | 미실행 | NEW_CAPITAL_RESEARCH; 1억원은 연구 규모 가정 |

외부 검토와 CI의 최신 상태는 아래 PR의 **현재 HEAD**에서 확인한다.
이 문서는 실행 증거이며 자체 승인이나 병합 신호가 아니다.

## 작업 경계·커밋·PR

| 범위 | branch | 실행/구현 기준 commit | PR |
|---|---|---|---|
| 미국 H1 | codex/research-decision-v1-data-contract-20260907 | c1196e775b7fa3e1e857025cb23c80254b296602 | [US #399](https://github.com/wscha231/r1000-quant-engine/pull/399) |
| 미국 H2 | codex/research-decision-v1-ranking-reviewed-20260907 | 07f976263481047e50bedae6349ede3e6a2292fc | [US #400](https://github.com/wscha231/r1000-quant-engine/pull/400) |
| 한국 export | codex/research-decision-v1-kr-export-20260907 | 3c40210b8675267121d7f40f3dcd8d158720a4e8 | [KR #2](https://github.com/wscha231/kr-quant-engine/pull/2) |

H2는 H1 브랜치를 PR base로 사용한다. H1과 H2의 기능 변경을 분리했다.
마지막으로 확인한 기본 브랜치는 US master `8ccbd478e05ff34c6dd70e410be0cae793c9863e`,
KR main `80cb0721896a834a45d257fc4f65255134338f36`였다.
[이슈 #396](https://github.com/wscha231/r1000-quant-engine/issues/396)은 과거 ownership
정규화 문제와 거절된 실험의 추적 근거다. V1은 그 추가 알파를 활성화하지 않는다.

AGENTS.md, 운영 표준, CURRENT_STATUS 및 KR 인수인계, 공유 교훈·실험 장부와
기각 기록을 확인했다. 오래된 CURRENT_STATUS/첨부 감사의 공급자 장애를 현재
상태로 단정하지 않았다. US #394 rclone hotfix, #389 macro archive는 의존 PR이
아니다. #320의 RS 배분을 재사용하지 않았고 #336의 REJECT_CAGR_AND_MDD 실험을
되풀이하지 않았다. 기존 캘린더와 공급자/캐시 계약을 확인했고 새 키·구매·수집
스케줄을 추가하지 않았다. 기존 valuation의 0 부채/TTM-as-forward fallback은
신규 계약에 맞지 않아 계산 경로로 사용하지 않았다.

로컬 검증 후 Git 객체의 전체 tree 일치를 확인하여 PR 브랜치에 게시했다.
로컬/원격 커밋 메타데이터 차이는 다음 동일 tree로 대조된다.

| 범위 | 로컬 검증 commit | 원격 기준 commit | 동일 tree |
|---|---|---|---|
| H1 | c574c100be73d56bcbf4d55e413aab71b8c3f4e0 | c1196e775b7fa3e1e857025cb23c80254b296602 | 572f8a2841c9377dfdf7e5b962d8b58943403f6e |
| H2 | 1112265b5486ea5e08bab481604a54cae3f300b5 | 07f976263481047e50bedae6349ede3e6a2292fc | 258f496b089a0356b95ba9248aa8b8e4bb0999c8 |
| KR | e6e411b243914a604a20be32ecb2f8b999491195 | 3c40210b8675267121d7f40f3dcd8d158720a4e8 | b3057e53e30059885d66042120aa71901e777b4a |

H1 검토 수정에 맞춰 H2를 재적용했다. 기존 H2 head
`88d4dfa1322d816481452d16928eb40678a0e999`는
`codex/research-decision-v1-ranking-before-h1-review2-20260907`에 보존했다.
최초 H2 `61af490a79ebf79d5fa75afae80fa447cc6bd1e6`도 보존한다.
PR #400의 본인 작업 브랜치만 재정렬했으며 기본 브랜치는 병합하지 않았다.

## 변경 파일과 핵심 함수

| 파일 | 핵심 함수·역할 |
|---|---|
| tools/research_decision_v1/data.py | export_market, envelope_errors, financial_errors, price_analysis, total_return_series: 출처·단위·시점·시장·가격조정·결측 검증 |
| tools/research_decision_v1/io.py | read_json, immutable_json, immutable_bytes, source_material: 제한된 입력·불변 저장·소스 해시 |
| tools/export_research_decision_market.py | 미국 전용 export CLI |
| tools/research_decision_v1/valuation.py | scenario_price, evaluate_security: 12개월 EV/EBITDA·P/E와 reverse valuation |
| tools/research_decision_v1/portfolio.py | add_fx_returns, read_book, propose, constraint_audit: 환율·기존 보유 비교·위험/비용/비중 |
| tools/research_decision_v1/engine.py | run_decisions, rank_sensitivity, component_hashes, discovery_snapshot: 재검증·순위·민감도·변경 이유 |
| tools/run_research_decision_v1.py | CLI, render_report: 독립 연구 산출물과 실행 manifest |
| tests/research_decision_v1_* | 합성 fixture, 데이터 19개 및 의사결정 16개 반례 |
| research/decision_v1/reproduce_checks.py | 실제 2+1 및 합성 3/7개 명령행 연결·반복 재현 검사 |
| docs/research_decision_v1_config.json | 출력 전 고정한 연구 설정 |
| docs/research_decision_v1_contract.md, docs/research_decision_v1_usage.md | 입력/출력·해석·제한 계약 |
| requirements_research_decision_v1.txt | 연구용 캘린더/표 계산 의존성 |
| tools/run_pr_validation.py | 신규 테스트 등록만 추가 |
| tools/build_p0_4_artifact_inventory.py, tests/test_p0_4_artifact_inventory.py | 보호된 실행기 등록의 실제 선행 commit pin/기대값만 변경 |
| docs/AGENT_SHARED_LESSONS_LEDGER.md | 실패·검토 교훈 추가 |
| KR tools/export_research_decision_market.py | source_material, verified_snapshot, execute_export: 검증한 동일 소스 바이트로 한국 export |
| KR tests/research_decision_export_smoke.py | 소스 변경·부모/하위 모듈·검증 후 교체 반례 4개 |
| KR .github/workflows/smoke_test.yml | 기존 PR 검증에 export 테스트 등록; 새 trigger 없음 |
| KR CHANGELOG.md, SESSION_HANDOFF.md, research/research_decision_v1.md | 한국 작업 경계·인수인계 |

보호 검증기를 끄지 않았다. H1 등록 pin은 `7d5913f1d48e213faaf979ea110276e51ab800dd`,
현 H2 등록 pin은 실제 선행 commit `163e1a4ae764f506f19a5150df72a8ced2a05b3f`다.
보호 경로 목록·검증 알고리즘·동결된 inventory는 바꾸지 않았다.

기존 모니터·공식 target·장부·주문·승격 경로의 diff는 없다. 미국 로컬의 기존
사용자 변경 CSV 두 개도 커밋하지 않았다. 작업 전후 diff numstat는 각각
`1/8878`, `1/41137`로 동일하다. 경로는 20260624 global_alpha_universe 아래
market_leader_challenger의 holdings_daily.csv와 sec_enriched_candidate_replay의
candidate_replay_book_sec_enriched.csv다.

## 사용 데이터·cutoff·결측

고정 cutoff: **2026-09-07T13:35:25Z**. 미국의 요구 완료 세션은 9월 4일,
한국은 9월 7일이다. [NYSE 거래일 안내](https://www.nyse.com/markets/hours-calendars)의
9월 7일 휴장과 시장 캘린더를 대조했다.

| 후보 | 산업 | 확보한 공개 근거 | 검증된 필수 가격/TTM/시나리오 |
|---|---|---|---|
| NVDA | AI 반도체 | [Q2 FY2027 IR](https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-second-quarter-fiscal-2027), 공개일 8/26, 분기말 7/26 | 0 / 0 / 0 |
| EME | 전기·기계 건설/서비스 | [Q2 2026 IR](https://emcorgroup.com/investor-relations/press-releases/2026-news/emcor-group-inc-reports-second-quarter-2026-results), 공개일 7/30, 분기말 6/30 | 0 / 0 / 0 |
| 000660 | 메모리 반도체 | [Q2 2026 IR](https://news.skhynix.com/en/q2-2026-business-results/), 공개일 7/29, 분기말 6/30 | 0 / 0 / 0 |

분기 IR 일부는 수작업 추출로 보존했으나 독립 대사된 원본 응답이 없어
`unverified`다. 단위는 base USD/KRW, 회계기준은 US_GAAP/K_IFRS_CONSOLIDATED로
명시했다. 날짜만 알려진 발표의 정확한 published_at/public_available_at은 null,
관찰·수집 시각은 cutoff에 고정했다. 현재 관찰로 과거 PIT 또는 컨센서스 변경
이력을 만들지 않았다. 재무의 보고 시간대가 확인되지 않은 점도 오류로 보존한다.

필수 누락: 원가격/거래량과 기업행사·benchmark의 동일 세션 자료, 최소 21개
유동성 관측(240일 RS는 241개), 연결 TTM·최근 분기/연간·순부채·희석주식수·
OCF/CAPEX/FCF/SBC, 대사된 가이던스/시나리오, 반대논리·고객/경쟁 근거와 위험
노출, 현재 FX·regime. 제공자 점검의 PASS가 이 3종목 coverage를 뜻하지 않는다.

최신 API 증거: run `34094427045`, job `101654720085`, HEAD `8ccbd478...`,
checked_at `2026-09-07T07:13:45.007496+00:00`. Alpaca SPY raw SIP, FMP AAPL
profile/annual estimates, DART 기업정보, KRX 표본은 PASS였다. Finnhub profile은
PASS, estimates는 403이었다. 이는 endpoint 표본이지 재무 완결/전체 universe
검증이 아니다. 기존 earnings run `33945765078`, artifact `9963347716`
(SHA256 `581ecacd8d627019ffb31f2308a1d125f168df54efe0c761bc99e30dc0cdcba5`)를
재사용하려 했으나 발급된 다운로드 URL의 로컬 요청 두 번이 HTTP 403 / error
1010으로 실패했다. 직접 SEC/Yahoo 확인도 URLError였다. 새 키/커넥터를 만들지 않았다.

추가 13F/Form 4/뉴스/옵션은 독립 optional 상태이며 가점을 주지 않는다.
현재 전체 차단 사유는 필수 자료다. optional 공급자 장애만으로는 검증된 다른
종목이나 기본 연구 계산을 차단하지 않는 반례가 통과했다.

## 실제 연구 출력

| 종목 | 좋은 회사인가 | 좋은 주식인가 | 지금 살 가격인가 | 이 포트에 넣을 가치 | 투자순위 | 행동 | 목표비중 |
|---|---|---|---|---|---|---|---:|
| NVDA | 미검증 | 미검증 | 미검증 | 공통 입력으로 차단 | 미산출 | WAIT | 0% |
| EME | 미검증 | 미검증 | 미검증 | 공통 입력으로 차단 | 미산출 | WAIT | 0% |
| 000660 | 미검증 | 미검증 | 미검증 | 공통 입력으로 차단 | 미산출 | WAIT | 0% |

자금 100%는 `cash_is_unallocated_fallback=true`인 **미배정 연구자금**이다.
실제 계좌 리밸런싱이 아니며 1억원 가정 외 계좌 정보는 사용하지 않았다.
세 종목의 차단 코드: financials:unverified, price:missing, risk:missing,
thesis:unverified, scenario:missing. 공통 차단은 FX 미확인과 regime 미확인이다.
기대수익·손실확률·1/3/6개월 전망은 null이다. 5+2 실데이터 확대를 중단했다.

설정상 제약은 단일 20%, 국가 US 75%/KR 40%, 산업 40%/테마 50%/공통고객 40%,
ADV20 참여 1%, 주관적 스트레스 손실 25%, 신규 순기대수익 15%/보유 8%,
no-trade 2%p/교체 개선 buffer 3%p다. 편도 비용 US 15bp/KR 25bp는 연구 가정이며
확인된 세율이 아니다. gross cap은 regime에 따라 40~90%, UNKNOWN은 0%다.
실제 위험·비용 산출은 입력 부족으로 미평가이며 설정 한도를 충족한 실전 포트로
표시하지 않는다. MDD 25% 보장은 없다. 종목 수를 국가 비중 5:2로 변환하지 않는다.

## 실행 명령·테스트·산출물

아래는 최종 실행 코드 `07f976263481047e50bedae6349ede3e6a2292fc`에서 실제 실행한 명령이다.

```bash
cd /workspace/scratch/a006f1d2e538/r1000-quant-engine
PYTHONWARNINGS=ignore PYTHONPATH=/workspace/scratch/a006f1d2e538/run287-hotfix-venv/lib/python3.12/site-packages python research/decision_v1/reproduce_checks.py --kr-root /workspace/scratch/f247432c1548/kr-quant-engine
```

재현 스크립트가 각 시장 exporter와 consumer를 실행한다. 정확한 개별 명령·
입력 경로·exit code·파일 SHA256은 [connection_verification.json](evidence_20260907/executions/07f976263481047e50bedae6349ede3e6a2292fc/connection_verification.json)에 있다.
필수 데이터 오류를 exit 0으로 바꾸지 않았다.

| 검사 | 결과 |
|---|---|
| H1 data smoke | 19개 통과: 시점·원가격/조정·FCF·결측/0·synthetic·안전한 입력/저장 |
| H2 decision smoke | 16개 통과: 시나리오·환율·순위·민감도·현금/비용·기존 보유·변경 원인 |
| KR export pin smoke | 4개 통과 |
| 기존 US daily research monitor | 초기 구현 검증 19개 통과; 이후 모니터 수정 없음 |
| 보호 inventory/lineage | 최종 pin의 직접 관련 4개 회귀검사 통과 |
| 실제 2+1 CLI | export/consumer exit 2; 동일 실행 두 번의 결정·파일 해시 일치 |
| 합성 3/7 CLI | exit 0; 반복 동일, 비중+현금=1, 7개 fixture에서만 5+2 확인 |
| 전체 로컬 inventory | 과거 promisor blob 324e84859be5dddf091b165f9533259354739077의 HTTP 403으로 미완료 |
| US H1 선행 f2fdc859 CI | job 101769790608, 229/229 통과; 최신 HEAD 결과로 대체 해석하지 않음 |
| KR 최신 CI | source-pin·quick 23·full 44 통과. 기존 PIT 3/7 통과, 상장 이력 캐시 부재로 4개 실패; 후속 단계 skip |

최신 소스 package hash: `ddef2ed477b641d51994fbd575a6a17f7f701f2aefa982452fd7ae5deebe7680`

고정 설정 hash: `c5e3f22852a3c59c6b8aa1b21e9829990c0ba6230af07b6548bac7284c6db9bf`. 최초 설정은 출력 전에 local commit
`a4b5d8c06225823a4af93da638053c053d71c1dc`에 저장했고 결과를 보고 계수를 조정하지 않았다.

실제 결정 hash: `2caf4994a421a59c89c330687efdf108b6a797a51197cfe4fbbe208a9c6f0160`

- [실제 report.md](evidence_20260907/executions/07f976263481047e50bedae6349ede3e6a2292fc/REAL_PILOT/report.md)
- [실제 report.json](evidence_20260907/executions/07f976263481047e50bedae6349ede3e6a2292fc/REAL_PILOT/report.json)
- [실제 coverage](evidence_20260907/executions/07f976263481047e50bedae6349ede3e6a2292fc/REAL_PILOT/data_coverage_snapshot.json)
- [실제 evidence snapshot](evidence_20260907/executions/07f976263481047e50bedae6349ede3e6a2292fc/REAL_PILOT/research_evidence_snapshot.json)
- [실제 portfolio proposal](evidence_20260907/executions/07f976263481047e50bedae6349ede3e6a2292fc/REAL_PILOT/portfolio_proposal_research.json)
- [검증 receipt](evidence_20260907/executions/07f976263481047e50bedae6349ede3e6a2292fc/validation_receipt.json)
- [이전 코드와 artifact 비교](evidence_20260907/executions/07f976263481047e50bedae6349ede3e6a2292fc/artifact_comparison.json)

이전 88d4dfa 실행과 원본 입력·설정·context·행동·비중·차단 사유가 같다.
H1 추가 검증의 provenance 오류 표시 때문에 export/decision hash만 달라졌다.
같은 현 코드 안에서의 반복은 모두 동일하다. 순위 변화 원인은 가격·실적·추정치/
시나리오·thesis·위험·결측과 peer/config/context로 분리하며 수집시각만 바뀐 경우는
`evidence_provenance`다. 실제 표본은 최초 관찰로 순위 변화 이력이 없다.

합성 보고서는 같은 execution 폴더의 SYNTHETIC_3/SYNTHETIC_7 아래에 별도 보존한다.
현재 원본 응답으로부터의 유효 투자순위, OOS 성과, 통계 보정은 산출하지 못했다.

## 다음 작업과 중단 조건

1. PR #399/#400/#2의 현재 HEAD, 외부 review 완료 여부·열린 thread·CI를 먼저 확인한다.
   검토 지적은 fixture→최소 수정→검증→같은 입력 재실행으로 처리한다. 기존 사용자
   CSV 변경을 보존하고 unrelated PR 파일을 동시에 수정하지 않는다.
2. 기존 earnings artifact/가격 캐시의 **읽기 가능한 동일 원본**을 확보하고 원본 해시를
   대조한다. 기존 Alpaca/FMP/DART/KRX collector 계약에 맞는 작은 H1 materializer를
   추가한다. 원본 응답이 없으면 status를 available로 올리지 않는다.
3. NVDA·EME·000660의 최신 가격/행사/benchmark, TTM·순부채·희석주식수·FCF와
   시간대·공개시각을 채운다. thesis의 병목·고객·경쟁·촉매·강한 반대논리와
   가정별 시나리오 출처, FX·regime을 대사한다. 입력 오염 시 해당 결정만 차단한다.
4. 같은 2+1 실데이터 연결이 검증된 뒤에만 검증 가능한 후보 범위로 확대하여 5+2와
   현금을 제안한다. 숫자를 맞추기 위해 약한 후보를 넣거나 임의 확률/추정 이력을 만들지 않는다.
5. OOS는 별도 역사적 PIT snapshot·universe·성숙 outcome·비용 포함 설계 후 수행한다.
   현재 시나리오를 과거 consensus로 사용하지 않는다. V1 stress를 MDD 실증으로 바꾸지 않는다.

즉시 중단/보류: 필수 출처·단위·통화·공개시각·가격조정·해시가 불명확하거나 충돌,
의존 HEAD의 예기치 않은 변경, 실제 보유 미대사, 주문/공식 장부/승격을 요구하는 경로,
유료 구매·키 생성 필요. 같은 실패한 다운로드를 무작정 재시도하지 않는다.
optional ownership/news/options 미완성만으로 기본 시스템을 멈추지 않는다.

별도 승인 없는 병합·fullrun·운영복구 migration·모델/정책 승격·새 스케줄·공식 장부
변경·실전 주문·유료 구매/키 생성은 계속 범위 밖이다.
