# [PROJECT_HANDOFF] Overall workflow and repaired seams — 2026-09-09

> User handoff review: [2026-09-10 reconciliation](HANDOFF_RECONCILIATION_20260910.md).
> Adds shared-environment comparison checks and reconciled FX/cost attribution;
> keeps historical quantitative recovery separate from unavailable quality records.

> New 2026-09-10 code: [USD continuous fund replay contract](../../docs/research_fund_replay_contract.md).
> Branch `codex/usd-fund-manager-replay-20260910` extends the current #405 dependency.
> It connects actual simulated shares/cash to repeated H1/H2/quality decisions and adds
> after-cost CAGR development selection. It is executable research code, not completed
> REAL 7–8 year data coverage, new performance evidence or production activation.

> Continuation: [2026-09-10 fixes and long-backtest readiness](BACKTEST_READINESS_20260910.md).
> It records current repairs, later CI evidence, the blocked preflight and source recovery limits.
> The dated statements below remain historical evidence; RESEARCH_INDEX entries are not reapproved by this link.

**The research decision graph is now connected in code and synthetic seam tests.
The complete live-data investment/operating system is NOT finished.**
RESEARCH_ONLY. No merge, production promotion, schedule, book, order or numeric
strategy-weight change. Existing #399/#400/#401/#405 are reused; no new parallel
strategy or duplicate plan PR is created. Core bugfixes belong to #400; optional
quality integration belongs to #405. Precise published HEADs are in PR metadata.

## Source identities actually inspected

US master: 8ccbd478e05ff34c6dd70e410be0cae793c9863e.
H1 #399: 1c5e1c0eaeb7885d35bd6713aba93ff931460c81.
H2 #400 before patch: 52b119ab653016bb1706cf4ff706890e820e131d.
Quality #405 before patch: 19d75517cf0ee72fa56d400d8a749306fa7280a8.
KR export dependency remains #2 at 3c40210b8675267121d7f40f3dcd8d158720a4e8;
no KR code/operational branch is edited here. All unmerged work is research only.

AGENTS, operating standard, shared lessons, #400 inline reviews, key entrypoints,
monitor contract, workflow file directory, recent runs and one failed job's logs
were read. This is a major-path/seam audit, not an exhaustive review of every file.

## End-to-end map: existence is not readiness

| Stage | Producer -> consumer | Observation / remaining boundary |
|---|---|---|
| Universe and identities | US/KR universe -> provider inputs | Current full universe/history coverage NOT verified; 5+2 is output count, not the universe |
| Raw sources | providers/cache/filings -> H1 export | Price/actions/benchmark/TTM/shares/FCF availability must pass original admission; API success alone is insufficient |
| Features/discovery | admitted price/financial inputs -> group/RS diagnostics | Original functions retained; no NONRANKING-to-alpha conversion |
| Business evidence | capture/claim/receipt -> quality assessment | Seven axes and price-independent business analysis; receipt validity is not authenticated semantic truth |
| Scenario/value | reviewed bindings + H1 scenario -> V1 valuation | Existing PE/EV_EBITDA, profitable-company, 12-month subjective bounds retained; no invented short-horizon forecast |
| Currency/ranking | local value + FX -> local/global ranks | FIXED: capital failure no longer erases valid FX ranks; KRW-native metrics survive missing USD FX |
| Portfolio/funding | quality-eligible ranks + book/regime/risk -> target/cash | CONNECTED quality; FIXED fees/post-cost NAV/HOLD notional; unreviewed holdings preserved for review |
| Reporting/history | decision -> immutable report/evidence/ledger | New per-run quality/workflow artifacts wired to existing writer; global index pointer advance NOT automated |
| Outcomes/learning | frozen decisions -> matured realized outcomes | NOT connected/validated in this patch; no claimed 12-month accuracy, CAGR or MDD |
| Approved operations | reviewed target -> paper/actual execution/reconciliation | NOT activated; accepted Drive/broker state NOT inspected or mutated |

## Actual operational handoff failure

