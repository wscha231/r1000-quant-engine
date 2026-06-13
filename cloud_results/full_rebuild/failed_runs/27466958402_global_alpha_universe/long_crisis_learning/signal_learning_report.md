# Long Crisis Signal Learning

- status: `completed`
- label: `future_63d_drawdown_le_15pct`
- rows: 3915

## Top Signals

| split | feature | auc | spearman | rows |
| --- | --- | ---: | ---: | ---: |
| all | vix_zscore_252d | 0.616 | 0.077 | 3866 |
| all | rate_shock_score | 0.591 | 0.063 | 3915 |
| all | tga_13w_change_pct | 0.564 | 0.042 | 3850 |
| all | volatility_stress_score | 0.501 | 0.001 | 3915 |
| all | market_trend_damage_score | 0.497 | -0.002 | 3915 |
| holdout | vix_zscore_252d | 0.630 | 0.114 | 1683 |
| holdout | rate_shock_score | 0.619 | 0.105 | 1683 |
| holdout | tga_13w_change_pct | 0.607 | 0.094 | 1683 |
| holdout | volatility_stress_score | 0.536 | 0.032 | 1683 |
| holdout | dxy_ret_20d | 0.519 | 0.016 | 1683 |
| test | m2_6m_change_lag1m | 0.650 | 0.063 | 2106 |
| test | fed_assets_13w_change_pct | 0.578 | 0.032 | 2167 |
| test | net_liquidity_13w_change_pct | 0.561 | 0.025 | 2167 |
| test | tga_13w_change_pct | 0.530 | 0.013 | 2167 |
| test | credit_stress_score | 0.500 | nan | 2232 |

Research-only; no production target book changes.
