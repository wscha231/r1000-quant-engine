# Concentrated Portfolio Report

This report separates latest target recommendations from the current simulated operating account.
- Recommendation date: `2026-05-13`
- Current account last replay trade date: `2026-03-02`
- Current account stale days versus recommendation date: `72`
- Pending orders needed to match recommendation: `5`

## Performance Scorecard

| Horizon | Return | CAGR | Sharpe | MaxDD | Turnover | Trades | End Cash |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1M | -1.55% | -17.36% | -0.652 | -7.48% | 0.00x | 0 | 13.96% |
| 3M | 4.88% | 21.58% | 1.124 | -7.48% | 1.63x | 4 | 13.96% |
| 6M | 60.45% | 159.65% | 3.131 | -10.66% | 4.38x | 12 | 13.96% |
| 1Y | 93.01% | 93.10% | 2.345 | -15.74% | 13.18x | 35 | 13.96% |
| 2Y | 102.31% | 42.27% | 1.493 | -20.87% | 25.22x | 73 | 13.96% |
| 3Y | 251.24% | 52.11% | 1.507 | -23.42% | 40.09x | 114 | 13.96% |
| 5Y | 307.35% | 32.44% | 1.149 | -28.85% | 67.25x | 197 | 13.96% |
| FULL | 629.43% | 32.65% | 1.071 | -28.85% | 35.60x | 280 | 13.96% |

## Files

- `recommendation_latest.csv`: latest target recommendation, formatted as what to buy/hold to target from the latest close.
- `current_operating_holdings_latest.csv`: actual simulated broker-ledger holdings marked to market, including cash.
- `performance_scorecard.csv`: broker-ledger performance by horizon.
- `*_pie.svg` and `*_bar.svg`: visual weights for recommendation/current holdings.

## Top Recommendations

| Ticker | Weight | Current Weight | Action | Trade Delta | Price | Shares per $100k | Logic |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- |
| MRVL | 50.00% | 0.00% | BUY | 364,715 | 177.95 | 280 | concentrated_selection_source=monster_extreme_early; concentrated_preferred_sleeve=True; portfolio_sleeve_label=future_winner; portfolio_defensive_rotation_action=promote_monster_early; theme_holding_profile_primary=long_duration |
| MU | 25.00% | 0.00% | BUY | 182,358 | 803.63 | 31 | concentrated_selection_source=monster_extreme_early; concentrated_preferred_sleeve=True; portfolio_sleeve_label=future_winner; portfolio_defensive_rotation_action=promote_monster_early; theme_holding_profile_primary=long_duration |
| CIEN | 25.00% | 0.00% | BUY | 182,358 | 577.90 | 43 | concentrated_selection_source=monster_extreme_early; concentrated_preferred_sleeve=True; portfolio_sleeve_label=future_winner; portfolio_defensive_rotation_action=promote_monster_early; theme_holding_profile_primary=long_duration |
| CASH | 0.00% | 13.96% | DEPLOY_CASH | 0 | 1.00 | 0 | residual cash after target stock weights |

## Current Holdings

| Ticker | Current Weight | Target Weight | Action | Trade Delta | Shares | Current Price | Entry Date | Entry Price | Return Since Entry | Entry Reason |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- | ---: | ---: | --- |
| PR | 43.56% | 0.00% | SELL | -317,728 | 15698.00 | 20.24 | 2026-03-02 | 18.63 | 8.62% | target_rebalance |
| ETR | 42.48% | 0.00% | SELL | -309,861 | 2758.00 | 112.35 | 2026-03-02 | 106.05 | 5.94% | target_rebalance |
| CASH | 13.96% | 0.00% | DEPLOY_CASH | 0 | 0.00 | 1.00 |  | 1.00 | 0.00% | uninvested_cash |
