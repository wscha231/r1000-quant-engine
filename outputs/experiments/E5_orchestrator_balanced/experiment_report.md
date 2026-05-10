# Aggressive Lab Experiment Report

- Experiment: `E5_orchestrator_balanced`
- Status: `snapshot_report_only`
- Category: `orchestrator`
- Description: 83-month orchestrator backtest with balanced mandate capacities.
- Backtest executed: `False`
- Production activation allowed: `False`

## Metrics Source

- Metric mode: `baseline_performance_metrics_plus_latest_snapshot_orchestrator_delta`
- CAGR: 0.21403316158616126
- Sharpe: 1.1831414285357171
- MaxDD: -0.2727261662085777
- Monthly turnover: 0.4858881015027757

## Artifact Status

| Artifact | Source | Status |
| --- | --- | --- |
| `current_unified_target_latest.json` | `cloud_results/full_rebuild/latest_global_alpha_universe/orchestrator/unified_target_latest.json` | `copied` |
| `orchestrator_comparison.json` | `` | `derived` |
| `proposed_unified_target_latest.json` | `` | `derived` |
| `proposed_unified_target_latest.csv` | `` | `derived` |
| `equity_curve.csv` | `` | `report_only_placeholder` |
| `monthly_allocations.csv` | `` | `derived_snapshot` |
| `sleeve_returns.csv` | `` | `limitation_logged` |
| `turnover.csv` | `` | `report_only_placeholder` |
| `stress_windows.csv` | `cloud_results/full_rebuild/latest_global_alpha_universe` | `limitation_logged` |
| `trade_journal_summary.md` | `cloud_results/full_rebuild/latest_global_alpha_universe/trade_journal/insights/summary.md` | `copied` |
| `metrics.json` | `` | `derived` |

## Interpretation

E5 now has executable orchestrator mechanics for the latest snapshot. Under the neutral matrix, proposed sum-then-cap uses 55% main and 25% concentrated capacity, preserving a 20% cash target unless name caps bind.

This is not yet the requested 83-month orchestrator backtest. The next implementation needs historical monthly raw mandate books or an engine hook that can replay main/concentrated/tactical selections before merge.
