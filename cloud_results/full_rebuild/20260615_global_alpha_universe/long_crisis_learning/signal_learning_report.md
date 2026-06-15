# Long Crisis Signal Learning

- status: `completed`
- label: `future_63d_drawdown_le_15pct`
- rows: 1846

## Top Signals

| split | feature | auc | spearman | rows |
| --- | --- | ---: | ---: | ---: |
| all | rate_shock_score | 0.610 | 0.097 | 1846 |
| all | tga_13w_change_pct | 0.604 | 0.093 | 1781 |
| all | vix_zscore_252d | 0.594 | 0.083 | 1797 |
| all | volatility_stress_score | 0.525 | 0.023 | 1846 |
| all | market_trend_damage_score | 0.489 | -0.010 | 1846 |
| holdout | vix_zscore_252d | 0.628 | 0.113 | 1683 |
| holdout | rate_shock_score | 0.619 | 0.105 | 1683 |
| holdout | tga_13w_change_pct | 0.607 | 0.094 | 1683 |
| holdout | volatility_stress_score | 0.530 | 0.027 | 1683 |
| holdout | dxy_ret_20d | 0.519 | 0.016 | 1683 |
| test | m2_6m_change_lag1m | 0.740 | 0.413 | 37 |
| test | reverse_repo_13w_change_pct | 0.709 | 0.238 | 98 |
| test | liquidity_confirmation_score | 0.642 | 0.133 | 163 |
| test | rate_shock_score | 0.537 | 0.034 | 163 |
| test | volatility_stress_score | 0.526 | 0.027 | 163 |

Research-only; no production target book changes.
