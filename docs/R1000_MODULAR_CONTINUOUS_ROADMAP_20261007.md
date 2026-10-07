# R1000 Modular & Continuous Development Roadmap — 2026-10-07

> Status: **COORDINATION / T2_PREPARE / RESEARCH_ONLY**
>
> Purpose: cross-chat / agent coordination during the Codex-unavailable period and the following native integration phase.
>
> This document does **not** replace canonical authority:
> Actual Broker Book → Approved Target/Portfolio → CURRENT_STATUS/[PROJECT_HANDOFF] → merged code/config → verified artifacts/receipts → approved thesis → chat summary.
>
> Central progress ledger: **GitHub Issue #448**.
> New-chat durable handoff: **`docs/R1000_NEW_CHAT_HANDOFF_20261007.md`**. New chats/agents should read this handoff first, then reconcile live #448/master/PR state.
> Every task should read this document + the latest relevant #448 checkpoint before starting, and should return a compact completion/update record to #448 when possible.

## 1. Program objective

Build an investment backend that can:

1. discover large future winners earlier;
2. distinguish good company / good stock / current price / entry timing / portfolio fit;
3. hold winners through normal volatility while detecting real thesis deterioration;
4. compare incumbent vs challenger after costs, re-entry risk, uncertainty, correlation and liquidity;
5. switch or combine strategy modules without rewriting the whole engine;
6. evaluate strategies with the same PIT/data/execution/accounting environment;
7. continue ingesting new data, updating forward outcomes and evaluating strategy performance as time advances;
8. keep research, model proposals, paper, actual broker state and publication authority separate.

Research targets remain:
- Main net CAGR >=35%
- Concentrated net CAGR >=50%
- MDD magnitude <=25% as a survival constraint

Targets are not guarantees and must not be achieved by repeated holdout tuning or risk-limit relaxation.

## 2. Current verified repository checkpoint

Repository: `wscha231/r1000-quant-engine`

Master observed at creation of this roadmap:
`6a2fa606896a2f263fffa07b9273d60f2d011626`

Important merged/reusable assets:
- #556 earnings consensus / PIT admission
- #560 Candidate Registry reference index
- #574 long-history SQLite cleanup
- #575 FMP/EODHD source hooks
- #577 SEC-first reassessment bridge
- #578 E2 bound research NAV/evaluator
- #579 A7 publication-recovery source fix
- `tools/run287_hold_exit_policy.py`
- `tools/run_strategy_logic_ledger.py`

Important prepared but not fully integrated/economically validated assets:
- Drive package: `R1000_LEADERSHIP_V2_H1_NATIVE_REVIEW_20261003.zip`
- A4 Macro Transmission V2 research package/results

Do not reimplement these from scratch.

## 3. Temporary operating mode while Codex is unavailable

For the current 5–6 day Codex-unavailable window:

- normal ChatGPT may read the current GitHub source, prepare code, tests and isolated Draft PRs;
- existing GitHub CI may be reused when it is triggered by normal Draft-PR behavior;
- Codex is reserved for later rebase/integration, difficult native corrections, full regression and exact-head independent review;
- no new orchestrator, scheduler, backtester, canonical Registry, ledger or evaluation engine is created;
- Main mutation writer = max 1;
- Source/Data mutation writer = max 1;
- READ_ONLY research/test design may run in parallel;
- same file / same causal path is not edited concurrently.

This temporary control room does not supersede canonical A0/C0.

## 4. Modular architecture

The fixed/common layer and strategy layer must be separated.

```
[admitted data / PIT / identity / CA / delist / FX]
                      |
                      v
              [Decision Context]
                      |
          +-----------+-----------+
          | strategy recipe       |
          |                       |
          | discovery/leadership  |
          | fundamentals/thesis   |
          | return model          |
          | entry/add             |
          | hold/exit/reentry     |
          | macro/regime          |
          | allocation/replacement|
          +-----------+-----------+
                      |
                      v
       [common execution / cost / accounting]
                      |
                      v
          [common evaluator / attribution]
                      |
                      v
        [experiment & forward outcome history]
```

Strategy modules must not directly mutate accepted paper, public, broker or canonical state.

