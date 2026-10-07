# R1000 NEW CHAT HANDOFF — 2026-10-07 KST

> **Purpose:** 새 일반 Chat / 새 에이전트 / Codex 복귀 후에도 이전 대화를 다시 설명하지 않고 R1000 작업을 정확히 이어가기 위한 durable handoff.
>
> **Start here:** 이 문서를 읽은 뒤 GitHub Issue #448의 최신 checkpoint와 PR #580 로드맵을 live로 대사한다.
>
> **This is coordination state, not investment/account authority.**

---

## 0. 새 채팅에서 가장 먼저 할 일

1. Repository `wscha231/r1000-quant-engine`의 **live master SHA**를 확인한다.
2. GitHub **Issue #448 최신 CURRENT CONTROL / TEMP_A0 checkpoint**를 읽는다.
3. Draft PR **#580**의
   `docs/R1000_MODULAR_CONTINUOUS_ROADMAP_20261007.md`
   를 읽는다.
4. 이 문서의 SHA/PR 상태와 live GitHub가 다르면 **live 상태 우선**이며 차이를 먼저 보고한다.
5. 같은 TASK_KEY / same causal path / active writer가 이미 있는지 확인한다.
6. 기존 코드·patch·receipt·test를 먼저 재사용한다. 새 framework/agent/watchdog/whole-system audit를 중복 생성하지 않는다.

새 채팅은 과거 chat summary만으로 merge/완료/경제검증을 주장하지 않는다.

---

# 1. 프로젝트 최종 목적

미국·한국·Multi-Asset에서 반복 가능한 alpha를 발굴해 **실전비용 차감 후 장기 복리수익률**을 최대화한다.

도전목표:
- Main 순 CAGR >= 35%
- Concentrated 순 CAGR >= 50%
- MDD magnitude <= 25%를 survival constraint로 관리

목표 달성을 위해:
- 동일 holdout 반복최적화 금지
- 위험한도 완화 금지
- 과도한 레버리지 금지

우선순위:

`Data/PIT integrity → execution feasibility → OOS net compound/alpha → winner capture/hold → catastrophic drawdown control → recovery/turnover/liquidity`

MDD 최소화 자체가 목적이 아니다. permanent loss·강제청산·복리 훼손 방지가 목적이다.

---

# 2. 투자판단 철학

핵심 흐름:

`Discovery/Leadership → ER/Thesis → Candidate Competition → Portfolio/Regime → Execution → Forward Learning`

분리해서 판단한다:
- 좋은 기업
- 좋은 주식
- 현재 가격
- 진입 타이밍
- portfolio fit
- 계속 보유할 가치

RS는:
- discovery
- rank
- entry/inflection
- warning

용도이며 단독 BUY/SELL 명령이 아니다.

기업/자산 평가:
- 산업 병목
- value capture
- moat
- 성장/이익/FCF 가속
- valuation / expectation gap
- 가격구조 / RS
- catalyst
- downside

가능하면 Bull/Base/Bear별 12/24개월 valuation, 1/3/6/12개월 ER, downside, counter-thesis, catalyst, thesis invalidation을 기록한다.

---

# 3. Winner 보유 / 교체 원칙

좋은 winner를 정상 변동성 때문에 조기매도하지 않는다.

단독 매도 근거로 부족:
- 단기 RS 약화
- 정상 조정
- 단순 목표가 도달
- 단기 valuation 부담
- 일회성 risk-off

축소/매도는 함께 본다:
- thesis
- estimate
- FCF
- moat
- valuation
- 중장기 RS
- liquidity
- concentration
- challenger opportunity

기존 winner에는 incumbent advantage / hysteresis를 적용한다.

교체 조건:

`Challenger expected utility - Incumbent expected utility`

가 아래를 충분히 넘어야 한다:
- fee
- tax effect
- spread
- slippage
- re-entry risk
- uncertainty margin

목표는 turnover 최소화가 아니라 **cost-after compound return 최대화**다.

---

# 4. Portfolio / Regime

미국주식·한국주식·원자재·BTC·ETH·현금은 동일한 위험조정 ER 체계에서 경쟁한다.

Regime:
- RISK_ON
- CAUTION
- RISK_OFF
- RECOVERY

