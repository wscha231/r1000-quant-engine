# Concentrated Portfolio Report

This report separates latest target recommendations from the current simulated operating account.
- Recommendation date: `2026-05-14`
- Current account last replay trade date: `2026-05-14`
- Current account stale days versus recommendation date: `0`
- Pending orders needed to match recommendation: `1`

## Performance Scorecard

| Horizon | Return | CAGR | Sharpe | MaxDD | Turnover | Trades | End Cash |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1M | -2.35% | -25.10% | -1.437 | -6.67% | 1.81x | 10 | 0.23% |
| 3M | 2.96% | 13.18% | 0.890 | -6.67% | 3.49x | 20 | 0.23% |
| 6M | 55.61% | 144.08% | 3.364 | -6.67% | 6.57x | 41 | 0.23% |
| 1Y | 63.39% | 63.45% | 2.172 | -10.99% | 13.69x | 88 | 0.23% |
| 2Y | 101.39% | 41.95% | 1.742 | -16.08% | 25.20x | 178 | 0.23% |
| 3Y | 224.16% | 48.04% | 1.699 | -16.08% | 37.87x | 270 | 0.23% |
| 5Y | 298.16% | 31.83% | 1.332 | -22.68% | 62.35x | 459 | 0.23% |
| FULL | 730.61% | 35.10% | 1.300 | -22.68% | 33.25x | 649 | 0.23% |

## Files

- `recommendation_latest.csv`: latest target recommendation, formatted as what to buy/hold to target from the latest close.
- `current_operating_holdings_latest.csv`: actual simulated broker-ledger holdings marked to market, including cash.
- `performance_scorecard.csv`: broker-ledger performance by horizon.
- `*_pie.svg` and `*_bar.svg`: visual weights for recommendation/current holdings.

## Top Recommendations

| Ticker | Weight | Current Weight | Action | Trade Delta | Price | Shares per $100k | Logic |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- |
| FIX | 50.00% | 49.69% | BUY | 2,569 | 2043.24 | 24 | concentrated_selection_source=preferred_final_label; concentrated_preferred_sleeve=True; portfolio_sleeve_label=future_winner; portfolio_defensive_rotation_action=promote_monster_early; theme_holding_profile_primary=neutral |
| NVDA | 12.50% | 0.00% | BUY | 0 | 235.72 | 53 | concentrated_selection_source=preferred_final_label; concentrated_preferred_sleeve=True; portfolio_sleeve_label=future_winner; portfolio_defensive_rotation_action=promote_monster_early; theme_holding_profile_primary=long_duration |
| MRVL | 12.50% | 0.00% | BUY | 0 | 184.61 | 67 | concentrated_selection_source=monster_extreme_early; concentrated_preferred_sleeve=True; portfolio_sleeve_label=future_winner; portfolio_defensive_rotation_action=promote_monster_early; theme_holding_profile_primary=long_duration |
| MU | 12.50% | 0.00% | BUY | 0 | 794.10 | 15 | concentrated_selection_source=monster_extreme_early; concentrated_preferred_sleeve=True; portfolio_sleeve_label=future_winner; portfolio_defensive_rotation_action=promote_monster_early; theme_holding_profile_primary=long_duration |
| CIEN | 12.50% | 0.00% | BUY | 0 | 584.68 | 21 | concentrated_selection_source=monster_extreme_early; concentrated_preferred_sleeve=True; portfolio_sleeve_label=future_winner; portfolio_defensive_rotation_action=promote_monster_early; theme_holding_profile_primary=long_duration |
| CASH | 0.00% | 0.23% | DEPLOY_CASH | 0 | 1.00 | 0 | residual cash after target stock weights |

## Current Holdings

| Ticker | Current Weight | Target Weight | Action | Trade Delta | Shares | Current Price | Entry Date | Entry Price | Return Since Entry | Entry Reason |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- | ---: | ---: | --- |
| FIX | 49.69% | 50.00% | BUY | 2,569 | 202.00 | 2043.24 | 2026-05-14 | 2043.24 | 0.00% | target_rebalance |
| CIEN | 12.53% | 0.00% | HOLD | 0 | 178.00 | 584.68 | 2026-05-14 | 584.68 | 0.00% | target_rebalance |
| MU | 12.52% | 0.00% | HOLD | 0 | 131.00 | 794.10 | 2026-05-14 | 794.10 | 0.00% | target_rebalance |
| NVDA | 12.52% | 0.00% | HOLD | 0 | 441.00 | 235.72 | 2026-05-14 | 235.72 | 0.00% | target_rebalance |
| MRVL | 12.51% | 0.00% | HOLD | 0 | 563.00 | 184.61 | 2026-05-14 | 184.61 | 0.00% | target_rebalance |
| CASH | 0.23% | 50.00% | DEPLOY_CASH | 0 | 0.00 | 1.00 |  | 1.00 | 0.00% | uninvested_cash |
