# Fullrun Ready Gate for Integrated Target Hooks (2026-06-29)

## Current State

The integrated cheap broker replay passes both research targets on the clean 7Y
artifact:

| Sleeve | CAGR | MaxDD | Sharpe |
|---|---:|---:|---:|
| Main | 36.82% | -24.76% | 1.325 |
| Concentrated | 50.07% | -24.96% | 1.477 |

This is not yet production evidence and not a fresh fullrun.

## Blocking Item Before Fullrun

The local clean 7Y cache used for cheap replay is not latest-close current:

- `SPY`: 2019-05-09 to 2026-06-25
- `QQQ`: 2019-05-09 to 2026-06-25
- Main/Concentrated hook evidence therefore reflects the 2026-06-25 close.

Before any fullrun with `skip_collector=true`, refresh data so the latest
regular-session close is present. If latest-close freshness is not proven, do
not use `skip_collector=true`.

## Required Sequence

1. Merge/review the stacked component PRs or run from the integration branch:
   - PR #199: AI Capex late-cycle research screens and Main tilt hook.
   - PR #211: Main fast-crash hedge + 0.5% risk buffer hook.
   - PR #209: Concentrated cash-funded early-entry hook.
   - PR #212: integration evidence branch.

2. Refresh data:

```powershell
gh workflow run free_data_daily_update.yml `
  -R wscha231/r1000-quant-engine `
  --ref codex/integration-main-conc-target-hooks-20260629 `
  -f force_run=true `
  -f max_price_tickers=0
```

3. Confirm latest-close freshness from the workflow artifact or committed
   cache/manifest. Do not proceed if prices are future-dated or stale.

4. Dispatch one full rebuild only after freshness is clean:

```powershell
$envJson = '{"PHASE_AI_CAPEX_MOMENTUM_TILT_ENABLED":"1","PHASE_MAIN_FAST_CRASH_HEDGE_ENABLED":"1","PHASE_CONCENTRATED_CASHFUNDED_EARLY_ENTRY_ENABLED":"1"}'

gh workflow run full_rebuild_manual.yml `
  -R wscha231/r1000-quant-engine `
  --ref codex/integration-main-conc-target-hooks-20260629 `
  -f universe_mode=global_alpha_universe `
  -f backtest_years=7 `
  -f pit_universe_label_clean=false `
  -f skip_collector=true `
  -f fast_mode=true `
  -f leader_rescue_mode=latest_only `
  -f sidecar_profile=official `
  -f artifact_profile=official `
  -f gdrive_sync_mode=official `
  -f portfolio_policy=alphaops_vnext_production `
  -f experiment_env_json=$envJson
```

If data refresh did not update the cache, rerun full rebuild with
`skip_collector=false` or stop and fix the freshness path. Do not run a stale
`skip_collector=true` fullrun.

## Required Fullrun Verification

The fullrun result is acceptable as research evidence only if all are true:

- `metric_mode=broker_ledger_next_close`
- 7Y broker window starts near 2019-06-03 and `years >= 7.0`
- Main CAGR >= 35% and MaxDD >= -25%
- Concentrated CAGR >= 50% and MaxDD >= -25%
- `data_readiness.ready_for_policy_replay=true`
- no future `available_from` leakage
- hooks have nonzero telemetry:
  - Main fast-crash hedge actions emitted.
  - Concentrated cash-funded early-entry applied rows emitted.

Run the verifier before interpreting the run:

```powershell
$py='C:\codex-shadow\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'

& $py tools\verify_alphaops_goal_artifact.py `
  --latest-run <fullrun-artifact-or-outputs-dir> `
  --target-dir <fullrun-artifact-or-outputs-dir>\alphaops_vnext `
  --output-dir <fullrun-artifact-or-outputs-dir>\goal_verifier `
  --expect-pit-unclean
```

## Production Caveat

`pit_universe_label_clean=false` remains a hard production blocker. A passing
fullrun can be classified as clean `research_7y` / `ready_for_human_review`, not
production promotion.

## Forward Operating Cadence

Use this cadence after the integration fullrun lands:

- Daily after the latest regular-session close:
  - run/verify `free_data_daily_update.yml`;
  - confirm no future-dated prices;
  - refresh user-current/order-preview outputs only as review-only artifacts.
- Weekly:
  - run cheap sidecars for hook applied counts, cash usage, 2-week RS telemetry,
    and leader capture drift;
  - do not run full rebuild unless a hook, data source, or market regime changed
    enough to justify the 2-6 hour cost.
- Monthly or after material code/data changes:
  - run one official full rebuild with the integration env flags;
  - run `verify_alphaops_goal_artifact.py`;
  - archive the verifier report with the run.
- Always:
  - keep PIT membership cleanup active in parallel;
  - keep any 2-week RS result as telemetry until a separate broker-ledger A/B
    proves it improves full-period results without OOS collapse.
