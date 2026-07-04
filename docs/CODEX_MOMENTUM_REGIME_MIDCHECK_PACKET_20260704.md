# CODEX Momentum / Regime Midcheck Packet - 2026-07-04

## Purpose

This packet is for a mid-cycle review by GPT Pro and Claude before continuing
implementation. It summarizes what was actually implemented, what remains
research-only, what must not be activated, and the exact review questions.

Do not treat this packet as a policy approval, fullrun trigger, or production
promotion request.

## Current Branch / HEAD

- Repository: `H:\codex\tmp_r1000_grossfloor_20260625`
- Branch: `codex/integration-fullrun-clean-20260630`
- Latest relevant commits:
  - `9ab0b63b feat: add momentum regime research audits`
  - `ae2fd139 docs: refine momentum regime scorecard`
  - `fc292693 docs: add momentum regime research tracks`
  - `6011853f docs: close out accelerate exit no-op`

Working tree note:

- There are many untracked `outputs/` and cache artifacts from previous research
  runs. They were intentionally not staged.
- The M/R implementation commit includes only tools, tests, and validation
  wiring.

## What Was Reflected

### 1. Momentum / Regime Directive

File:

- `docs/CODEX_MOMENTUM_REGIME_RESEARCH_TRACKS_20260704.md`

Purpose:

- Define AlphaOps as a concentrated long-only momentum system with industry
  momentum, 52-week-high leadership, trend filters, cash/regime controls, and
  PIT fundamental confirmation where available.
- Add Track M and Track R as research-only backlog, not as trading policy.

Key guardrails:

- No production promotion.
- No live trading.
- No fullrun from this document alone.
- No short side.
- No all-in/all-out regime switch.
- No volatility scaling up.
- No broad gross-floor revival.
- No tight-stop revival.
- No one-month reversal entry rule without measured evidence.
- Forward returns are audit labels only.
- Any current-market label must come from data computed by Track R, not from
  commentary.

### 2. Track M Research Tools

Added:

- `tools/research_audit_utils.py`
- `tools/run_momentum_beta_decomposition.py`
- `tools/run_rs_horizon_ic_audit.py`

Tests:

- `tests/momentum_beta_decomposition_smoke.py`
- `tests/rs_horizon_ic_audit_smoke.py`

Intent:

- M1 decomposes portfolio returns into market exposure, internal momentum beta,
  and residual alpha.
- M2 audits RS horizon information coefficient across 1w/1m/3m/6m/12m.

Important limitation:

- These are informational. They do not alter scores, target books, weights,
  orders, or production state.

### 3. Track R Research Tools

Added:

- `tools/run_regime_nowcast_dial.py`
- `tools/run_chameleon_policy_audit.py`
- `tools/run_state_conditional_ic_audit.py`

Tests:

- `tests/regime_nowcast_dial_smoke.py`
- `tests/chameleon_policy_audit_smoke.py`
- `tests/state_conditional_ic_audit_smoke.py`

Intent:

- R1 builds a 0-12 bear-warning nowcast score.
- R1 emits `DATA_INSUFFICIENT` if fewer than six warning signals are covered.
- R1 outputs triggered/missing signals, confidence, and required review action.
- R1b translates the regime state into review-only operating guidance.
- R2 checks whether momentum or turnaround/oversold-value feature families have
  better IC by regime state.

Important limitation:

- R1/R1b/R2 do not create executable orders.
- R1/R1b/R2 do not mutate target books.
- R1/R1b/R2 do not enable live trading.
- R1/R1b/R2 do not trigger fullrun.

### 4. Extra Hardening Added During Review

Two issues were found and fixed before this packet:

1. `run_regime_nowcast_dial.py` originally allowed input columns such as
   `state_override` / `current_state` / `regime_state` to override the computed
   state by default. This could have weakened the rule that current-market
   labels must come from computed data.
   - Fix: state override is now off by default and requires
     `--allow-state-override`.
   - Smoke added to verify override does not apply by default.

2. `run_state_conditional_ic_audit.py` could pass the R3 gate using rows with
   insufficient sample count if the IC gap was large.
   - Fix: R3 gate only considers rows with `status == completed`.
   - Smoke added to verify insufficient samples do not pass R3.

## Validation Performed

Use the Codex bundled Python, not the WindowsApps Python shim:

`C:\codex-shadow\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`

Commands run:

