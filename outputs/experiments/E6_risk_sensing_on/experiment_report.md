# Aggressive Lab Experiment Report

- Experiment: `E6_risk_sensing_on`
- Status: `simplified_layer2_backtest`
- Category: `risk_sensing`
- Description: Connect risk sensing actions into historical backtest in report/challenger mode.
- Backtest executed: `True`
- Production activation allowed: `False`

## Metrics Source

- Metric mode: `simplified_dd_breaker_backtest`
- CAGR: 0.1846609658361189
- Sharpe: 1.1194872875548136
- MaxDD: -0.2162517256738774
- Monthly turnover: None

## Artifact Status

| Artifact | Source | Status |
| --- | --- | --- |
| `risk_sensing_compare.json` | `outputs/strategy_backtest/risk_sensing_compare.json` | `copied` |
| `equity_curve.csv` | `` | `report_only_placeholder` |
| `monthly_allocations.csv` | `` | `report_only_placeholder` |
| `turnover.csv` | `` | `report_only_placeholder` |
| `stress_windows.csv` | `` | `report_only_placeholder` |
| `sleeve_returns.csv` | `outputs/strategy_backtest/risk_sensing_compare.json` | `derived` |
| `trade_journal_summary.md` | `cloud_results/full_rebuild/latest_global_alpha_universe/trade_journal/insights/summary.md` | `copied` |
| `metrics.json` | `` | `derived` |

## Interpretation

E6 is valuable for drawdown research: simplified Layer 2 risk sensing reduced main MaxDD materially, but it also cut CAGR and Sharpe.
This is a discovery candidate for stress defense, not a production policy until Layer 1/3/4 position-aware replay exists.
