# Run287 latest-close execution prompt — 2026-07-27

아래 프롬프트는 현재 작업트리와 승인 원장을 보존하면서 최신 완료
NYSE 종가 성과를 일일 산출물에 연결하기 위한 실행 지시다.

```text
H:\codex\r1000_run287_closeout_20260707 기존 폴더와 기존 작업트리를
그대로 사용해. 새 작업트리를 만들지 마.

현재 브랜치는
codex/run287-latest-close-performance-20260727 이다.
먼저 git status와 diff를 확인하고 다음 사용자 소유 untracked 파일은
수정·삭제·커밋하지 마.

- .github/workflows/run287_selective_breakdown_challenger_daily.yml
- docs/CODEX_HANDOFF_GPT56_20260710.md
- docs/CODEX_RUN287_GPT_PRO_REVIEW_HANDOFF_20260715.md

목표:

1. 2026-07-10 고정 Full 백테스트 수치를 “역사적 승인 기준”으로만
   유지한다.
2. 매 완료 NYSE 세션마다 승인된 exact-close paper 원장의 실제
   운용 성과를 별도로 계산한다.
3. durable chronological catch-up mark는 현재 운용 수익률/MDD에는
   포함하되 forward promotion 표본에서는 계속 제외한다.
4. 역사적 종료자산과 paper index를 연결한 최신 종가 CAGR은
   진단값으로만 표시한다.
5. 전체 역사 equity curve가 없으므로 결합 MDD는 exact라고 표시하지
   말고 bound/limitation을 명시한다. 역사 MDD와 paper 운용 MDD는
   각각 별도로 보존한다.
6. scorecard, user_current, public dashboard의 as-of 날짜가
   LAST_NYSE_SESSION_DATE와 다르면 게시를 fail closed 한다.
7. stale fallback, prior-close masquerading, 자동 promotion,
   production mutation, live trading을 금지한다.

현재 검증된 상태:

- 마지막 승인 paper 원장: 2026-07-23
- Main paper: $100,000 → $99,033.0078,
  누적 -0.966992%, paper MDD -2.275338%
- Concentrated paper: $100,000 → $96,098.2395,
  누적 -3.901760%, paper MDD -15.720199%
- 2026-07-23까지 endpoint-chain CAGR 진단:
  Main 34.022623%, Concentrated 47.972732%
- 2026-07-24 실행 30194334376은 이전 master
  77eb8c3ab812662d5c2507424c98bf125194dd64에서 exact-close gate가
  차단했다. 그 뒤 exact-close refresh 복구 커밋들이 master에
  병합됐으므로 옛 실패를 최신 코드 실패로 간주하지 마.

구현 완료 기준:

- run287_operating_scorecard_smoke
- public_portfolio_dashboard_smoke
- user_current_research_notice_smoke
- daily_user_current_contract_smoke
- workflow_artifact_smoke
- git diff --check
- 변경 Python py_compile
- workflow YAML parse

모두 통과시 이 브랜치의 의도한 tracked 파일만 커밋하고 push한 뒤
draft PR을 연다. 리뷰와 필수 검사가 모두 통과한 경우에만 master에
병합한다.

병합 후 별도 승인 없이 fullrun을 실행하지 마. 최신 master에서
Daily Operating Selection Refresh를 1회 실행해 최신 완료 세션인
2026-07-24를 순차 처리하고 다음을 확인한다.

- exact close coverage 100%
- accepted paper summary as_of_date = 2026-07-24
- scorecard_trusted = true
- latest_close_performance.status =
  READY_LATEST_CLOSE_REVIEW_ONLY
- latest_close_performance.as_of_date = 2026-07-24
- user_current/10_latest_close_performance.json 존재
- public dashboard as_of_close = 2026-07-24
- accepted publication manifest 검증 통과

실행이 실패하면 이전 날짜를 최신으로 표시하거나 원장을 건너뛰지
말고 실패 단계와 산출물을 보존해. exact-close 또는 원장 연속성
문제를 수정한 뒤 동일한 2026-07-24 세션부터 다시 순차 재개해.

fullrun, production, live trading, 새 작업트리 생성은 금지한다.
PR #343의 U0 변경은 이 latest-close PR에 섞지 마.
```
