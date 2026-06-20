# Long Crisis Signal Learning

- status: `completed`
- label: `future_63d_drawdown_le_15pct`
- rows: 3914

## Top Signals

| split | feature | auc | spearman | rows |
| --- | --- | ---: | ---: | ---: |
| all | vix_zscore_252d | 0.618 | 0.078 | 3865 |
| all | rate_shock_score | 0.582 | 0.057 | 3914 |
| all | tga_13w_change_pct | 0.563 | 0.042 | 3849 |
| all | volatility_stress_score | 0.502 | 0.002 | 3914 |
| all | credit_stress_score | 0.490 | -0.013 | 3914 |
| holdout | vix_zscore_252d | 0.631 | 0.115 | 1687 |
| holdout | rate_shock_score | 0.619 | 0.105 | 1687 |
| holdout | tga_13w_change_pct | 0.607 | 0.094 | 1687 |
| holdout | volatility_stress_score | 0.537 | 0.033 | 1687 |
| holdout | dxy_ret_20d | 0.519 | 0.016 | 1687 |
| test | m2_6m_change_lag1m | 0.649 | 0.062 | 2101 |
| test | fed_assets_13w_change_pct | 0.578 | 0.032 | 2162 |
| test | net_liquidity_13w_change_pct | 0.561 | 0.025 | 2162 |
| test | tga_13w_change_pct | 0.529 | 0.012 | 2162 |
| test | credit_stress_score | 0.500 | nan | 2227 |

Research-only; no production target book changes.
