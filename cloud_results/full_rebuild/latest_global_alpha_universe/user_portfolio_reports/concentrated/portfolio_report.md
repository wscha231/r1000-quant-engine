# Concentrated Portfolio Report

This report separates latest target recommendations from the current simulated operating account.
- Recommendation date: `2026-05-13`
- Current account last replay trade date: `2026-03-02`
- Current account stale days versus recommendation date: `72`
- Pending orders needed to match recommendation: `6`

## Performance Scorecard

| Horizon | Return | CAGR | Sharpe | MaxDD | Turnover | Trades | End Cash |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1M | -1.55% | -17.36% | -0.652 | -7.48% | 0.00x | 0 | 13.96% |
| 3M | 5.81% | 26.08% | 1.298 | -7.48% | 1.63x | 4 | 13.96% |
| 6M | 55.19% | 142.76% | 2.971 | -10.32% | 4.99x | 14 | 13.96% |
| 1Y | 56.06% | 56.11% | 1.619 | -21.87% | 12.96x | 35 | 13.96% |
| 2Y | 107.06% | 43.93% | 1.500 | -28.71% | 26.24x | 73 | 13.96% |
| 3Y | 217.65% | 47.09% | 1.413 | -29.60% | 38.93x | 111 | 13.96% |
| 5Y | 258.97% | 29.13% | 1.056 | -32.56% | 66.62x | 195 | 13.96% |
| FULL | 513.27% | 29.42% | 1.078 | -32.56% | 38.23x | 280 | 13.96% |

## Files

- `recommendation_latest.csv`: latest target recommendation, formatted as what to buy/hold to target from the latest close.
- `current_operating_holdings_latest.csv`: actual simulated broker-ledger holdings marked to market, including cash.
- `performance_scorecard.csv`: broker-ledger performance by horizon.
- `*_pie.svg` and `*_bar.svg`: visual weights for recommendation/current holdings.

## Top Recommendations

| Ticker | Weight | Current Weight | Action | Trade Delta | Price | Shares per $100k | Logic |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- |
| ON | 38.29% | 0.00% | BUY | 234,819 | 115.71 | 330 | concentrated_selection_source=preferred_final_label; concentrated_preferred_sleeve=True; portfolio_sleeve_label=early_scout; portfolio_defensive_rotation_action=promote_monster_early; theme_holding_profile_primary=neutral |
| WDC | 27.57% | 0.00% | BUY | 169,070 | 494.09 | 55 | concentrated_selection_source=monster_extreme_early; concentrated_preferred_sleeve=True; portfolio_sleeve_label=future_winner; portfolio_defensive_rotation_action=promote_monster_early; theme_holding_profile_primary=long_duration |
| MRVL | 19.85% | 0.00% | BUY | 121,730 | 177.95 | 111 | concentrated_selection_source=monster_extreme_early; concentrated_preferred_sleeve=True; portfolio_sleeve_label=future_winner; portfolio_defensive_rotation_action=promote_monster_early; theme_holding_profile_primary=long_duration |
| MU | 14.29% | 0.00% | BUY | 87,646 | 803.63 | 17 | concentrated_selection_source=monster_extreme_early; concentrated_preferred_sleeve=True; portfolio_sleeve_label=future_winner; portfolio_defensive_rotation_action=promote_monster_early; theme_holding_profile_primary=long_duration |
| CASH | 0.00% | 13.96% | DEPLOY_CASH | 0 | 1.00 | 0 | residual cash after target stock weights |

## Current Holdings

| Ticker | Current Weight | Target Weight | Action | Trade Delta | Shares | Current Price | Entry Date | Entry Price | Return Since Entry | Entry Reason |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- | ---: | ---: | --- |
| PR | 43.56% | 0.00% | SELL | -267,128 | 13198.00 | 20.24 | 2026-03-02 | 18.63 | 8.62% | target_rebalance |
| ETR | 42.48% | 0.00% | SELL | -260,540 | 2319.00 | 112.35 | 2026-03-02 | 106.05 | 5.94% | target_rebalance |
| CASH | 13.96% | 0.00% | DEPLOY_CASH | 0 | 0.00 | 1.00 |  | 1.00 | 0.00% | uninvested_cash |
