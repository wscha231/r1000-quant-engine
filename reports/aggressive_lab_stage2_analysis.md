# Aggressive Lab Stage 2 Analysis

Generated from local report-only runs on `codex/integrate-phase17-19`.
No production defaults, active feature gates, sleeve weights, sector caps, or
broker execution paths were changed.

## What Was Added

- `E1_auto_feature_gates_on` now normalizes the existing auto-learning gate
  candidate and promotion decision into the aggressive lab output contract.
- `E5_orchestrator_balanced` now computes a latest-snapshot orchestrator
  comparison between current max-merge behavior and the proposed balanced
  `sum_then_cap` merge mode.
- Smoke tests now cover E0, E1, and E5 output generation.

## E1 Auto Feature Gates

Input candidate:

- `rs_acceleration_score` bear amplify factor 1.3, IC +0.1406, n 138
- `h1_oversold_value_score` bear amplify factor 1.3, IC +0.1190, n 138
- `theme_phase_multiplier_primary` bear disable factor 0.0, IC -0.1191, n 138
- `theme_phase_multiplier_max` bear disable factor 0.0, IC -0.0874, n 138

Dry-run result from the latest auto-learning promotion artifact:

- Main CAGR: 20.17% vs latest baseline 21.40%
- Sharpe: 1.0972 vs latest baseline 1.1831
- MaxDD: -27.31% vs latest baseline -27.27%
- Trade count: 695
- Promotion approved: false
- Failed checks: `main_cagr_floor`, `main_sharpe_floor`, `main_max_dd_floor`

Interpretation: the signals remain useful research hypotheses, especially
`rs_acceleration_score` and `h1_oversold_value_score` in bear regimes, but the
current candidate package does not pass even discovery-level promotion. The next
code step should make these gates a true isolated historical challenger inside
the scoring/backtest path rather than relying on the prior dry-run artifact.

## E5 Orchestrator Balanced Snapshot

Current latest orchestrator:

- Regime: neutral
- Merge mode: max-style current behavior
- Main capacity: 65%
- Concentrated capacity: 10%
- Invested: 72.44%
- Cash: 27.56%
- Conflict drag: 2.56%p
- Conflicts: 1

Proposed latest-snapshot `sum_then_cap`:

- Main capacity: 55%
- Concentrated capacity: 25%
- Alpha Sprint capacity: 0%
- Unified single-name cap: 20%
- Invested: 80.00%
- Cash: 20.00%
- Capped excess: 0.00%p
- Conflicts: 2
- Positions: 21

Top proposed weights:

- MRVL: 8.92%
- PR: 8.76%
- GEV: 7.36%
- NVDA: 5.34%
- AMKR: 5.04%

Interpretation: the proposed merge mechanics reduce current cash drag by
7.56%p in the latest neutral snapshot without breaching the 20% single-name cap.
This is a structural improvement candidate, but not yet a performance result.

## Discovery Gate Status

- E1: failed discovery. CAGR, Sharpe, and MaxDD all failed primary improvement
  checks.
- E5: failed discovery. Latest-snapshot mechanics are implemented, but no
  historical CAGR, Sharpe, or MaxDD improvement has been measured yet.

These failures are expected and should stay recorded. They prevent accidental
promotion while preserving the research trail.

## Next Code Starting Point

1. Implement a historical E1 challenger hook that applies candidate gates before
   portfolio scoring and writes a full equity curve.
2. Implement an E5 monthly replay hook that captures raw main, concentrated, and
   tactical/alpha-sprint books before merge, then applies each merge mode across
   the full 83-month window.
3. Start Main v2 only after the replay inputs are available, because Main v2
   needs historical scored frames and sleeve-level monthly return series to be
   measured honestly.

The critical missing artifact is a monthly raw mandate book. Latest snapshot
portfolio CSVs are enough to validate merge math, but not enough to claim CAGR
or drawdown improvement.