RISK_OFF에서는 winner 자동청산보다:
- 신규 진입
- beta
- gross exposure
- common-risk concentration

을 먼저 낮춘다.

연구형 raw weight 개념:

`expected alpha × signal confidence × thesis confidence × upside asymmetry ÷ downside risk`

이후 correlation/liquidity/country/FX/theme/customer/commodity/rates/regime/cost를 반영한다.

---

# 5. Data / PIT / Authority

권위순서:

`Actual Broker Book → Approved Target/Portfolio → CURRENT_STATUS/[PROJECT_HANDOFF] → merged code/config → verified Artifact/Receipt → approved Thesis → chat summary`

다음을 fail closed:
- missing
- stale
- future
- conflicting
- synthetic where real admission required
- ineligible

시간을 구분:
- observation time
- public availability
- collection time
- decision time
- execution time

Corporate action / split / delisting / ADR / FX / holiday / 당시 universe를 반영한다.

Research Signal / Candidate / Model Proposal / Approved Target / Simulated / Paper / Actual Broker Book을 혼합하지 않는다.

CI green/hash만으로 데이터 최신성·투자승인·장부갱신을 주장하지 않는다.

---

# 6. Investment Plane 역할

- A0 = state/dependency/task/authority/dispatch
- A1 = Data/PIT
- A2 = Discovery
- A3 = ER/Thesis
- A4 = Macro/Regime
- A5 = Portfolio
- A6 = Independent QA READ_ONLY
- A7 = Ops/Publishing
- A8 = Learning/Experiment

권한 제한:
- A2: BUY/ER 확정 권한 없음
- A3: portfolio weight 권한 없음
- A5: broker-book mutation 자동권한 없음
- A7: investment judgment 변경 금지
- A8: auto-promotion 금지

C0/Codex coordinator는 A0 상위가 아니다.

---

# 7. 자동화 / 개발 원칙

우선순위:

`deterministic code/GitHub Actions → artifact reuse/SKIP_UNCHANGED → normal Chat → Work → Codex`

deterministic 처리 우선:
- SHA
- dedupe
- freshness
- RS calculation
- CI polling
- simple state transition

AI 사용:
- industry interpretation
- moat/thesis
- valuation
- catalyst
- causal analysis
- bounded strategy research

Risk classes:
- T0_READ
- T1_COMPUTE
- T2_PREPARE
- T3_REVERSIBLE_WRITE
- T4_ECONOMIC_MUTATION
- T5_IRREVERSIBLE_OR_PROTECTED

자동승인하지 않는 것:
- fullrun
- Approved Target
- paper/broker mutation
- live activation
- risk-limit relaxation
- protected gate changes

---

# 8. 병렬 작업 규칙

기본:
- L0/A0 coordinator 1
- Main Integration mutation lane 1
- Source/Data mutation lane 1
- READ_ONLY research/design 여러 개 가능
- A6 independent

같은 causal path를 여러 worker가 동시에 수정하지 않는다.

각 TASK는 최소:
- task_key
- owner
- base SHA
- dependency
- allowed files
- validation
- stop condition

을 가진다.

OPEN Draft PR 자체만으로 active writer lease를 영구 추론하지 않는다.
실제 owner/task/allowed path/checkout-index lease를 확인한다.

---

# 9. 현재 modular architecture

고정 공통 layer와 strategy layer를 분리한다.

```
admitted data/PIT
   ↓
Decision Context
   ↓
Strategy modules
  - discovery/leadership
  - fundamentals/thesis
  - return model
  - entry/add
  - hold/exit/reentry
  - macro/regime
  - allocation/replacement
   ↓
common execution/cost/accounting
   ↓
common evaluator/attribution
   ↓
experiment + forward outcome history
```

Strategy module은 accepted paper/public/broker/canonical state를 직접 변경하지 않는다.

---

# 10. Live repository checkpoint at handoff creation

Repository:
`wscha231/r1000-quant-engine`

Live master:
`6a2fa606896a2f263fffa07b9273d60f2d011626`

Reusable merged assets:
- #556 Earnings consensus/PIT
- #560 Candidate Registry reference index
- #574 long-history SQLite cleanup
- #575 estimate/source hooks
- #577 SEC-first reassessment bridge
- #578 E2 research NAV/evaluator
- #579 A7 recovery source fix

