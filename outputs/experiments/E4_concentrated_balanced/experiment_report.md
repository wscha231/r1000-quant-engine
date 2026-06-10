# Aggressive Lab Experiment Report

- Experiment: `E4_concentrated_balanced`
- Status: `standalone_sleeve_policy_audit`
- Category: `concentrated`
- Description: Concentrated alpha as larger orchestrator sleeve with caps and dynamic N.
- Backtest executed: `False`
- Production activation allowed: `False`

## Metrics Source

- Metric mode: `standalone_concentrated_not_full_portfolio`
- CAGR: 0.3484912610130364
- Sharpe: 1.4286886669635341
- MaxDD: -0.22940113109440408
- Monthly turnover: None

## Artifact Status

| Artifact | Source | Status |
| --- | --- | --- |
| `concentrated_policy_audit.json` | `` | `derived_snapshot` |
| `concentrated_policy_audit.csv` | `` | `derived_snapshot` |
| `equity_curve.csv` | `` | `report_only_placeholder` |
| `turnover.csv` | `` | `report_only_placeholder` |
| `stress_windows.csv` | `` | `report_only_placeholder` |
| `monthly_allocations.csv` | `` | `derived_policy` |
| `sleeve_returns.csv` | `cloud_results/full_rebuild/latest_global_alpha_universe/concentrated_backtest_metrics.json` | `derived` |
| `trade_journal_summary.md` | `cloud_results/full_rebuild/latest_global_alpha_universe/trade_journal/insights/summary.md` | `copied` |
| `metrics.json` | `` | `derived` |

## Interpretation

E4 confirms concentrated remains a strong standalone alpha source, but latest cap and entry/risk audit findings block automatic capital expansion.
The next step is an orchestrated historical backtest with these caps and weekly timing rules.
