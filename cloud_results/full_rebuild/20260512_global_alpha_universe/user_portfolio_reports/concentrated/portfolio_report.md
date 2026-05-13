# Concentrated Portfolio Report

This report separates latest target recommendations from the current simulated operating account.
- Recommendation date: `2026-05-12`
- Current account last replay trade date: `2026-03-02`
- Current account stale days versus recommendation date: `71`
- Pending orders needed to match recommendation: `6`

## Performance Scorecard

| Horizon | Return | CAGR | Sharpe | MaxDD | Turnover | Trades | End Cash |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1M | -2.00% | -22.42% | -0.890 | -7.61% | 0.00x | 0 | 0.01% |
| 3M | 5.10% | 22.67% | 1.178 | -7.61% | 1.94x | 6 | 0.01% |
| 6M | 43.47% | 107.18% | 2.498 | -15.53% | 5.41x | 20 | 0.01% |
| 1Y | 81.25% | 81.33% | 2.197 | -18.55% | 11.77x | 48 | 0.01% |
| 2Y | 114.32% | 46.51% | 1.602 | -20.24% | 23.45x | 101 | 0.01% |
| 3Y | 250.89% | 51.94% | 1.610 | -22.76% | 35.72x | 155 | 0.01% |
| 5Y | 320.34% | 33.27% | 1.185 | -32.99% | 63.84x | 271 | 0.01% |
| FULL | 787.47% | 36.41% | 1.186 | -38.45% | 33.23x | 394 | 0.01% |

## Files

- `recommendation_latest.csv`: latest target recommendation, formatted as what to buy/hold to target from the latest close.
- `current_operating_holdings_latest.csv`: actual simulated broker-ledger holdings marked to market, including cash.
- `performance_scorecard.csv`: broker-ledger performance by horizon.
- `*_pie.svg` and `*_bar.svg`: visual weights for recommendation/current holdings.

## Top Recommendations

| Ticker | Weight | Current Weight | Action | Trade Delta | Price | Shares per $100k | Logic |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- |
| GLW | 37.78% | 0.00% | BUY | 335,260 | 196.16 | 192 | concentrated_selection_source=monster_extreme_early; concentrated_preferred_sleeve=True; portfolio_sleeve_label=future_winner; portfolio_defensive_rotation_action=promote_monster_early; theme_holding_profile_primary=neutral |
| WDC | 35.68% | 0.00% | BUY | 316,680 | 480.90 | 74 | concentrated_selection_source=monster_extreme_early; concentrated_preferred_sleeve=True; portfolio_sleeve_label=future_winner; portfolio_defensive_rotation_action=promote_monster_early; theme_holding_profile_primary=long_duration |
| MU | 26.54% | 0.00% | BUY | 235,530 | 751.24 | 35 | concentrated_selection_source=monster_extreme_early; concentrated_preferred_sleeve=True; portfolio_sleeve_label=future_winner; portfolio_defensive_rotation_action=promote_monster_early; theme_holding_profile_primary=long_duration |
| CASH | 0.00% | 0.01% | DEPLOY_CASH | 0 | 1.00 | 0 | residual cash after target stock weights |

## Current Holdings

| Ticker | Current Weight | Target Weight | Action | Trade Delta | Shares | Current Price | Entry Date | Entry Price | Return Since Entry | Entry Reason |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- | ---: | ---: | --- |
| ETR | 40.00% | 0.00% | SELL | -355,018 | 3143.00 | 112.96 | 2026-03-02 | 106.05 | 6.51% | target_rebalance |
| PR | 39.83% | 0.00% | SELL | -353,458 | 17537.00 | 20.16 | 2026-03-02 | 18.63 | 8.16% | target_rebalance |
| PEG | 20.16% | 0.00% | SELL | -178,911 | 2269.00 | 78.85 | 2026-03-02 | 83.83 | -5.94% | target_rebalance |
| CASH | 0.01% | 0.00% | DEPLOY_CASH | 0 | 0.00 | 1.00 |  | 1.00 | 0.00% | uninvested_cash |
