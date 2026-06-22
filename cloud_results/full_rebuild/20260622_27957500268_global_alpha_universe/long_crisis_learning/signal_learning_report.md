# Long Crisis Signal Learning

- status: `completed`
- label: `future_63d_drawdown_le_15pct`
- rows: 3914

## Top Signals

| split | feature | auc | spearman | rows |
| --- | --- | ---: | ---: | ---: |
| all | vix_zscore_252d | 0.618 | 0.078 | 3865 |
| all | rate_shock_score | 0.579 | 0.055 | 3914 |
| all | tga_13w_change_pct | 0.563 | 0.042 | 3849 |
| all | volatility_stress_score | 0.503 | 0.002 | 3914 |
| all | credit_stress_score | 0.490 | -0.013 | 3914 |
| holdout | vix_zscore_252d | 0.631 | 0.115 | 1689 |
| holdout | rate_shock_score | 0.620 | 0.105 | 1689 |
| holdout | tga_13w_change_pct | 0.607 | 0.094 | 1689 |
| holdout | volatility_stress_score | 0.537 | 0.033 | 1689 |
| holdout | dxy_ret_20d | 0.518 | 0.016 | 1689 |
| test | m2_6m_change_lag1m | 0.649 | 0.062 | 2099 |
| test | fed_assets_13w_change_pct | 0.578 | 0.032 | 2160 |
| test | net_liquidity_13w_change_pct | 0.561 | 0.025 | 2160 |
| test | tga_13w_change_pct | 0.529 | 0.012 | 2160 |
| test | credit_stress_score | 0.500 | nan | 2225 |

Research-only; no production target book changes.
