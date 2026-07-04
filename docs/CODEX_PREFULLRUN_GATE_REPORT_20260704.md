# AlphaOps Pre-Fullrun Gate Report - 2026-07-04

## Purpose

This report freezes the current state before any additional integration
fullrun. It converts the active governance queue into a machine-readable gate
and records the exact blockers that must be cleared first.

No workflow was dispatched. No live-trading or production state was mutated.

## What Changed

Implemented a stricter pre-fullrun gate:

- `tools/verify_alphaops_prefullrun_gate.py`
- `tests/alphaops_prefullrun_gate_smoke.py`
- `tools/run_pr_validation.py` registration

Also aligned the older price-only readiness helper with current governance:

- `tools/verify_alphaops_fullrun_readiness.py`
  - default branch is now `codex/integration-fullrun-clean-20260630`
  - default experiment env is now empty / long-only
  - `SH` is required only when `PHASE_MAIN_FAST_CRASH_HEDGE_ENABLED=1`
- `tests/alphaops_fullrun_readiness_smoke.py`

Replacement-quality readiness was refreshed with the current allowlist-v2 hook
probe:

- `outputs/replacement_quality_readiness_audit_28616190134_allowlist_v2/summary.json`
- `outputs/replacement_quality_readiness_audit_28616190134_allowlist_v2/report.md`

This removed the older "hook broader than fixed" blocker. The current blockers
are narrower and more accurate.

## Current Machine Verdict

Latest local gate:

- `outputs/prefullrun_gate/summary.json`
- `outputs/prefullrun_gate/report.md`

Verdict:

- `research_fullrun_preconditions_ready=false`
- `fullrun_dispatch_allowed=false`
- `production_promotion_allowed=false`
- `next_action=finish_prefullrun_blockers`

Current blockers:

1. `price_readiness_not_ready`
   - `outputs/latest_price_date_audit.json` is missing locally.
   - Long-only default required tickers are now only `QQQ`, `SPY`.
2. `target_book_control_repro_not_exact`
   - `ticker_mismatch_date_count`: Main 52, Concentrated 56.
   - `max_weight_delta_abs`: Main 0.49, Concentrated 0.30.
   - Required W1 gate remains exact: `max_weight_delta_abs <= 1e-9`.
3. `replacement_quality_not_fullrun_ready`
   - allowlist-v2 hook is now a subset of fixed-book swaps.
   - remaining blockers:
     - `control_not_reproduced`
     - `hook_swap_count_outside_tolerance`
   - fixed swaps: 17; hook swaps: 12; fixed-only: 5; hook-only: 0.
4. `main_long_only_cash_carry_target_not_met`
   - hedge-off cash-carry Main: CAGR 34.996%, MDD -24.003%.
   - Main is MDD-safe but misses the 35% CAGR target by about 0.00375 absolute
     CAGR.
5. `earnings_guidance_not_research_ready`
   - current true PIT revision/guidance feed remains `DATA_INSUFFICIENT`.
   - actuals/proxy context is allowed for diagnostics but not coverage.
6. `universe_health_not_ready`
   - latest P2 status is `invalid_universe`.
   - scored R1000 base count is 0 and expected run files are missing.
7. Production blocker remains:
   - `pit_universe_label_clean_false`

## Required Order Before Fullrun

Do not dispatch a fullrun until these are cleared in order:

1. Refresh price readiness.
   - Run the daily data update and regenerate `outputs/fullrun_readiness`.
   - This is necessary but not sufficient.
2. Fix W1 target-book control reproduction.
   - Either reproduce the dirty official artifact exactly, or create a new clean
     official control artifact and use that as the acceptance baseline.
   - No regenerated selection-side A/B can be accepted before this.
3. Resolve replacement-quality event source.
   - Preserve the current allowlist-v2 subset property.
   - Fix the five fixed-only / under-fire events or explicitly document why the
     hook may skip them.
   - The hook count delta must be within the readiness tolerance or the rule
     remains diagnostic only.
4. Close the Main long-only shortfall.
   - Current hedge-off cash-carry Main is close but still below target.
   - Do not re-enable SH hedge to quote Main as solved; official policy is
     long-only.
5. Add or import a true PIT earnings/guidance feed before any earnings-dependent
   policy or regime hook is allowed.
6. Restore universe health and keep `pit_universe_label_clean=false` as a hard
   production blocker until the PIT membership audit is clean.

## Claude/GPT Pro Routing

No new Claude question is required right now.

Reason: the current blockers are mechanical, not ambiguous. Another review round
would likely repeat the same instruction:

- no fullrun now
- fix W1/control reproduction
- fix replacement event-source coverage
- keep Main long-only
- do not treat SEC actuals/proxies as true revision/guidance coverage

Ask Claude only after one of these happens:

1. W1 exact control reproduction passes, but replacement-quality still fails.
2. replacement-quality passes fixed-book readiness, but fullrun go/no-go remains
   ambiguous.
3. Main still misses by a tiny amount after a verified Main-safe replay-stage
   lever.

GPT Pro is more useful for governance/service-contract questions, for example:

- whether to accept cash-carry as the official research accounting contract;
- whether website display can show any backtest-derived metrics;
- what wording to use for forward expectation bands.

## Validation

Executed with the bundled Codex Python runtime:

```powershell
python -m py_compile `
  tools\verify_alphaops_fullrun_readiness.py `
  tools\verify_alphaops_prefullrun_gate.py `
  tests\alphaops_fullrun_readiness_smoke.py `
  tests\alphaops_prefullrun_gate_smoke.py `
  tools\run_replacement_quality_readiness_audit.py

python tools\run_pr_validation.py `
  --only alphaops_fullrun_readiness_smoke `
  --only alphaops_prefullrun_gate_smoke `
  --only replacement_quality_readiness_audit_smoke
```

Result:

- `alphaops_fullrun_readiness_smoke`: PASS
- `alphaops_prefullrun_gate_smoke`: PASS
- `replacement_quality_readiness_audit_smoke`: PASS

## Bottom Line

Fullrun is still blocked. The repository now has a single local gate that says
why, with the current long-only/cash-carry governance applied. The next
engineering work should be W1 control reproduction and replacement-quality
event-source coverage, not another strategy idea or fullrun dispatch.