Existing reusable modules:
- `tools/run287_hold_exit_policy.py`
- `tools/run_strategy_logic_ledger.py`
- existing broker ledger replay / execution/accounting

Prepared research assets:
- Leadership v2 Drive package
- A4/Macro research assets; exact canonical source identity must be narrowed before G6 integration

---

# 11. G1 — DONE_VALIDATED / DRAFT_UNMERGED

PR:
**#582 — G1 all-LEGACY Control modular adapter**

Exact head:
`a37d50026850eb76e7454fa7ae02ad7a66d43319`

Base:
`6a2fa606896a2f263fffa07b9273d60f2d011626`

Result:
- all-LEGACY adapter
- Main15 / Concentrated5
- next_close
- integer shares
- initial capital $100,000
- 25 bps
- max fill lag 7
- native smoke normal 14/14 PASS, SKIP0
- native smoke Python -O 14/14 PASS, SKIP0
- real broker fixture direct vs adapter parity PASS
- positive fixture has BUY / SELL / fees / cash / NAV / positions
- missing-price negative case identical fail-closed
- PR Validation 37573898111 SUCCESS
- Portfolio Guard 37573898112 SUCCESS
- evaluate SUCCESS
- review_head_observed SUCCESS

Positive fixture:
Main:
- trades 8
- buys 4
- sells 4
- fees 891.8575000000001
- ending cash 10179.142500000009
- equity 105869.14250000002
- positions 2

Concentrated:
- trades 8
- buys 4
- sells 4
- fees 890.0675
- ending cash 10124.932499999995
- equity 105184.9325
- positions 2

Boundary:
- BROKER_FIXTURE_PARITY complete
- R0_FULL_CONTROL_PARITY NOT_RUN
- fullrun/economic comparison NOT_RUN
- G2/G3 not applied
- #582 remains Draft/unmerged
- review_complete expected blocked until maintainer/current-head independent review evidence

G1 additional economic logic work is not needed now.

---

# 12. G2 — BINDING_PREPARED / DRAFT_UNMERGED

PR:
**#581 — Hold/Exit/Replacement module prep**

Head:
`b1eabe64bbb9e0665680830e13be80b6195830c7`

G2 core prep remains Draft/unmerged and its code checks are green.

A local G1↔G2 binding package has now been prepared and independently inspected.

Binding bundle:
- ZIP SHA256 `816b99efd0dd92b4168c68f32395ecbca4aad6caedfa7ff13f75ebc558784db2`
- patch SHA256 `e083b37acd2fc68d7e0db8cb862cfaba1f8a9b52a3cf860e60e50399b00afc41`
- binding source SHA256 `cb63a1d165460902f25e234fb3e0b325c75f98e01a19f664880a52950cc1c9a9`
- smoke SHA256 `3b69e2a5c2aaddf634233242cd9ac3785f446c4cfe68cbe7fd23a455dde47537`
- local normal 10/10 PASS
- local Python -O 10/10 PASS

Binding behavior:
- LEGACY path keeps exact G1 behavior and never loads G2
- G2 path builds unchanged Control first, then existing G2 treatment
- G2 is still a post-Control overlay, not proven full replacement
- only minimum_score_gap is a candidate axis
- exact module/version/policy/config/hash required
- explicit PIT scored cache and lifecycle identities required
- G2 direct full-run/broker execution is blocked until treatment target materialization is explicit

Still NOT_RUN:
- exact combined-tree native CI
- treatment-book materialization into isolated broker replay
- R0
- R1
- economic comparison

Next:
**native combined-tree integration validation**. Do not jump directly to R0 materialization.

---

# 13. G3 — PREPARED_LOCAL_REPORTED

Goal:
Strategy Difference / Attribution reporter.

Reported local patch:
`R1000_G3_Strategy_Difference_Reporter_PREP_20261007.patch`

Reported SHA256:
`80b8e2a8e9b9775dbbe36fa1933e363cf48876f0328e0f054c9e5a5193df6f54`

Proposed files:
- `tools/strategy_difference_reporter.py`
- `tests/strategy_difference_reporter_smoke.py`

Reported local test:
- 12 PASS
- py_compile PASS

No GitHub branch/PR yet.

