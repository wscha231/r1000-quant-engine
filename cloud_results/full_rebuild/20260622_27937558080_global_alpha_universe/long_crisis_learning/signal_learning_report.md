# Long Crisis Signal Learning

- status: `completed`
- label: `future_63d_drawdown_le_15pct`
- rows: 1830

## Top Signals

| split | feature | auc | spearman | rows |
| --- | --- | ---: | ---: | ---: |
| all | rate_shock_score | 0.611 | 0.098 | 1830 |
| all | vix_zscore_252d | 0.608 | 0.097 | 1781 |
| all | tga_13w_change_pct | 0.600 | 0.090 | 1765 |
| all | volatility_stress_score | 0.532 | 0.029 | 1830 |
| all | dxy_ret_20d | 0.486 | -0.013 | 1810 |
| holdout | vix_zscore_252d | 0.638 | 0.121 | 1687 |
| holdout | rate_shock_score | 0.619 | 0.105 | 1687 |
| holdout | tga_13w_change_pct | 0.607 | 0.094 | 1687 |
| holdout | volatility_stress_score | 0.535 | 0.031 | 1687 |
| holdout | dxy_ret_20d | 0.519 | 0.016 | 1687 |
| test | reverse_repo_13w_change_pct | 0.790 | 0.363 | 78 |
| test | m2_6m_change_lag1m | 0.750 | nan | 17 |
| test | liquidity_confirmation_score | 0.709 | 0.212 | 143 |
| test | cash_raise_confirmation_score | 0.599 | 0.095 | 143 |
| test | volatility_stress_score | 0.577 | 0.086 | 143 |

Research-only; no production target book changes.
