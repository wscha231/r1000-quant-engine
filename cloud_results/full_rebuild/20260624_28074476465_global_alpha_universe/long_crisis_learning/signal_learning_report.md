# Long Crisis Signal Learning

- status: `completed`
- label: `future_63d_drawdown_le_15pct`
- rows: 3913

## Top Signals

| split | feature | auc | spearman | rows |
| --- | --- | ---: | ---: | ---: |
| all | vix_zscore_252d | 0.619 | 0.079 | 3864 |
| all | rate_shock_score | 0.576 | 0.053 | 3913 |
| all | tga_13w_change_pct | 0.563 | 0.042 | 3848 |
| all | volatility_stress_score | 0.503 | 0.002 | 3913 |
| all | credit_stress_score | 0.490 | -0.013 | 3913 |
| holdout | vix_zscore_252d | 0.631 | 0.115 | 1690 |
| holdout | rate_shock_score | 0.620 | 0.105 | 1690 |
| holdout | tga_13w_change_pct | 0.607 | 0.094 | 1690 |
| holdout | volatility_stress_score | 0.537 | 0.033 | 1690 |
| holdout | dxy_ret_20d | 0.518 | 0.016 | 1690 |
| test | m2_6m_change_lag1m | 0.648 | 0.062 | 2097 |
| test | fed_assets_13w_change_pct | 0.578 | 0.032 | 2158 |
| test | net_liquidity_13w_change_pct | 0.561 | 0.025 | 2158 |
| test | tga_13w_change_pct | 0.528 | 0.012 | 2158 |
| test | vix_zscore_252d | 0.500 | 0.000 | 2174 |

Research-only; no production target book changes.
