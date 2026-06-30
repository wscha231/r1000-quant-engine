# Integration Target Hooks Result (2026-06-29)

## Summary

This integration branch combines the currently surviving Main and
Concentrated default-OFF research hooks:

- Main:
  - `PHASE_AI_CAPEX_MOMENTUM_TILT_ENABLED=1`
  - `PHASE_MAIN_FAST_CRASH_HEDGE_ENABLED=1`
- Concentrated:
  - `PHASE_CONCENTRATED_CASHFUNDED_EARLY_ENTRY_ENABLED=1`

The integration replay is still research-only. It uses the clean 7Y artifact
and local broker-ledger replay; it is not a full rebuild and not a production
promotion.

## Reference Baseline

Artifact: `artifacts/28074476465/outputs/account_evaluation/official_metrics.json`

| Sleeve | CAGR | MaxDD | Sharpe |
|---|---:|---:|---:|
| Main | 33.15% | -26.02% | 1.219 |
| Concentrated | 46.24% | -25.82% | 1.421 |

## Integrated Cheap Broker Replay

Target-book output:
`artifacts/28074476465/integration_main_conc_target_hooks_20260629/`

Broker settings:

- `broker_ledger_next_close`
- Integer shares
- 25 bps cost
- Max fill lag 7 days
- Window 2019-06-03 to 2026-06-25

| Sleeve | CAGR | MaxDD | Sharpe | Avg Cash | Trades |
|---|---:|---:|---:|---:|---:|
| Main | 36.82% | -24.76% | 1.325 | 27.02% | 1660 |
| Concentrated | 50.07% | -24.96% | 1.477 | 40.88% | 653 |

Both sleeves clear the current research targets:

- Main: CAGR >= 35%, MaxDD >= -25%
- Concentrated: CAGR >= 50%, MaxDD >= -25%

## Applied Counts

- Main fast-crash hedge fired on 2 rebalance dates.
- Main fast-crash risk buffer was 0.5% while the hedge phase was enabled.
- Concentrated cash-funded early entry applied on 44 rows.

## Side-Path Decisions

### Kept

- AI Capex bottleneck/momentum tilt for Main CAGR.
- Funded fast-crash hedge for Main crash convexity.
- Small generic Main risk buffer because the unbuffered result was only
  `-25.003%` MaxDD.
- Concentrated cash-funded early entry because it directly deploys idle cash
  into PIT-ranked unheld leaders without selling existing winners.
- Read-only goal verifier. This is not an alpha lever; it prevents accidental
  manual promotion by checking both sleeves, hook telemetry, and the PIT
  production blocker from one command.

### Rejected

- Main trend-break hedge variants. They worsened MaxDD in cheap broker probes.
- Direct 2-week RS scoring. Keep it as sidecar/telemetry only until a separate
  broker-ledger A/B proves it is stable OOS and not a chase/whipsaw signal.
  The only acceptable promotion path is a default-OFF timing tie-breaker, not a
  broad unconditional score term.

### Sidecar-Only Candidates

- 2-week RS comparison remains useful as a timing diagnostic. The integration
  branch now emits `2w` RS telemetry from the same PIT price-cache path used for
  `1w`, `1m`, `3m`, and `6m`, but it does not enter `score_total`. Promote it
  only after a forward-blind screen and broker-ledger A/B show full-period
  value. The current passing integration already has three active levers, so
  adding a fourth unproven score feature would blur attribution.
  A new read-only sidecar (`tools/run_rs_2w_entry_timing_screen.py`) now audits
  this automatically. On the clean 7Y concentrated early-entry artifact it found
  `2w_rs_positive` mean 126d excess `+3.80%` with `48.57%` hit rate, while
  `1w_rs_positive` was stronger at `+6.73%` and `57.14%`. The `2w_rs_top_half`
  bucket was useful (`+6.92%`, `63.64%`) but not enough to justify direct score
  mutation without a separate broker-ledger A/B. The sidecar has been upgraded
  to schema v2 so `2w_rs_top_half` can be surfaced as a default-OFF timing
  tie-breaker candidate when it clears observation/OOS thresholds. A follow-up
  cheap broker A/B (`tools/run_rs_timing_tiebreaker_broker_ab.py`) tested that
  candidate by removing failing cash-funded early-entry rows and returning the
  weight to cash. Result: reject. Baseline Concentrated was `50.07%` CAGR /
  `-24.96%` MaxDD; `rs2w_positive` was `49.88%` / `-24.82%`; `rs2w_is_median`
  was `49.52%` / `-25.60%`. Therefore 2-week RS remains useful as timing
  telemetry, but should not be promoted to direct scoring, a tie-breaker, or a
  fullrun flag.
- Rejected trend-break hedge variants can still contribute to future crash
  diagnostics as stress labels, not as target-book actions.
- Broad hold/rescue variants remain rejected as policy hooks, but their
  whipsaw rows are useful for post-trade attribution and for testing narrower
  thesis-intact hold candidates.

## Important Caveats

- This is not production evidence because `pit_universe_label_clean=false`
  still blocks production promotion.
- This is not a fresh-data fullrun. It reuses the clean 7Y artifact.
- PR stacking still matters:
  - Main AI Capex tilt dependency.
  - Main fast-crash hedge hook.
  - Concentrated cash-funded early-entry hook.
- A final fullrun should wait until the hooks are reviewed/merged or explicitly
  run from an integration branch with fresh latest-close data and clean
  preflight.

## Next Step

1. Review/merge the component PRs.
2. Keep this integration branch as the combined evidence path.
3. Refresh latest close data.
4. Run one full rebuild only after cheap preflight confirms the same hooks are
   active and data freshness is clean.
5. Continue PIT membership cleanup in parallel.
6. Run `tools/verify_alphaops_goal_artifact.py` against the fullrun artifact
   before interpreting the result.
