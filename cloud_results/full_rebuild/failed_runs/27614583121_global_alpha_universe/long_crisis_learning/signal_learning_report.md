# Long Crisis Signal Learning

- status: `completed`
- label: `future_63d_drawdown_le_15pct`
- rows: 3912

## Top Signals

| split | feature | auc | spearman | rows |
| --- | --- | ---: | ---: | ---: |
| all | vix_zscore_252d | 0.617 | 0.078 | 3863 |
| all | rate_shock_score | 0.583 | 0.058 | 3912 |
| all | tga_13w_change_pct | 0.563 | 0.042 | 3847 |
| all | volatility_stress_score | 0.502 | 0.001 | 3912 |
| all | credit_stress_score | 0.490 | -0.013 | 3912 |
| holdout | vix_zscore_252d | 0.631 | 0.115 | 1683 |
| holdout | rate_shock_score | 0.619 | 0.105 | 1683 |
| holdout | tga_13w_change_pct | 0.607 | 0.094 | 1683 |
| holdout | volatility_stress_score | 0.536 | 0.032 | 1683 |
| holdout | dxy_ret_20d | 0.519 | 0.016 | 1683 |
| test | m2_6m_change_lag1m | 0.649 | 0.062 | 2103 |
| test | fed_assets_13w_change_pct | 0.578 | 0.032 | 2164 |
| test | net_liquidity_13w_change_pct | 0.561 | 0.025 | 2164 |
| test | tga_13w_change_pct | 0.530 | 0.012 | 2164 |
| test | credit_stress_score | 0.500 | nan | 2229 |

Research-only; no production target book changes.
