# Aggressive Lab Plan

Date: 2026-05-03 KST
Branch: `codex/integrate-phase17-19`
Mode: research-only challenger lab

## Purpose

The aggressive lab exists to turn dormant and sidecar capabilities on in
isolated challenger experiments while preserving production defaults.

Core rule:

```text
Production stays protected. Aggressive tests run only through experiment
overrides and isolated outputs. Passing discovery is not production approval.
```

## Directory Layout

```text
research/aggressive_lab_202605/
  experiment_matrix.yaml
  discovery_gates.yaml
  production_gates.yaml
```

Future report outputs:

```text
outputs/experiments/{experiment_id}/metrics.json
outputs/experiments/{experiment_id}/equity_curve.csv
outputs/experiments/{experiment_id}/monthly_allocations.csv
outputs/experiments/{experiment_id}/sleeve_returns.csv
outputs/experiments/{experiment_id}/turnover.csv
outputs/experiments/{experiment_id}/stress_windows.csv
outputs/experiments/{experiment_id}/trade_journal_summary.md
outputs/experiments/{experiment_id}/experiment_report.md
```

## Common Assumptions

- Universe: `global_alpha_universe`.
- Backtest years requested: 8.
- Current available latest window: 83 months.
- Starting capital: USD 100,000.
- Trade cost: 25 bps per side.
- Baseline: latest main and concentrated from baseline registry.
- Production defaults: unchanged.
- Failed experiments: retained and summarized.

## Initial Experiment Matrix

| ID | Purpose | Production risk |
| --- | --- | --- |
| `E0_baseline_latest` | Reproduce latest production/shadow baseline | None |
| `E1_auto_feature_gates_on` | Test current auto feature gate candidate | Challenger only |
| `E2_main_v2_balanced` | Test 15-name high-conviction main | Challenger only |
| `E3_main_v2_aggressive` | Test 12-name higher-conviction main | Challenger only |
| `E4_concentrated_balanced` | Test larger concentrated sleeve with caps | Challenger only |
| `E5_orchestrator_balanced` | Test 83-month orchestrator and merge modes | Challenger only |
| `E6_risk_sensing_on` | Test historical risk sensing actions | Challenger only |
| `E7_tactical_bull_only` | Test tactical sleeve only in bull regimes | Challenger only |
| `E8_alpha_sprint_sidecar` | Test new bull-only Alpha Sprint sidecar | Research only |
| `E9_kitchen_sink_all_on` | Discovery-only all-on stress test | Never production candidate |

## Discovery Gates

Discovery means "worth more research", not "ship it".

A candidate passes discovery if it improves at least one of:

- CAGR by 2.0 percentage points or more.
- MaxDD by 2.0 percentage points or more.
- Sharpe by 0.08 or more.

And also:

- Monthly turnover worsens by no more than 10.0 percentage points.
- Trade count is at least 250 when trade-journal evidence is used.
- Required output artifacts exist.
- No production default changed.

## Production Gates

Production promotion requires all of:

- CAGR improvement at least 3.0 percentage points.
- MaxDD no worse than -25%.
- Sharpe at least 1.20.
- Monthly turnover at or below 35%.
- Zero cap violations.
- Stress windows improve or have documented risk tradeoff.
- Human approval recorded.

These gates are intentionally stricter than discovery because current main has
high turnover and latest MaxDD is worse than the control.

## Main v2 Balanced

Candidate:

```yaml
main_v2_enabled: true
main_target_n: 15
main_sleeve_weights:
  core: 0.25
  future_winner: 0.55
  early_scout: 0.20
sleeve_rebalance_months:
  core: 3
  future_winner: 2
  early_scout: 1
single_name_cap: 0.15
incumbent_buffer: 3
```

Bear adjustments to test only inside the challenger:

- disable weak theme multipliers
- amplify `rs_acceleration_score`
- amplify `h1_oversold_value_score`

## Concentrated Balanced

Candidate capacity:

```yaml
deep_bear: 0.00
bear: 0.05
neutral: 0.20
bull: 0.25
strong_bull: 0.30
```

Required risk constraints:

- single-name cap: 25%
- theme cap: 45%
- sector cap: 55%
- unified single-name cap after orchestrator: 18-20%
- weekly review
- staged entry
- hard stop and trailing stop tests

## Orchestrator Balanced

Candidate neutral allocation:

```yaml
neutral:
  main: 0.55
  concentrated: 0.25
  alpha_sprint: 0.00
  cash: 0.20
```

Merge modes to test:

- `max`
- `sum_then_cap`
- `priority_concentrated`
- `risk_budget_blend`

Recommended first challenger:

```text
sum_then_cap + unified cap
```

Reason:

- Latest max-merge output leaves 27.56% cash in neutral.
- A sum-then-cap mode can reduce cash drag while still enforcing a hard
  per-name cap.

## Risk Sensing

First test should be report/challenger only:

- O'Neil hard stop: -8%.
- Trailing stop: -15%.
- RS break threshold: -30 percentage points.
- Portfolio drawdown breaker enabled.
- Swap engine enabled as recommendation, not broker execution.

Do not connect this to live broker orders.

## Alpha Sprint

Research-only sidecar:

- bull capacity: 5%.
- strong bull capacity: 10%.
- exceptional regime capacity: 15% only if later defined and validated.
- N: 2-5.
- hard stop: -6% to -8%.
- time stop: 20-30 days.
- staged entry required.

Candidate signals:

- `rs_acceleration_score`
- `breakout_fresh_20d`
- `breakout_volume_z`
- `volatility_contraction_score`
- `entry_quality_score`
- earnings or revision confirmation
- theme acceleration
- stage2 overextension block

Use `explosion_*` if nonzero and validated, but do not depend on it.

## Runner Requirements

The future runner should:

- Read `experiment_matrix.yaml`.
- Apply overrides to a copied config object or explicit experiment adapter.
- Write only under `outputs/experiments/{experiment_id}`.
- Emit a failure report when an experiment cannot run.
- Capture git commit, config fingerprint, data source paths, and dirty status.
- Never write active production config or active gate files.

Suggested future file:

```text
tools/run_aggressive_lab.py
```

No runner is implemented in this planning batch.

## Approval Boundary

This plan authorizes only creation of lab configuration files. Implementing the
runner, Main v2, Alpha Sprint, or orchestrator backtest requires separate
approval.