## 5. Execution roadmap

### G1 — Legacy Control modular adapter
Goal: wrap the existing Control with the thinnest possible recipe/spec boundary.

First acceptance test:
legacy direct call == modular call for:
- candidates/intents
- positions
- weights
- orders/fills
- cash
- costs
- NAV
- reason codes

No alpha change is expected in G1.

### G2 — Hold / Exit / Replacement module
Reuse:
- `tools/run287_hold_exit_policy.py`
- `LeadershipPersistencePolicy`
- existing sell taxonomy / lifecycle / PIT / risk checks

Do not create a new strategy from scratch.

Expose the existing policy through stable module identity/version/config.
First research comparison changes exactly one hold/replacement hypothesis while discovery, entry, allocation, regime and evaluator remain fixed.

Measure:
winner retention, early exits, re-entry, replacement effect, holding duration, missed upside, overholding deteriorated names, turnover, costs, NAV, CAGR, MDD.

### G3 — Strategy Difference / Attribution reporter
Reuse and extend:
- `tools/run_strategy_logic_ledger.py`
- existing replay/evaluator outputs

Do not create a new NAV engine or backtester.

Track where possible:
- parent strategy
- changed module/version
- first divergence session/asset/reason
- candidate-only entries/exits/retentions
- replacement events
- holding-duration delta
- trade/turnover delta
- cost delta
- cash delta
- NAV delta
- existing evaluator CAGR/MDD delta
- winner-capture / early-exit / re-entry attribution where evidence exists

Missing evidence remains NULL / NOT_AVAILABLE.

### G4 — SEC ACTUAL thin trace
Reuse #577 + existing Companyfacts/fundamental normalization + existing A0/A3/Registry.

First trace:
retained MSFT raw
→ normalized ACTUAL comparison
→ reassessment bridge
→ A0-compatible task
→ A3 verdict
→ Registry reference/readback

Do not create another SEC collector/A3/Registry.
Do not recollect the already exhausted Source3 allowance.
Unknown expiry/freshness stays unknown.

### G5 — Leadership v2 current-master port
Reuse the Drive package rather than rewriting:
- `research/leadership_diagnostics_v2.py`
- `research/a3_leadership_review_v2.py`
- related tests/docs/patch

Tasks:
1. compare old package base to current master;
2. identify dependency drift;
3. port the smallest compatible patch;
4. preserve current A3/Registry contracts;
5. run the existing synthetic/native-adjacent tests;
6. prepare an isolated Draft PR if the lane is free.

Discovery remains research input, not BUY/SELL/weight authority.

### G6 — Macro minimum admissible module
Reuse A4 Macro Transmission V2 + existing Lake + #574.

Do not start by completing every macro family.
Select only a small set of genuinely admitted/PIT-usable inputs first.

Possible initial families:
rates, real rates, credit spreads, liquidity, VIX/breadth, USD, oil/copper.

Outputs:
- regime
- gross/risk/cash budget evidence
- source-based industry transmission evidence

Macro does not independently determine stock weights.
The same macro effect must not be double-counted in ER and allocation.

## 6. Economic validation sequence

R0 — Control parity
- existing Control vs G1 modular Control
- expected alpha delta = 0

R1 — Hold/replace experiment
- one module changed
- common data/execution/evaluator

R2 — Leadership discovery experiment
- historical candidate denominator required
- no survivor-only discovery claim

R3 — Macro incremental experiment
- fixed alpha/selection where appropriate
- measure risk reduction and lost upside/re-entry effects

Then:
validated ER V2
→ A4 risk
→ A5 Main/Concentrated
→ frozen Control/challenger economic comparison
→ approved shadow/forward evaluation

The original Control/C1 frozen comparison remains separate from new modular experiments.

## 7. Continuous operation design

After an approved strategy version exists, the system should advance without changing the frozen historical experiment.

Separate:
1. frozen backtest;
2. forward performance extension with the same strategy/version;
3. new strategy-version validation.

Normal daily/weekly operation should use deterministic code for:
- source freshness / identity / duplicate checks
- incremental data ingestion
- feature updates
- state transitions
- order/accounting calculations
- forward-outcome maturity
- performance extension
- receipt/hash/status generation

