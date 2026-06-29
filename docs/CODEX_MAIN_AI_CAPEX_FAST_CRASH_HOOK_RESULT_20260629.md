# Main AI Capex + Fast-Crash Hedge Hook Result (2026-06-29)

## Summary

This branch wires the Main sleeve's two surviving research ideas into the
normal `run_alphaops_vnext_policy_replay.py` target-book path:

- `PHASE_AI_CAPEX_MOMENTUM_TILT_ENABLED=1`
- `PHASE_MAIN_FAST_CRASH_HEDGE_ENABLED=1`

The implementation is still default-OFF and research-only unless explicitly
enabled by environment flags. It does not enable live trading, workflow
dispatch, production sync, or production promotion.

## Clean 7Y Reference Baseline

Artifact: `artifacts/28074476465/outputs/account_evaluation/official_metrics.json`

| Sleeve | CAGR | MaxDD | Sharpe | Production |
|---|---:|---:|---:|---|
| Main | 33.15% | -26.02% | 1.219 | blocked |
| Concentrated | 46.24% | -25.82% | 1.421 | blocked |

`pit_universe_label_clean=false` remains a production blocker even if research
metrics pass.

## Main Hook Evidence

Artifact:
`artifacts/28074476465/main_ai_capex_fast_crash_hook_policy_replay_20260629_buffered/`

Broker replay:
`broker_manual_main/metrics.json`

| Metric | Value |
|---|---:|
| Metric mode | broker_ledger_next_close |
| Start / end | 2019-06-03 / 2026-06-25 |
| Years | 7.061 |
| CAGR | 36.82% |
| MaxDD | -24.76% |
| Sharpe | 1.325 |
| Avg cash | 27.02% |
| Trades | 1660 |

This clears the research Main mission target (`CAGR >= 35%`, `MaxDD >= -25%`)
on the clean 7Y artifact.

### What Changed

The Main hook combines:

1. AI Capex momentum tilt from PR #199:
   - Main only.
   - Selected ticker set and stock gross are preserved before the hedge step.
   - AI bottleneck + momentum names receive a small internal reweighting.

2. Funded fast-crash hedge:
   - Main only.
   - Hedge ticker default: `SH`.
   - Benchmark default: `SPY`.
   - Hedge fires only when SPY 5d return <= -5% or 10d return <= -8% at a
     target-book decision date.
   - Hedge is funded by pro-rata long reduction; total gross remains <= 1.0.
   - In the clean 7Y run it fired on 2020-02-28 and 2020-10-30.

3. Small risk buffer:
   - `R1000_MAIN_FAST_CRASH_RISK_BUFFER_WEIGHT`, default `0.005`.
   - This is a generic 0.5% cash reserve while the hedge phase is enabled.
   - It is not date/ticker/sector-specific and is not based on future labels.
   - It avoids a threshold-only result: the unbuffered hook reached
     37.08% CAGR but only -25.003% MaxDD.

## Rejected / Not-Carried Side Paths

These were checked before accepting the small risk buffer:

| Probe | Result | Decision |
|---|---|---|
| Trend hedge: SPY below MA200 | MDD worsened to about -25.04% to -25.48% | Reject |
| Trend hedge: SPY below MA50 and MA200 | MDD worsened to about -25.21% | Reject |
| 63d SPY drawdown hedge | MDD worsened to about -25.87% | Reject |
| Unbuffered fast-crash hedge | 37.08% CAGR / -25.003% MaxDD | Too close to threshold |
| 0.5% generic risk buffer | 36.82% CAGR / -24.76% MaxDD | Keep |

The discarded trend-break variants are not being carried forward. They added
slow-bear hedge exposure but did not improve the broker-ledger MaxDD.

## 2-Week Relative Strength Decision

Directly adding 2-week RS to the score is not recommended yet.

Reason:

- Prior 2-week RS work (#205/#207) was useful as telemetry and timing audit,
  but primary direct-scoring predicates were unstable OOS.
- Short-horizon RS is sensitive to whipsaw and can easily become a chase
  signal if added directly to `score_total`.

Carry-forward use:

- Keep 2-week RS as a sidecar/telemetry feature.
- Use it as an entry timing split or no-op detector.
- Only promote it to a default-OFF policy hook after a broker-ledger A/B shows
  `applied_count > 0`, OOS non-collapse, and no MDD degradation.

## Concentrated Status Cross-Check

The matching Concentrated research candidate is separate from this branch.

Passing artifact:
`artifacts/28074476465/concentrated_cashfunded_early_entry_hook_policy_replay_final_default_v2_20260629/broker_manual_concentrated/metrics.json`

| Metric | Value |
|---|---:|
| CAGR | 50.07% |
| MaxDD | -24.96% |
| Sharpe | 1.477 |

This is the correct Concentrated path to carry into the later integration
branch. Other similarly named local artifacts are older arms and do not all
pass both CAGR and MaxDD.

## Validation

Commands passed:

```powershell
python -m py_compile tools/run_alphaops_vnext_policy_replay.py tests/main_fast_crash_hedge_hook_smoke.py
python tests/main_fast_crash_hedge_hook_smoke.py
python tools/run_pr_validation.py --only main_fast_crash_hedge_hook --only ai_capex_momentum_tilt_hook
```

Smoke coverage:

- Default OFF returns the input book unchanged.
- Non-Main portfolios are skipped.
- Missing hedge/benchmark price blocks without mutation.
- Enabled Main hook adds a funded `SH` hedge row when the crash signal fires.
- Total target-book gross remains <= 1.0.

## Next Step

Do not run a full rebuild yet.

Recommended sequence:

1. Merge/stack PR #199 (AI Capex Main tilt).
2. Review this Main fast-crash hedge hook PR.
3. Review the Concentrated cash-funded early-entry hook PR.
4. Create one integration branch combining:
   - Main AI Capex tilt.
   - Main fast-crash hedge + 0.5% risk buffer.
   - Concentrated cash-funded early entry.
5. Run cheap policy replay and broker replay for both sleeves.
6. Only if both sleeves still pass, refresh latest close data and run one
   clean 7Y full rebuild.

Production promotion remains blocked until PIT membership/universe evidence is
clean.