Run287 Sector Leadership Research run 34192898628 / job 101954423205 failed on
2026-09-08 at exact-source-artifact selection. The source run 34192518327 had
passed successful-default-branch identity verification, but the consumer required:
`daily-operating-selection-refresh-34192518327` and
`accepted-paper-transaction-34192518327`.
The error was `exact daily and accepted source artifacts are both required`.
The source run artifact API returned an empty list during this inspection.
The latest inspected Free Data Daily Update run 34299114362 succeeded, but its
artifact API also returned an empty list. That is NOT proof that Drive/cache data
is absent; publication and coverage were not verified there. No blind rerun or
relaxation of accepted-transaction requirements was performed. Producer publication
and existing operational receipt contracts need a separate bounded repair.

## Code repaired / connected

- portfolio.py: separate account/capital/FX/regime gates; self-financing fees and
  post-cost NAV; exact HOLD preserves notional; risk/liquidity checked after fees.
- engine.py: optional reviewed quality bundle calls existing quality/value modules,
  prevents unreviewed investment ranks/new allocations, preserves partial company
  analysis, tracks quality/receipt changes and reports per-stage workflow status.
- research CLI: OS-trusted absolute Git, sanitized Git environment, explicit quality
  input, immutable quality/workflow snapshots and manifest hashes. No trading import.
- Existing numeric config, H1 data/io/platform code, quality semantics and official
  monitor/target/ledger writers are unchanged. No new standalone scoring engine.

Funding details and #400 review IDs are in CORE_SEAM_FIXES_20260909.md.
A quality-reviewed rejection is separate from an expected-return comparison. A
missing review is not corporate deterioration. The template cannot self-authorize
source truth, independent approval or historical PIT merely by having a hash.

## What was actually tested

Integrated workspace: 14 funding + 5 source-executable + 22 quality-engine + 65
existing quality regressions = **106 unique tests**, all pass normal and -O.
The identical new suites fail on original code. The core-only scope passes 19.
These tests are synthetic, with `engine.replay_export` mocked ONLY at the explicitly
labelled admitted-export boundary for successful investment cases. All downstream
quality/valuation/FX/ranking/portfolio/funding/ledger calls are real code. Synthetic
5US+2KR reaches a funded proposal; it is NOT successful real H1 admission or OOS.

Additionally, an unmocked archived REAL negative replay used actual H1 export/replay
and the new engine with prior EME/NVDA/KR captures. It retains 7 excerpt matches,
0 newly accepted v1.1 reviews, 0/3 admitted investment inputs and orders=false.
Two executions match. Original v1.0 receipts are NOT reissued. The archive cutoff
remains 2026-09-08T15:59:56Z; this is not a new market-data observation. Partial
facts survive but ranks/portfolio remain blocked. Successful full H1/CLI storage
execution and full raw-data collection were NOT performed. See validation JSON.

## Environment and acceptance gates

No user checkout is available. Container GitHub DNS failed; exact source blobs
were reconstructed in an isolated partial workspace. pandas_market_calendars5.4.0
is absent and tzdata2026.2 differs from required2026.3. The bounded pinned-package
attempt failed. No versions or calendar gates were falsified/relaxed. New positive
seam fixtures mock only export replay, and negative REAL replay never calls the
unavailable valid-price calendar path. Full H1/H2 tests, native Windows, protected
Tier-1 registration/full CI and new exact-head independent review remain pending.
Local explicit-path bare-object staging precedes publishing identical blobs; a
partial local tree is not the full repository tree. Source snapshots/fixture repos
are not new user worktrees. No claimed future work occurs asynchronously here.

## Acceptance ladder / remaining critical path

1. Exact-head independent review plus protected test registration/full pinned runtime.
2. Fill actual prices/actions/TTM/FX/regime and core company/scenario evidence for one
   real company; then 2+1 and a broad admitted candidate universe. No fake pass counts.
3. Trace daily provider artifacts into independent research inputs without reading
   legacy accepted paper transactions as universal research authorization.
4. Keep reviewed index/latest execution/last success distinct; immutable per-run
   snapshots are now wired, global latest pointers still require an explicit updater.
5. Record baseline/challenger forward decisions and matured outcomes, including
   costs, turnover, missed winners and false rejections; then OOS/approval separately.

Implementation connectivity: tested at stated seams. REAL investment readiness:
incomplete. Whole automated loop: incomplete. Profitability/MDD/OOS: not validated.
No official portfolio targets, production/readiness, accepted ledger, user account,
secrets, payments, orders, schedules, migration or main-branch merge were changed.
