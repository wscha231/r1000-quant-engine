# Aggressive Lab Experiment Report

- Experiment: `E9_kitchen_sink_all_on`
- Status: `snapshot_discovery_only`
- Category: `discovery_stress`
- Description: Discovery-only all-on experiment. Not a production candidate.
- Backtest executed: `False`
- Production activation allowed: `False`

## Metrics Source

- Metric mode: `baseline_performance_metrics_plus_all_on_snapshot`
- CAGR: 0.21403316158616126
- Sharpe: 1.1831414285357171
- MaxDD: -0.2727261662085777
- Monthly turnover: 0.4858881015027757

## Artifact Status

| Artifact | Source | Status |
| --- | --- | --- |
| `kitchen_sink_unified_latest.json` | `` | `derived_snapshot` |
| `kitchen_sink_unified_latest.csv` | `` | `derived_snapshot` |
| `source_audit.json` | `` | `derived` |
| `equity_curve.csv` | `` | `report_only_placeholder` |
| `sleeve_returns.csv` | `` | `report_only_placeholder` |
| `turnover.csv` | `` | `report_only_placeholder` |
| `stress_windows.csv` | `` | `report_only_placeholder` |
| `monthly_allocations.csv` | `` | `derived_snapshot` |
| `trade_journal_summary.md` | `cloud_results/full_rebuild/latest_global_alpha_universe/trade_journal/insights/summary.md` | `copied` |
| `metrics.json` | `` | `derived` |

## Interpretation

E9 is intentionally wild-lab only. It combines Main v2, concentrated, and sprint/tactical hooks in a latest neutral snapshot.
It cannot be promoted; its purpose is to expose conflicts, cap behavior, and missing historical replay requirements.