Must reuse existing replay outputs:
- trades.csv
- holdings_daily.csv
- cash_ledger.csv
- equity_curve.csv
- metrics.json

Must not invent:
- new evaluator
- NAV engine
- backtester
- missing turnover
- causal attribution without evidence

Before native integration, obtain/preserve actual G3 patch bytes.

---

# 14. G4 / G5 / G6

## G4 SEC ACTUAL
Reuse #577 + Companyfacts/fundamental normalization + A0/A3/Registry.

First intended trace:
retained MSFT ACTUAL
→ normalized comparison
→ reassessment bridge
→ A0-compatible task
→ A3 verdict
→ Registry ref/readback

No new SEC collector.
Do not recollect exhausted Source3 allowance.
Unknown freshness/expiry stays unknown.

## G5 Leadership v2
Reuse existing Drive ZIP:
`R1000_LEADERSHIP_V2_H1_NATIVE_REVIEW_20261003.zip`

Do not rewrite.
Port/rebase to current master and preserve A3/Registry contracts.
Discovery is research input only, no BUY/SELL/weight authority.

## G6 Macro
Reuse existing A4/Macro work and Lake/#574.
First narrow actual canonical artifact/source identity.
Start with a small set of genuinely PIT-admissible indicators.
Macro does not directly choose stock weights.

---

# 15. Current integration order

Current L0/TEMP_A0 decision:

`G1 DONE → G2 binding PREPARED → G2 native integration validation → G3 binding → R0 → R1 → G5/G4/G6 increments → ER/A5 → forward/shadow`

Important:
- G2 remains default OFF / LEGACY for R0.
- Native combined-tree validation must pass before treatment-book materialization wiring is authorized.
- G3 binding should explain differences, not generate economic outcomes.
- R0 = pure all-LEGACY direct Control vs modular all-LEGACY Control.
- R1 = one hold/replace hypothesis changed, same data/execution/evaluator.

---

# 16. R0 / R1 definitions

## R0 Control parity
Expected alpha delta = 0.

Compare:
- candidates/intents
- target/positions
- weights
- orders/fills
- cash
- fees/cost
- NAV
- account state
- reason codes

R0 is broader than the completed small broker fixture parity.

## R1 Hold/Replace
Change exactly one G2 hold/replacement hypothesis.
Keep:
- discovery
- entry
- allocation
- regime
- execution
- evaluator

fixed.

Measure:
- winner retention
- early exits
- re-entry
- replacement effect
- holding duration
- missed upside
- overholding deterioration
- turnover
- costs
- NAV
- CAGR
- MDD

Do not tune parameter to hit target CAGR.

---

# 17. A7 publication recovery

A7 is a separate legacy operation lane.

Do not make A7 recovery a blanket blocker for G1-G6 modular research.
Do not replay transactions already reflected in ledger.
Publication/paper durable mutation still requires its existing authority/readback gates.

---

# 18. Model routing / quota policy

User preference:
**Conserve Pro calls; use Extra High by default when sufficient.**

Every significant task instruction should state:

```
RECOMMENDED_MODEL:
<Extra High | Pro>

WHY:
<why this level is sufficient>

PRO_BUDGET_PRIORITY:
LOW | MEDIUM | HIGH | CRITICAL
```

Default use:
### Extra High
- GitHub live state/SHA/CI reconciliation
- bounded implementation
- small multi-file patches
- test writing
- defined module integration
- routine failure diagnosis
- handoff/roadmap update

### Pro
reserve for:
- difficult multi-causal native failures
- PIT + execution + accounting interactions that remain unresolved
- complex multi-PR integration conflicts
- economically material strategy design decisions
- final exact-head independent review
- high-cost architecture decisions

Do not spend Pro simply because a task contains code.

If Extra High succeeds, do not redo the same task in Pro.

---

# 19. Codex / Work policy

Codex should be used later for:
- exact-current rebase/integration
- difficult native correction
- full required regression
- exact-head independent review
- permitted merge
- economic execution/verification where justified

Do not ask Codex to rediscover/rebuild work already prepared by normal Chat.

Work is for genuinely large multi-file implementation/research, not routine coordination.

---

# 20. Shared task packet

Every new task should contain:

