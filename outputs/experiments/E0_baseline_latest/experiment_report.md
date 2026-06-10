# Aggressive Lab Experiment Report

- Experiment: `E0_baseline_latest`
- Status: `completed`
- Category: `control`
- Description: Current latest production/shadow baseline.
- Control: `True`

## Main Metrics

- CAGR: 0.21403316158616126
- Sharpe: 1.1831414285357171
- MaxDD: -0.2727261662085777
- Monthly turnover: 0.4858881015027757
- Avg stock names: 25.50602409638554

## Concentrated Metrics

- CAGR: 0.3484912610130364
- Sharpe: 1.4286886669635341
- MaxDD: -0.22940113109440408
- Selected names: 5

## Artifact Status

| Artifact | Source | Status |
| --- | --- | --- |
| `metrics.json` | `cloud_results/full_rebuild/latest_global_alpha_universe/reports/baseline_registry.json` | `derived` |
| `equity_curve.csv` | `cloud_results/full_rebuild/latest_global_alpha_universe` | `limitation_logged` |
| `monthly_allocations.csv` | `cloud_results/full_rebuild/latest_global_alpha_universe/reports/global_alpha_sleeve_audit_by_month.csv` | `copied_proxy` |
| `sleeve_returns.csv` | `` | `limitation_logged` |
| `turnover.csv` | `cloud_results/full_rebuild/latest_global_alpha_universe/reports/backtest_window_comparison.csv` | `derived` |
| `stress_windows.csv` | `cloud_results/full_rebuild/latest_global_alpha_universe` | `limitation_logged` |
| `trade_journal_summary.md` | `cloud_results/full_rebuild/latest_global_alpha_universe/trade_journal/insights/summary.md` | `copied` |

## Interpretation

This E0 run normalizes existing baseline artifacts into the aggressive lab output contract. It does not rerun the production engine and is not a challenger.
