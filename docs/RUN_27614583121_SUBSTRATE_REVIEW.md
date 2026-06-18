# Run 27614583121 Substrate Review

## Verdict

Run `27614583121` completed at the GitHub Actions workflow level, but it is
Tier 0 `DO_NOT_USE` because the data and universe substrate were dirty. It is
not promotable and must not be used as a clean A/B baseline.

- official verdict: `invalid_window`
- production validity: `false`
- broker window: `2019-06-03` to `2026-06-15` (`7.03y`)
- data readiness: `blocked`
- universe health: `INVALID_UNIVERSE`
- scored_latest rows: `259`
- audited R1000 base count: `234`, below the `400` floor
- official broker-ledger evidence artifact: skipped because the run used `artifact_profile=minimal`

The next step for this run is not T3, replacement cap, bull-floor, reentry,
theme, cap, or era A/B. The next step is universe/data substrate repair.

## Broker Metrics

These metrics are useful diagnostics only. They are not promotion evidence and
not a clean research baseline under the invalid window/universe state. This
does not mean every 7-year broker-ledger run is useless: a clean 7-year run with
data readiness pass and healthy universe is Tier 1 research evidence.

| Portfolio | CAGR | MaxDD | IS-CAGR | OOS/IS | Status |
| --- | ---: | ---: | ---: | ---: | --- |
| Main | `35.01%` | `-26.05%` | `22.36%` | `3.37x` | `invalid_window` |
| Concentrated | `45.00%` | `-25.82%` | `21.65%` | `5.99x` | `invalid_window` |

## Root Blockers

1. The broker replay still starts in `2019-06`, not `2018-06`.
2. The target books do not cover the requested 8-year window.
3. The scored_latest output collapsed to `259` rows and the audited R1000 base count was only `234`.
4. `data_readiness.ready_for_policy_replay=false`.
5. The official evidence artifact was not separately preserved for the minimal 8-year run.

## Immediate Rules

- Stop all T3/recovery A/B from this run because it is Tier 0.
- Clean Tier 1 7-year broker-ledger evidence may support Alpha Plane audit/A-B;
  this run does not qualify because data readiness and universe health failed.
- Do not use run `27614583121` for promotion or as an official A/B baseline.
- Do not use legacy/proxy metrics.
- Do not mutate production targets.
- Do not enable live trading.

## Required Diagnostics

Future full rebuilds must emit:

- `outputs/universe_health/universe_source_audit.json`
- `outputs/universe_health/universe_membership_by_month.csv`
- `outputs/universe_health/scored_row_count_by_date.csv`
- `outputs/universe_health/iwb_fetch_status.json`
- `outputs/universe_health/universe_fallback_decision.md`

Each diagnostic row must carry:

- `date`
- `r1000_base_count`
- `scored_count`
- `candidate_count`
- `price_coverage_pct`
- `fundamental_coverage_pct`
- `universe_source`
- `fallback_used`
- `promotion_allowed`

## Recovery Sequence

1. Fix the IWB/R1000 source chain:
   - live iShares IWB holdings fetch
   - restored Drive/cache IWB holdings
   - previous healthy current-constituents cache
   - committed static IWB seed
   - hard fail
2. Require `scored R1000 base >= 400` before any promotion candidate.
3. Build 8-year target books with start date no later than `2018-06-15`.
4. Rerun official 8-year broker-ledger rebuild.
5. Re-run Alpha Plane audits on clean Tier 1+ evidence.
6. Only then consider research A/B in order; promotion review still requires
   Tier 3/4 evidence or explicit user-approved alternative evidence:
   - T3 hysteresis
   - hard replacement cap
   - bull-floor
   - reentry quality
   - theme leadership
   - concentration cap relaxation
   - era-aware challenger review-only