```
TASK_KEY:
PARENT:
ROLE:
MODE:
RECOMMENDED_MODEL:
PRO_BUDGET_PRIORITY:
BASE_SHA:
DEPENDENCIES:
ALLOWED_FILES:
READ_ONLY_FILES:
INPUTS:
OUTPUT_CONTRACT:
TESTS:
STOP_CONDITION:
AUTHORITY:
NOT_AUTHORIZED:
RETURN_TO: #448
```

Worker completion:

```
TASK_KEY:
STATUS: DONE | PARTIAL | BLOCKED | SUPERSEDED
BASE_SHA:
HEAD_SHA_OR_PATCH_ID:
FILES_READ:
FILES_CHANGED:
TESTS_RUN:
CI:
OUTPUT_REFS:
REUSED_EVIDENCE:
NOT_RUN:
BLOCKERS:
NEXT_RECOMMENDED:
AUTHORITY_NEEDED:
```

If worker has GitHub write permission, post one compact #448 update.
Otherwise return block to TEMP_A0 for one-time posting.

---

# 21. Do-not-repeat rules

Do not:
- create another system-wide plan if #580 + this handoff are sufficient
- create new backtester/evaluator/Registry/scheduler without proving existing one cannot be reused
- run same holdout repeatedly to optimize target CAGR
- convert missing data to neutral/zero
- infer active writer merely because Draft PR is open
- use old CI for a new head
- treat green CI as economic validation
- call a local synthetic pass production approval
- mix Control/C1 frozen experiment with new modular experiments
- let G2/G3 silently modify R0 all-LEGACY arm
- claim G3 causal attribution without row-level evidence
- make A7 a global blocker for modular research

---

# 22. Current immediate next task

**G2 native integration validation**.

Recommended model:
**GPT-5.6 Sol Extra High**

Pro budget priority:
**LOW**

Reason:
bounded exact-tree integration and regression validation; no new alpha logic or economic run.

Required:
- exact G1 #582 head
- exact G2 #581 head
- exact prepared G2 binding patch
- one isolated integration-validation tree
- binding smoke normal/-O in dependency-complete environment
- existing G1/G2 native regressions and required CI
- LEGACY remains default
- no treatment-book materialization yet
- no R0/R1 yet
- no merge/Ready/Codex/paper/broker/public/live mutation

If clean:
1. TEMP_A0 records native binding validation
2. G3 binding task
3. then R0 all-LEGACY parity
4. only after R0, R1 hold/replace experiment

---

# 23. Exact new-chat startup text

새 채팅에 다음만 붙이면 된다:

```
@GitHub

R1000 TEMP_A0/L0 continuation.

Do not create a new whole-system plan.

First read:
1. GitHub Issue #448 latest checkpoint
2. PR #580:
   docs/R1000_NEW_CHAT_HANDOFF_20261007.md
3. PR #580:
   docs/R1000_MODULAR_CONTINUOUS_ROADMAP_20261007.md
4. live master and relevant active PR heads

Treat live GitHub as fresher than this prompt.

Preserve the existing authority hierarchy, PIT fail-closed rules,
winner-hold/replacement philosophy, Main1/Source1 mutation discipline,
and research-vs-paper-vs-broker separation recorded in the handoff.

Use Extra High by default for bounded implementation/integration.
Recommend Pro only when the expected quality gain justifies the limited quota,
and state PRO_BUDGET_PRIORITY.

Current expected sequence:
G1 DONE → G2 binding → G3 binding → R0 → R1.

Before acting, reconcile whether this sequence has already advanced.
Do not repeat completed work.

Return only:
CURRENT_LIVE_STATE
DELTA_FROM_HANDOFF
ACTIVE_TASK
BLOCKERS
NEXT_ACTION
RECOMMENDED_MODEL
PRO_BUDGET_PRIORITY
```

---

# 24. Handoff freshness rule

This handoff is a durable starting point, not an immutable truth.

On every new chat:
- live master may have moved
- PR heads may have moved
- G2/G3/R0 may already be completed

Therefore always compare against live GitHub before issuing new work.

When material state changes, update:
1. Issue #448 checkpoint
2. PR #580 roadmap
3. this handoff when the change affects future chat continuity

Do not update this file for trivial CI polling noise unless it changes the next action.
