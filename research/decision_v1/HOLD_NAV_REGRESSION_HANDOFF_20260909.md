# [PROJECT_HANDOFF] HOLD / post-cost NAV regression repair — 2026-09-09

Scope: existing PR #400 test-contract repair; no new alpha, cost/config change,
production readiness, broker mutation, Codex dependency or new workflow.
Parent: `35c4cab6b1367d5ca68368cd444c9a8427eec395`.
Downstream #405 observed: `fb57000c4dd069b43d4fd0b0e036a4c468cc3cf9`.

## Failure and correction
The supplied original CI log for run34306121085/job102323060428 reports
229/230 test files passed, with two of the 42 decision tests failing because
a held weight was compared to 0.2 after trading costs reduced total NAV.
The unchanged `fund_targets` preserves the holding NOTIONAL and funds other
trades' fees from cash. Restoring the 0.2 weight would imply a hidden sale.

The two existing tests now check HOLD action, exactly zero held trade,
unchanged held notional, post-cost weight identity, independently recomputed
fees by market, cash/NAV conservation and the existing risk-audit result.
They do not waive risk violations or increase the no-trade threshold.
Three tests inside the already-registered decision test file cover analytic
post-cost weights, exact zero-cost parity and six corrupted-output cases.
Existing zero-trade/no-purchase assertions remain unchanged.

## Actual local evidence
- Reconstructed the original 39,398-byte test from live GitHub reads; exact
  blob equals `437dfdfa8eacd8c93960ee8704a4259c33f0d584` before editing.
- Same arithmetic reproduces 0.20006 and 0.20009000000000002 with a KRW20m
  holding unchanged and zero held trade; old equality-to-0.2 fails.
- Three NEW test methods were AST-isolated from the edited file and executed
  against actual `portfolio.fund_targets`: 3/3 PASS, normal and optimized.
  The context/config are the attachment's synthetic setup, not real data.
- Existing attachment tests: funding14, source5, quality-engine22, quality65,
  all PASS (106 total). With the three focused checks:109 unique local checks.
- Compiled edited full file; it contains45 test methods. The FULL45-test file
  and full230-file CI were NOT run locally. Do not equate109 with full CI.

Local input is the supplied System_Workflow_Integration_20260909.zip source
snapshot, not the user's full checkout. Network DNS/HTTPS failed. No package
lock was invented, pin checks removed or missing calendar library impersonated.
Python3.13.5/pandas2.2.3/exchange_calendars4.13.1/tzdata2026.2; the pinned full
H1/CLI environment is not available here. Local logs are delivered with the patch.

## Publication and validation boundary
Explicit local staging only: the test file and this handoff. No other source,
config, workflow, historical receipt or index is changed. Keep the existing PR
Draft. Full fixed-environment Actions and exact-head independent review remain
required. A passing local subset is neither CODE_FULLY_VALIDATED nor DATA_READY,
RESEARCH_E2E_READY, OOS/MDD validation or production approval.

Do not invoke Codex for this task. Do not remove GitHub review requirements.
No merge, force push, transaction rerun, order, live/paper account change or
new schedule. #405 needs separate validation against the updated base; do not
claim its old HEAD already contains this change.

## Shared lesson / next action
HOLD is a zero-trade notional invariant, not constant post-fee weight. Tests
must reconcile denominators and money, rather than loosen decimal tolerances.
Next: run the full existing decision test in GitHub's pinned environment and
inspect its actual log, then validate downstream #405. Actual-company input
completion remains a separate data task; no new prices/fundamentals were fetched.

## Local source and log SHA256
- `tools/research_decision_v1/portfolio.py`: `5a62e9fa9a6ff5865558d7961bfa0ed3899d99406d3dd66da3da792de7f4e503`
- `tools/research_decision_v1/engine.py`: `c464aed8488810fd2b6389bf1fc32b4e05f0e4de2b323a6a81b72ddad6671e86`
- `tests/research_decision_v1_decision_smoke.py`: `dc3bbdbdd098f36da1a874432449f372f1aaa3968d2279fb58396c109e15002d`
- `funding.log`: `20921fc58d7c03d276058874a587bc397f9dc07d1efa3f3091a1b3b340052dfd`
- `hold_normal.log`: `534f23ee05d081157a8716c0876654b8b51e917db0913432091fdacdaca5b4ff`
- `hold_optimized.log`: `c43fb87e5b25d6fe6e1e2ceac95c709b001470fdcb172089afb7cc93b29aa9f0`
- `quality.log`: `a29b714a05b33cfee93bd6e590a9b475c17998fa93a425770ec1cf9a481d6c99`
- `quality_engine.log`: `c3f459504abda0f8dbb7097fa55fb954bb876964fd0f0eb13b59d5f55455c54f`
- `source.log`: `84228907ac1e897880ede6e7ba5e8ab1555dcf24ff782b78d808b5b373189751`
