# [PROJECT_HANDOFF] Decision V1 core seams — 2026-09-09

RESEARCH_ONLY / BUGFIX_ONLY. Extends #400 at 52b119ab653016bb1706cf4ff706890e820e131d.
No quality/alpha rule is introduced in this patch. #399 admission, numeric config,
protected test registration, existing operating workflows/books/orders are unchanged.

## Repaired connections

1. Account/capital, FX and regime validation have distinct errors. Missing capital
   blocks portfolio construction but does not erase valid currency-adjusted ranks.
   KRW-native values survive missing USD FX; global ranks remain blocked.
2. `fund_targets` solves a self-financing identity at post-cost NAV, preserving HOLD
   notionals. Cash pays estimated trading costs; no hidden borrowing. Actions use
   trade notionals rather than fee-induced weight drift. Concentration/liquidity/
   regime checks rerun on post-cost NAV. A financing-induced trade reversal,
   negative cash or risk conflict blocks the proposal instead of silent trading.
3. The research CLI uses an OS-managed absolute Git executable, never inherited
   PATH. Git/dynamic-loader environment overrides are removed for read commands.
   POSIX owner/mode checks and Windows OS known-folder lookup retain an explicit
   OS/admin-install trust boundary. Native Windows validation remains pending.

Review mapping: 3952443147 (trusted Git), 3952443150 (cash/NAV),
3952443159 (capital/FX). No thread is self-approved or automatically resolved.

Funding equation: lambda + sum(c_i * abs(D_i(lambda)-U_i)) = 1.
D_i=lambda*w_i for tradable targets; D_i=U_i for preserved HOLDs. Output records
initial NAV, fees, positions, residual cash and post-cost weights. It is a continuous
valuation proposal, NOT integer-lot execution, order fills or personal-tax modeling.

## Actual validation

`python -I tests/research_workflow_funding_smoke.py` (14 tests) and
`python -I tests/research_workflow_source_smoke.py` (5 tests) pass normally and
with `-O`. The identical suites fail on the original code. Nineteen unique tests,
not 38 independent tests. Funding includes one seeded 200-case conservation test.
Temporary Git repositories are synthetic test fixtures, not user worktrees.

The funding engine tests mock ONLY the market-export replay boundary with labelled
SYNTHETIC admitted objects. They exercise actual valuation/FX/ranking/funding, but
are not complete H1 or market-data coverage tests. Existing full H1/H2 suites,
protected Tier-1 registration, full checkout CI, Windows and exact-head independent
review are not claimed. Detailed local log hashes are in core_seam_validation.json.

## Environment and publication

No original user checkout exists in this session. Container GitHub DNS failed;
relevant archived source bytes were checked against exact GitHub blob identities.
Edits/tests use a partial source workspace, then an isolated bare object store and
explicit staged paths. Published blobs must equal those staged bytes. Local partial
patch tree/commit is NOT the full repository tree. No user files/worktrees changed.

## Remaining / next

Actual universe/current raw price, corporate actions, reconciled TTM and reviewed
scenario coverage remain incomplete. #405 owns the separately opt-in quality route.
No new market-data collection, fullrun, migration, scheduling, merge, promotion,
actual account reconciliation, OOS/CAGR/MDD proof or orders are included.