AI is used for:
- industry/moat/thesis interpretation
- new event interpretation
- hypothesis design
- bounded policy research

Daily continuation must be based on last successfully completed session/receipt, not on calendar assumptions alone.

A new code merge must not silently replace an approved strategy version.

## 8. Existing A7 recovery is a separate lane

A7 publication/paper recovery is independent from modular research.

Do not replay the already reflected Jul-27 transaction.
Do not make full A7 recovery a blanket prerequisite for G1–G6 research.

A7 durable/publication actions still require their existing authority, exact source, namespace and readback gates.

## 9. Shared task protocol

Before starting a task, the worker should read:
1. this roadmap;
2. latest relevant #448 checkpoint;
3. current master/base SHA;
4. relevant PR/branch;
5. applicable `AGENTS.md` and existing contracts.

Every task packet should include:

```
TASK_KEY:
PARENT:
ROLE:
MODE:
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

Every worker should return:

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

If the worker can write GitHub, post a compact update to #448.
If not, return this exact block so TEMP_A0/current coordinator can post it once.

## 10. Order / duplication control

Before issuing any new order, check:
- Is the same TASK_KEY already active?
- Is there an active owner on the same causal path?
- Is Main writer already leased?
- Is Source/Data writer already leased?
- Does a merged/native implementation already exist?
- Can a previous receipt/hash/test result be reused?
- Did base/master move?
- Does the task depend on a not-yet-integrated upstream?

If unchanged, do not create another worker, watcher, whole-system audit or repeat plan.

## 11. Current progress board

At roadmap creation:

DONE / reusable:
- #556
- #560
- #574
- #575
- #577
- #578
- #579
- existing hold/exit policy
- existing strategy logic ledger

PREPARED / not fully integrated:
- Leadership v2 package
- Macro Transmission V2 package/results

ACTIVE:
- G1 legacy-Control modular adapter: DONE_VALIDATED / Draft PR #582 head `a37d50026850eb76e7454fa7ae02ad7a66d43319`; native smoke normal/-O 14/14 PASS, SKIP0; real broker fixture direct↔adapter parity PASS; R0 full-Control parity still NOT_RUN
- G2 hold/exit binding: NATIVE_VALIDATED / Draft PR #583 head `f7bd98b43209b4cebb0e0c78f17963b6aba3795d`; binding normal/-O 10/10 PASS SKIP0; G1/G2 native regressions PASS; required current-head CI green; treatment materialization/R0 NOT_RUN
- G3 strategy-difference reporter: NATIVE_VALIDATED / Draft PR #584 head `451b67cfb132921088b73a883f03116417b85fa6`; native normal/-O 16 PASS; read-only replay consumer; R0/R1 NOT_RUN
- G1 remains the authoritative shared routing/interface contract before G2/G3 native integration

LATER:
- G5 Leadership port
- G4 SEC ACTUAL trace
- G6 minimum Macro module
- R0/R1/R2/R3
- validated ER/A5
- modular combinations
- forward/shadow continuation

SEPARATE:
- A7 durable recovery/publication

## 12. Codex handoff rule

When Codex becomes available again, do not ask it to rediscover or rebuild the above.

Handoff should contain:
- current master
- Draft PR/branch heads
- changed files
- interface contracts
- passing/failing tests
- CI refs
- known blockers
- dependency/merge order
- exact economic experiments ready/not-ready

Codex role:
rebase → integrate → difficult native correction → required full regression → exact-head independent review → permitted merge → economic execution/verification.

## 13. Completion criteria

Do not call the modular system complete until:

1. legacy vs modular Control parity exists;
2. one changed module produces reproducible holdings/actions/cash/cost/NAV differences;
3. the first divergence and downstream causal path are explainable;
4. same spec reruns reproduce results;
5. a later eligible session can be processed with the same approved strategy version;
6. data updates invalidate/recompute only affected dependencies;
7. forward outcomes/performance continue to mature without rewriting history;
8. production/paper/public/broker authority remains separate.

The optimization target is not PR count or review count. It is better winner discovery, better entry, longer correct winner holding, fewer bad replacements, lower unnecessary cost, controlled permanent-loss risk and a sustainable repeatable research/operation loop.


## 11.1 A0 live checkpoint — 2026-10-07

Latest TEMP_A0 live reconciliation (source: user-returned A0 checkpoint):

- current master: `6a2fa606896a2f263fffa07b9273d60f2d011626`
- #556/#560/#574/#575/#577/#578/#579: merged
- existing hold/exit policy and broker replay/evaluator are present
- existing strategy ledger does not yet contain first-divergence/module-delta attribution
- Leadership v2 Drive ZIP exists (74,464 bytes) and must be ported from its older base rather than applied blindly
- the exact single canonical artifact named `Macro Transmission V2` was not located in that live A0 search; macro assets must therefore be narrowed by actual file/source identity before G6 integration
- #573 remains an open Draft on an A0/control-plane causal path
- #572 remains an open Draft on an estimate/source-data causal path

Operational consequence:

1. Do not open another remote Main or Source/Data mutation lane yet.
2. G1/G2/G3 may all advance as **local/code-diff/test preparation** because that does not consume a remote mutation lane.
3. G2/G3 must stay interface-conservative: reuse current callers/types and do not create a global StrategySpec/DecisionContext/evaluator framework.
4. G1's all-legacy parity adapter becomes the authoritative shared module-routing contract before native integration.
5. Leadership v2 READ_ONLY port analysis may run in parallel.
6. G6 Macro is not a blocker for G1/R0; first narrow exact reusable Macro source/artifact identity.

The G1 development packet produced by A0 is the current authoritative G1 task definition. It is structural parity only: no strategy change, no G2/G3 feature insertion, no workflow/fullrun/paper/broker/Drive mutation.


## 11.2 G2/G3 preparation checkpoint — 2026-10-07

### G2
- task: `R1000-G2-HOLD-EXIT-MODULE-PREP-20261007`
- status: `G2_CODE_PREPARED / DRAFT_PR_OPEN / FINAL_CI_PENDING`
- Draft PR: #581
- head: `b1eabe64bbb9e0665680830e13be80b6195830c7`
- changed files: existing hold/exit policy + its smoke only
- existing caller unchanged
- bounded additions: module identity/config serialization/audit identity + one `minimum_score_gap` candidate helper
- Portfolio System Guard: PASS
- PR Validation: pending at checkpoint
- integration rule: keep Draft/no merge/no shared wiring until G1 contract and mutation-lane reconciliation

### G3
- task: `R1000-G3-STRATEGY-DIFFERENCE-REPORTER-PREP-20261007`
- status: `PREPARED_LOCAL / NO_REPOSITORY_MUTATION`
- reported patch: `R1000_G3_Strategy_Difference_Reporter_PREP_20261007.patch`
- reported SHA256: `80b8e2a8e9b9775dbbe36fa1933e363cf48876f0328e0f054c9e5a5193df6f54`
- proposed files: `tools/strategy_difference_reporter.py`, `tests/strategy_difference_reporter_smoke.py`
- existing strategy ledger remains unchanged
- reported local result: 12 tests PASS + py_compile PASS
- repository persistence/CI: NOT_RUN
- integration rule: wait for G1 IDs/refs and then bind replay refs/strategy identities; do not create a new evaluator/schema

Native integration order:
`G1 interface/parity → G2 binding → G3 binding → R0 → R1`.


## 11.3 G1 nonstub environment checkpoint — 2026-10-07

Task: `R1000-G1-NONSTUB-BROKER-PARITY-PREP-20261007`

Status:
`BLOCKED_ENVIRONMENT / ORIGINAL_BYTES_VERIFIED / NATIVE_PARITY_NOT_RUN`

Verified by the worker:
- original patch SHA256: `0f14c40c1ca64635a8b2f5fe85044b74e3b21061afef4b068842b1d740d45960`
- original ZIP SHA256: `172acb859f7d35719ff1d9d451d05f002e0fbd0548e1eea841fe19d517d6b063`
- ZIP patch and standalone patch are identical
- patch reconstruction matches original adapter/test source bytes
- product source changes in this follow-up: 0

Nonstub broker fixture parity:
- actual broker replay executions: 0
- fill/fee/cash/holdings/NAV comparisons: 0
- result: `BROKER_FIXTURE_PARITY = BLOCKED_ENVIRONMENT`

Observed isolated-runtime blockers:
- `pyarrow` missing
- `pandas_market_calendars` missing
- incomplete native source dependency tree, first observed as `ModuleNotFoundError: r1000_candidate_lanes`
- package-install attempt failed because the runtime could not resolve external package hosts

Do not reinterpret this as package incompatibility, missing repository implementation, or parity failure.

Next preferred path:
1. stop repeating dependency-install attempts in the same isolated chat runtime;
2. preserve exact G1 original bytes;
3. reconcile actual writer/lease once rather than inferring occupancy from open Draft PRs;
4. when remote preparation is allowed, apply only G1's two new files to an exact-current-master isolated Draft branch;
5. use the repository's existing dependency-complete CI/native environment for nonstub broker fixture parity;
6. require nonempty direct-vs-adapter economic outputs and exact comparable equality;
7. keep broker-fixture parity separate from full-history R0.

G2 is not part of all-legacy R0. A post-Control G2 treatment is an overlay until true module replacement is demonstrated.
G3 requires actual patch bytes plus comparable replay manifests before native wiring.


## 11.4 G1 exact-original Draft checkpoint — 2026-10-07

User supplied the four original G1 artifacts directly.

Verified identities:
- adapter SHA256 `fc422c209592ebc369e4ed4b2571a9956eb21f3fd76403a1a9489a30fabfda86`
- smoke SHA256 `e3fc046c3be48cf04cfed12e367eb11c5fc364a2b393186cc458b9af12c80bd9`
- original patch SHA256 `0f14c40c1ca64635a8b2f5fe85044b74e3b21061afef4b068842b1d740d45960`
- original ZIP SHA256 `172acb859f7d35719ff1d9d451d05f002e0fbd0548e1eea841fe19d517d6b063`
- ZIP members == standalone originals
- patch apply and source byte comparison: PASS

G1 Draft PR #582:
- base `6a2fa606896a2f263fffa07b9273d60f2d011626`
- head `92ffe3f2305a73b8e1d03e1f8565c33aaf11c128`
- net changed files: `tools/legacy_control_adapter.py`, `tests/legacy_control_adapter_smoke.py`
- adapter Git blob `759de0342c759c98ac5996b4433dcba3a1eca675`
- smoke Git blob `1eaf7cb7804129dde11ae4101444616ce54c88d2`
- those blob IDs equal local `git hash-object` of the supplied originals
- current-head generic `portfolio_guard` and `evaluate`: SUCCESS
- Draft `review_complete`: expected blocked

Important:
`tests/legacy_control_adapter_smoke.py` is not currently listed in master `tools/run_pr_validation.py` DEFAULT_TESTS. Generic green CI must not be reported as G1 smoke PASS.

Still NOT_RUN:
- G1 smoke in repository dependency-complete CI
- nonstub broker fixture parity
- full-history R0
- economic comparison
- merge/review approval

Any native-validation wiring should be the narrowest possible integration step and must not silently combine G2/G3 or broaden economic authority.


## 11.5 G1 native validation completion — 2026-10-07

G1 is now `DONE_VALIDATED / DRAFT_UNMERGED`.

PR #582 exact head:
`a37d50026850eb76e7454fa7ae02ad7a66d43319`

Verified live checks:
- PR Validation 37573898111: SUCCESS
- Portfolio Guard 37573898112: SUCCESS
- evaluate: SUCCESS
- review_head_observed: SUCCESS
- review_complete: expected BLOCKED while Draft and without maintainer/current-head Codex attestation

Accepted native fixture evidence:
- G1 native smoke normal 14/14 PASS, SKIP0
- G1 native smoke Python -O 14/14 PASS, SKIP0
- real broker replay direct vs adapter parity PASS
- Main15/Concentrated5, next_close, integer shares, $100k capital, 25bps, lag7 preserved
- positive fixture generates actual BUY/SELL/fees/cash/NAV/positions
- missing-price negative path matches fail-closed behavior

This is broker-fixture parity, not full-history R0.

Next integration order:
`G2 binding capability (default OFF/LEGACY) → G3 binding → R0 all-LEGACY full-Control parity → R1 hold/replace experiment`.

G1 #582 remains Draft/unmerged until review/attestation gates are available.


## 11.6 G2→G1 binding preparation — 2026-10-07

Task: `R1000-G2-BINDING-TO-G1-20261007`

Status:
`PREPARED_LOCAL_VERIFIED / NATIVE_INTEGRATION_NOT_RUN`

Bundle identities:
- ZIP SHA256 `816b99efd0dd92b4168c68f32395ecbca4aad6caedfa7ff13f75ebc558784db2`
- patch SHA256 `e083b37acd2fc68d7e0db8cb862cfaba1f8a9b52a3cf860e60e50399b00afc41`
- binding SHA256 `cb63a1d165460902f25e234fb3e0b325c75f98e01a19f664880a52950cc1c9a9`
- smoke SHA256 `3b69e2a5c2aaddf634233242cd9ac3785f446c4cfe68cbe7fd23a455dde47537`

Local evidence:
- normal 10/10 PASS
- Python -O 10/10 PASS

Design:
- LEGACY = exact G1 bypass, G2 loader zero-call
- G2 = post-Control/pre-broker overlay
- only minimum_score_gap candidate axis admitted
- exact G2 config/audit identity required
- missing PIT/lifecycle inputs fail closed
- treatment-book materialization remains a separate next-stage concern

Next:
`exact G1+G2 combined integration tree + binding patch → native smoke/CI → only then R0 materialization wiring`.

Recommended model: Extra High.
Pro budget priority: LOW.


## 11.7 G2 native binding validation completion — 2026-10-07

Task:
`R1000-G2-G1-NATIVE-INTEGRATION-VALIDATION-20261007`

Status:
`G2_BINDING_NATIVE_VALIDATED / DRAFT_UNMERGED`

Draft PR #583:
- head `f7bd98b43209b4cebb0e0c78f17963b6aba3795d`
- 8 changed files
- PR Validation 37582268796 SUCCESS
- Portfolio Guard 37582268781 SUCCESS
- binding smoke normal 10 PASS / SKIP0
- binding smoke optimized 10 PASS / SKIP0
- G1 native regression PASS
- G2 regression PASS
- LEGACY path G2 zero-load verified
- G2 broker path blocked until explicit treatment materialization

Still NOT_RUN:
- treatment target-book materialization
- R0 full-Control parity
- R1/economic comparison
- G3 strategy-difference reporter: NATIVE_VALIDATED / Draft PR #584 head `451b67cfb132921088b73a883f03116417b85fa6`; native normal/-O 16 PASS; read-only replay consumer; R0/R1 NOT_RUN
- merge/review/Codex

Program sequence remains:
`G3 binding → R0 materialization/full-Control parity → R1`.

G3 is observational only and must not change the economic path. Retrieve the existing G3 local patch bytes rather than rewriting them.


## 11.8 G3 native validation completion — 2026-10-07

Task:
`R1000-G3-NATIVE-BINDING-20261007`

Status:
`G3_NATIVE_VALIDATED / DRAFT_UNMERGED`

Draft PR #584:
- head `451b67cfb132921088b73a883f03116417b85fa6`
- PR Validation 37589666282 SUCCESS
- Portfolio Guard 37589666299 SUCCESS
- native reporter normal 16 PASS
- native reporter Python -O 16 PASS
- read-only comparison consumer only
- no NAV/evaluator/backtester/economic source creation
- missing fee/turnover/winner evidence remains NOT_AVAILABLE
- provenance-only G1/G2 identity preserved without economic interpretation

Expected review_complete remains blocked while Draft / without maintainer-current-head independent review evidence. This does not negate the native validation result and does not authorize merge.

Next:
`R0 materialization + all-LEGACY full-Control parity`.

R0 expected alpha delta is exactly zero. G2 must remain OFF/LEGACY in the parity arm. G3 only consumes resulting replay refs.


## 11.8 G3 native binding validation completion — 2026-10-07

Task:
`R1000-G3-NATIVE-BINDING-20261007`

Status:
`G3_BINDING_NATIVE_VALIDATED / DRAFT_UNMERGED`

Draft PR #584:
- head `451b67cfb132921088b73a883f03116417b85fa6`
- exactly 3 changed files
- PR Validation 37589666282 SUCCESS
- Portfolio Guard 37589666299 SUCCESS
- G3 smoke normal 16 PASS
- G3 smoke Python -O 16 PASS
- read-only replay comparison only
- no evaluator/NAV/backtester/cost engine
- optional missing economics remain NOT_AVAILABLE
- core holdings missing => INSUFFICIENT_EVIDENCE

Original recovery evidence independently checked:
- Recovery ZIP SHA256 `9f3eac746fe61c31869774e086bf3cfd9bb0cc49374bb325bb359d0fdc433241`
- original patch SHA256 `80b8e2a8e9b9775dbbe36fa1933e363cf48876f0328e0f054c9e5a5193df6f54`
- original source SHA256 `24a573e02ba58a34e1852f3a5c13c7bc0b621c7dde0e004f0fea5e8fb5bfaa78`
- original smoke SHA256 `0dbc9b7d4eb0504fd11ec7ea0642b11017dd6540856d4340af1a1386644c9fa1`

### R0 scope correction
R0 must remain **all-LEGACY direct Control vs modular all-LEGACY Control**.
G2 treatment is NOT applied in R0.

Next:
`isolated replay-materialization contract → R0 all-LEGACY full-Control parity → G3 no-divergence readout → R1 one G2 hold/replace candidate`.

G2 treatment target-book materialization is first used economically in R1 after R0 passes.


## R0 real-input gate update — 2026-10-08

R0 remains `BLOCKED_REAL_R0_INPUT`; PR #586 head `dcd006acef45bb783a5f21cf729a7738dda79464` is structural evidence only. No R0 economic receipt exists and R1 must not start.

TEMP_A0 found the current-inventory long-crisis file on Drive (ID `1Y7CFRCXtuKtBEPSczPYJqaJZoFWpfk56`, SHA256 `5b460618944303c65b97caa20323f498a266fe97005b6733ec75efd8acb3c519`) and a historical July price-cache manifest (Drive ID `1gTREHtoAgAUIugntQVANqig8425JzYRX`, SHA256 `f84fe86580bf6560db38926bbb716aaa929f5a4764ad40407b42d596a16bd731`, 80 tickers, actual through 2026-07-24). The current full-history Drive cache is a later mutable generation and must not substitute for the July snapshot.

Drive revision metadata exposes exact July revisions for at least AAPL/ABBV, but old revision media fetch returned HTTP 403 and at least one sampled ticker (ADI) did not expose the July revision. Therefore revision metadata is not yet recovered/admitted input.

Next: bounded A1-style input admission/recovery within the existing R0 lane; exact crisis binding + G2-env rejection + hash-bound real-input gate + synthetic-cannot-pass regression. No recollection/synthesis. If any required historical bar bytes cannot be recovered and SHA-verified, keep R0 blocked.

Recommended model: Extra High. Pro budget priority: MEDIUM.


## G5 Leadership Re-Acceleration PREP — 2026-10-08

Status:
`DONE_PREPARE_ONLY / PARTIAL_OVERLAP / INCREMENTAL_REVIEW_VALUE / NO_MUTATION`

Accepted interpretation:
- no new standalone Leadership framework
- reuse retained Leadership v2 + current RS/lifecycle/sector machinery
- incremental value is a PIT-safe A2→A3 re-review trigger for prior leaders/winners
- no canonical `REACCELERATING` Registry state now; use research diagnostic/annotation
- no BUY/SELL/A5/order authority
- no G5 integration/economic run while R0/R1 causal lane is unresolved

Prepared patch:
- `R1000_REACCELERATION_DIAGNOSTIC_PREP.patch`
- SHA256 `cb351333b90e71b13901fbf6b12c55deea524e771ce7866c20792722e2e2bf3a`

Local evidence:
- normal 77/77 PASS
- Python -O 77/77 PASS
- native CI/economic validation NOT_RUN

Real-company trace:
- MSFT retained evidence reused
- current conclusion `INSUFFICIENT_EVIDENCE / REACCELERATION_NOT_ADMITTED`
- exact immutable dual-cutoff + same-lineage exit→reacceleration evidence still required

Future sequence after R0/R1:
`current-master narrow port → A1 source-bound dual-snapshot trace → A3 re-review payload → A6 independent validation → H2 Control vs price/RS trigger → freeze → optional A3-confirmed challenger`

Current R0 live head observed:
`c74e9bf80b7f25868e21fce939e5615d93ce399c`
PR #586 Draft/open/unmerged. R0 remains the active integration/economic gate; R1 and G5 economics wait.


## G4 SEC ACTUAL trace PREP — 2026-10-08

Status:
`PARTIAL_REAL_TRACE / NO_MUTATION`

G4 narrowed the remaining gap to **retained Source3 artifact resolution + existing numerical Companyfacts normalizer → typed ACTUAL bridge binding**. No new SEC collector is needed.

MSFT retained trace:
- CIK `0000789019`
- accession `0001193125-26-323660`
- raw Source3 SHA256 `f8aae2965b20ad0df44bdf7ccbedf797d275b6b8dc030154a7a311361bb7246f`
- source-current receipt SHA256 `9e459e4b05d658f9b703b63370be40f6085e9bea913638e08c9d7235415cf9d9`
- READ_CALC receipt SHA256 `38be4cd79ba9d9ce463bd74b6525d2d8f04c67d0a7e781381892f3aa26eb2091`
- READ_CALC result SHA256 `32d172f188d707cae60274d2316d441ae52b7f6271f466030319288e81a0edab`
- retained evidence proves 6 observations / 3 comparisons for Revenue, NetIncome, DilutedEPS, but exact numerical values/concepts/units/period ends are not currently resolvable

PIT:
- prior 2026-10-02 cutoff correctly rejected Source3 as FUTURE_EVIDENCE
- retained available/collected clock `2026-10-05T09:17:49.266311Z`
- SEC accepted_at remains distinct from source_observed/available/collected
- expiry UNKNOWN

Real ACTUAL row / plan_reassessment were correctly NOT_RUN rather than synthesized.

Next G4 step, allowed in parallel with R0:
`retained Source3 recovery → exact value/concept/unit/period recovery → one real MSFT ACTUAL row → read-only plan_reassessment → proposal-only A3 handoff`

If retained bytes cannot be resolved, stop:
`BLOCKED_SOURCE_ADMISSION — RETAINED_SOURCE_ARTIFACT_NOT_RESOLVABLE`

No ER/A5/BUY/SELL/Registry write/economic mutation.


## G4-A1 retained Source3 recovery — 2026-10-08

Status:
`BLOCKED_SOURCE_ADMISSION`

G4-A1 stopped correctly at the retained-source gate. The target MSFT Source3 bytes were not recovered, and the nearest Drive Companyfacts file was rejected as a substitute because its SHA/accession/generation did not match the target lineage.

Target:
- CIK `0000789019`
- accession `0001193125-26-323660`
- Source3 SHA256 `f8aae2965b20ad0df44bdf7ccbedf797d275b6b8dc030154a7a311361bb7246f`
- source-current receipt `9e459e4b05d658f9b703b63370be40f6085e9bea913638e08c9d7235415cf9d9`
- READ_CALC receipt `38be4cd79ba9d9ce463bd74b6525d2d8f04c67d0a7e781381892f3aa26eb2091`
- READ_CALC result `32d172f188d707cae60274d2316d441ae52b7f6271f466030319288e81a0edab`

Rejected Drive candidate:
- `companyfacts_0000789019.json`
- SHA256 `e1c4ccf3b6d60fa5db29d48afb700acd25a41ce4402d59f256280aff758f7ff5`
- target accession absent; snapshot predates target filing

No ACTUAL row or plan_reassessment was synthesized.

Only remaining recovery path:
search the original 2026-10-05~06 C2 host/worktree/scratch/archive around `H:/r1000-quant-engine/outputs/a0_v5_dispatch_20261005/` for the exact four byte identities. If those bytes are confirmed lost, close as `SOURCE_LOST_NOT_ADMITTED`; do not recreate this lineage from a new SEC download.

G4 remains independent of R0/R1/G5/G6.