```powershell
C:\codex-shadow\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -B -m py_compile `
  tools\research_audit_utils.py `
  tools\run_momentum_beta_decomposition.py `
  tools\run_rs_horizon_ic_audit.py `
  tools\run_regime_nowcast_dial.py `
  tools\run_state_conditional_ic_audit.py `
  tools\run_chameleon_policy_audit.py
```

```powershell
C:\codex-shadow\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -B tools\run_pr_validation.py `
  --only momentum_beta_decomposition_smoke `
  --only rs_horizon_ic_audit_smoke `
  --only regime_nowcast_dial_smoke `
  --only state_conditional_ic_audit_smoke `
  --only chameleon_policy_audit_smoke
```

Result:

- `momentum_beta_decomposition_smoke`: PASS
- `rs_horizon_ic_audit_smoke`: PASS
- `regime_nowcast_dial_smoke`: PASS
- `state_conditional_ic_audit_smoke`: PASS
- `chameleon_policy_audit_smoke`: PASS
- Targeted PR validation: 5/5 PASS

Runtime caveat:

- The default `python` on this Windows machine is
  `C:\Users\<user>\AppData\Local\Microsoft\WindowsApps\python.exe` and does not
  have pandas installed. Use the bundled Codex Python above.

## How This Complements the Held Work

The held performance work remains the execution priority:

1. Concentrated replacement-quality event-matched candidate.
2. W1 target-book control reproduction.
3. Main hedge-OFF / long-only baseline interpretation.
4. PIT membership / production blocker.

M/R should not interrupt that queue.

M/R should be used as:

- A market-state dashboard.
- A review-only action layer.
- A research audit layer for momentum beta, RS horizon quality, and
  state-conditional feature quality.

M/R should not yet be used as:

- A policy hook.
- A scoring tilt.
- A fullrun payload.
- A live trading signal.
- A reason to revive broad bull-floor, broad hold, broad sizing, or tight stops.

## Open Engineering Questions

1. R1 real-data run:
   - Does the current local data provide at least six covered warning signals?
   - If not, which signals are missing?
   - Should missing signals stay neutral, or should certain missing critical
     signals block the regime label?

2. M1 data source:
   - Which target books should be the canonical M1 input?
   - Should M1 use fixed official books only until W1 is resolved?

3. M2 feature scope:
   - Are the current RS columns enough, or should QQQ/theme/industry RS variants
     be included?
   - Should M2 distinguish entry rows from incumbent/holding rows?

4. R2 sample gate:
   - Is `min_samples=20` appropriate for state-conditioned IC?
   - Should R2 require at least two eras per state before allowing R3?

5. R1b action semantics:
   - Are `CORRECTION` and `BEAR` actions too strong even as review-only?
   - Should `cash/T-bill reserve` be framed as a destination label only until
     cash-carry / reserve accounting is fully contractual?

## Questions for GPT Pro

Use GPT Pro for governance and service-facing wording, not code red-team.

1. Is the R1/R1b framing safe for future public/service use if every action row
   is `REVIEW_ONLY` and all current-market labels require computed data?
2. Should `bear_warning_score` be displayed to users as a numeric score, a
   coarse regime label, or hidden behind internal alerts?
3. Is `DATA_INSUFFICIENT` the right default if fewer than six signals are
   covered, or should the threshold be higher for public-facing use?
4. Should `cash/T-bill reserve` be described as an accounting/defensive reserve
   in service copy, given production remains blocked by PIT membership?
5. What wording best prevents users from interpreting historical CAGR as a
   forward return promise?

## Questions for Claude

Use Claude for code/path red-team after concrete outputs exist.

1. Does the R1 implementation correctly avoid market-timing claims?
2. Is the default-off `state_override` gate sufficient, or should override be
   removed entirely from the research tool?
3. Does R2's completed-row-only gate fully prevent insufficient-sample IC from
   authorizing R3?
4. Are the smoke tests strong enough to catch accidental executable order,
   production mutation, or live trading flags?
5. Which one should be run first on real data: R1 nowcast coverage, M1 momentum
   beta, or M2 RS horizon IC?

## Recommended Next Step

Do not ask for another abstract strategy opinion.

Run one concrete data pass first:

1. Run R1 on the latest available local data.
2. Report coverage, `DATA_INSUFFICIENT` status if applicable, triggered signals,
   and missing signals.
3. Feed that R1 output into R1b to generate review-only actions.
4. Then send the concrete R1/R1b outputs to Claude for code/path red-team and to
   GPT Pro for service/governance wording.

No fullrun, no production mutation, and no policy hook before that.

