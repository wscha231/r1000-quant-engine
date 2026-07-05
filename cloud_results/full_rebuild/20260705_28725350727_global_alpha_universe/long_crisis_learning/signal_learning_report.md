# Long Crisis Signal Learning

- status: `completed`
- label: `future_63d_drawdown_le_15pct`
- rows: 1866

## Top Signals

| split | feature | auc | spearman | rows |
| --- | --- | ---: | ---: | ---: |
| all | rate_shock_score | 0.611 | 0.097 | 1866 |
| all | tga_13w_change_pct | 0.606 | 0.094 | 1801 |
| all | vix_zscore_252d | 0.592 | 0.081 | 1817 |
| all | volatility_stress_score | 0.527 | 0.024 | 1866 |
| all | market_trend_damage_score | 0.489 | -0.010 | 1866 |
| holdout | vix_zscore_252d | 0.626 | 0.110 | 1697 |
| holdout | rate_shock_score | 0.621 | 0.106 | 1697 |
| holdout | tga_13w_change_pct | 0.607 | 0.094 | 1697 |
| holdout | volatility_stress_score | 0.529 | 0.026 | 1697 |
| holdout | dxy_ret_20d | 0.516 | 0.014 | 1697 |
| test | m2_6m_change_lag1m | 0.790 | 0.480 | 43 |
| test | reverse_repo_13w_change_pct | 0.677 | 0.195 | 104 |
| test | liquidity_confirmation_score | 0.614 | 0.104 | 169 |
| test | volatility_stress_score | 0.556 | 0.055 | 169 |
| test | cash_raise_confirmation_score | 0.519 | 0.017 | 169 |

Research-only; no production target book changes.
