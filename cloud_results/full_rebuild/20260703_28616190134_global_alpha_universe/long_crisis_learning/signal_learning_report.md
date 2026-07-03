# Long Crisis Signal Learning

- status: `completed`
- label: `future_63d_drawdown_le_15pct`
- rows: 3913

## Top Signals

| split | feature | auc | spearman | rows |
| --- | --- | ---: | ---: | ---: |
| all | vix_zscore_252d | 0.621 | 0.080 | 3864 |
| all | rate_shock_score | 0.570 | 0.049 | 3913 |
| all | tga_13w_change_pct | 0.562 | 0.041 | 3848 |
| all | volatility_stress_score | 0.509 | 0.006 | 3913 |
| all | credit_stress_score | 0.490 | -0.013 | 3913 |
| holdout | vix_zscore_252d | 0.631 | 0.114 | 1697 |
| holdout | rate_shock_score | 0.621 | 0.106 | 1697 |
| holdout | tga_13w_change_pct | 0.607 | 0.094 | 1697 |
| holdout | volatility_stress_score | 0.537 | 0.033 | 1697 |
| holdout | dxy_ret_20d | 0.516 | 0.014 | 1697 |
| test | m2_6m_change_lag1m | 0.647 | 0.062 | 2090 |
| test | fed_assets_13w_change_pct | 0.578 | 0.032 | 2151 |
| test | net_liquidity_13w_change_pct | 0.561 | 0.025 | 2151 |
| test | tga_13w_change_pct | 0.527 | 0.011 | 2151 |
| test | vix_zscore_252d | 0.505 | 0.002 | 2167 |

Research-only; no production target book changes.
