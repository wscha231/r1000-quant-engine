# Concentrated Portfolio Report

This report separates latest target recommendations from the current simulated operating account.
- Recommendation date: `2026-05-15`
- Current account last replay trade date: `2026-05-15`
- Current account stale days versus recommendation date: `0`
- Pending orders needed to match recommendation: `0`

## Performance Scorecard

| Horizon | Return | CAGR | Sharpe | MaxDD | Turnover | Trades | End Cash |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1M | -4.39% | -42.08% | -4.112 | -5.10% | 1.94x | 14 | 0.24% |
| 3M | -2.60% | -10.45% | -0.834 | -6.08% | 3.97x | 28 | 0.24% |
| 6M | 8.32% | 17.71% | 1.127 | -9.63% | 8.34x | 65 | 0.24% |
| 1Y | 9.86% | 9.86% | 0.726 | -9.63% | 14.45x | 127 | 0.24% |
| 2Y | 30.62% | 14.30% | 0.839 | -20.17% | 28.98x | 260 | 0.24% |
| 3Y | 67.73% | 18.81% | 1.073 | -20.17% | 44.45x | 396 | 0.24% |
| 5Y | 86.18% | 13.25% | 0.743 | -23.99% | 74.37x | 668 | 0.24% |
| FULL | 195.77% | 16.89% | 0.722 | -33.80% | 66.48x | 936 | 0.24% |

## Files

- `recommendation_latest.csv`: latest target recommendation, formatted as what to buy/hold to target from the latest close.
- `current_operating_holdings_latest.csv`: actual simulated broker-ledger holdings marked to market, including cash.
- `performance_scorecard.csv`: broker-ledger performance by horizon.
- `*_pie.svg` and `*_bar.svg`: visual weights for recommendation/current holdings.

## Top Recommendations

| Ticker | Weight | Current Weight | Action | Trade Delta | Price | Shares per $100k | Logic |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- |
| NVDA | 24.18% | 24.23% | BUY | 0 | 225.32 | 107 | concentrated_selection_source=preferred_final_label; concentrated_preferred_sleeve=True; portfolio_sleeve_label=future_winner; portfolio_defensive_rotation_action=promote_monster_early; theme_holding_profile_primary=long_duration |
| ADI | 23.36% | 23.29% | BUY | 0 | 417.49 | 55 | concentrated_selection_source=preferred_final_label; concentrated_preferred_sleeve=True; portfolio_sleeve_label=future_winner; portfolio_defensive_rotation_action=promote_monster_early; theme_holding_profile_primary=neutral |
| EXPE | 20.89% | 20.91% | BUY | 0 | 217.73 | 95 | concentrated_selection_source=preferred_final_label; concentrated_preferred_sleeve=True; portfolio_sleeve_label=early_scout; portfolio_defensive_rotation_action=neutral; theme_holding_profile_primary=neutral |
| JHG | 20.70% | 20.74% | BUY | 0 | 51.72 | 400 | concentrated_selection_source=preferred_final_label; concentrated_preferred_sleeve=True; portfolio_sleeve_label=early_scout; portfolio_defensive_rotation_action=neutral; theme_holding_profile_primary=neutral |
| MRVL | 5.26% | 5.26% | BUY | 0 | 176.89 | 29 | concentrated_selection_source=monster_extreme_early; concentrated_preferred_sleeve=True; portfolio_sleeve_label=future_winner; portfolio_defensive_rotation_action=promote_monster_early; theme_holding_profile_primary=long_duration |
| CIEN | 3.55% | 3.37% | BUY | 0 | 554.46 | 6 | concentrated_selection_source=monster_extreme_early; concentrated_preferred_sleeve=True; portfolio_sleeve_label=future_winner; portfolio_defensive_rotation_action=promote_monster_early; theme_holding_profile_primary=long_duration |
| MU | 2.05% | 1.96% | BUY | 0 | 724.66 | 2 | concentrated_selection_source=monster_extreme_early; concentrated_preferred_sleeve=True; portfolio_sleeve_label=future_winner; portfolio_defensive_rotation_action=promote_monster_early; theme_holding_profile_primary=long_duration |
| CASH | 0.00% | 0.24% | DEPLOY_CASH | 0 | 1.00 | 0 | residual cash after target stock weights |

## Current Holdings

| Ticker | Current Weight | Target Weight | Action | Trade Delta | Shares | Current Price | Entry Date | Entry Price | Return Since Entry | Entry Reason |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- | ---: | ---: | --- |
| NVDA | 24.23% | 24.18% | HOLD | 0 | 318.00 | 225.32 | 2026-05-15 | 225.32 | 0.00% | target_rebalance |
| ADI | 23.29% | 23.36% | HOLD | 0 | 165.00 | 417.49 | 2026-05-15 | 417.49 | 0.00% | target_rebalance |
| EXPE | 20.91% | 20.89% | HOLD | 0 | 284.00 | 217.73 | 2026-05-15 | 217.73 | 0.00% | target_rebalance |
| JHG | 20.74% | 20.70% | HOLD | 0 | 1186.00 | 51.72 | 2026-05-15 | 51.72 | 0.00% | target_rebalance |
| MRVL | 5.26% | 5.26% | HOLD | 0 | 88.00 | 176.89 | 2026-05-15 | 176.89 | 0.00% | target_rebalance |
| CIEN | 3.37% | 3.55% | HOLD | 0 | 18.00 | 554.46 | 2026-05-15 | 554.46 | 0.00% | target_rebalance |
| MU | 1.96% | 2.05% | HOLD | 0 | 8.00 | 724.66 | 2026-05-15 | 724.66 | 0.00% | target_rebalance |
| CASH | 0.24% | 0.00% | HOLD_CASH | 0 | 0.00 | 1.00 |  | 1.00 | 0.00% | uninvested_cash |
