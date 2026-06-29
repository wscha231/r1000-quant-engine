# Long Crisis Signal Learning

- status: `completed`
- label: `future_63d_drawdown_le_15pct`
- rows: 1862

## Top Signals

| split | feature | auc | spearman | rows |
| --- | --- | ---: | ---: | ---: |
| all | rate_shock_score | 0.610 | 0.096 | 1862 |
| all | tga_13w_change_pct | 0.606 | 0.094 | 1797 |
| all | vix_zscore_252d | 0.591 | 0.081 | 1813 |
| all | volatility_stress_score | 0.526 | 0.024 | 1862 |
| all | market_trend_damage_score | 0.489 | -0.010 | 1862 |
| holdout | vix_zscore_252d | 0.625 | 0.110 | 1693 |
| holdout | rate_shock_score | 0.620 | 0.105 | 1693 |
| holdout | tga_13w_change_pct | 0.607 | 0.094 | 1693 |
| holdout | volatility_stress_score | 0.528 | 0.025 | 1693 |
| holdout | dxy_ret_20d | 0.517 | 0.015 | 1693 |
| test | m2_6m_change_lag1m | 0.790 | 0.480 | 43 |
| test | reverse_repo_13w_change_pct | 0.677 | 0.195 | 104 |
| test | liquidity_confirmation_score | 0.614 | 0.104 | 169 |
| test | volatility_stress_score | 0.556 | 0.055 | 169 |
| test | cash_raise_confirmation_score | 0.519 | 0.017 | 169 |

Research-only; no production target book changes.
