# Concentrated Portfolio Report

This report separates latest target recommendations from the current simulated operating account.
- Recommendation date: `2026-05-13`
- Current account last replay trade date: `2026-03-02`
- Current account stale days versus recommendation date: `72`
- Pending orders needed to match recommendation: `6`

## Performance Scorecard

| Horizon | Return | CAGR | Sharpe | MaxDD | Turnover | Trades | End Cash |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1M | -1.08% | -12.36% | -0.380 | -7.61% | 0.00x | 0 | 0.00% |
| 3M | 1.45% | 6.07% | 0.402 | -7.61% | 1.98x | 6 | 0.00% |
| 6M | 48.92% | 123.36% | 2.663 | -13.72% | 5.81x | 20 | 0.00% |
| 1Y | 74.93% | 75.00% | 1.975 | -19.18% | 13.10x | 47 | 0.00% |
| 2Y | 143.60% | 56.12% | 1.704 | -23.23% | 25.96x | 102 | 0.00% |
| 3Y | 277.25% | 55.78% | 1.730 | -23.23% | 38.56x | 155 | 0.00% |
| 5Y | 276.03% | 30.33% | 1.096 | -41.82% | 71.67x | 277 | 0.00% |
| FULL | 643.08% | 33.00% | 1.094 | -41.82% | 37.58x | 402 | 0.00% |

## Files

- `recommendation_latest.csv`: latest target recommendation, formatted as what to buy/hold to target from the latest close.
- `current_operating_holdings_latest.csv`: actual simulated broker-ledger holdings marked to market, including cash.
- `performance_scorecard.csv`: broker-ledger performance by horizon.
- `*_pie.svg` and `*_bar.svg`: visual weights for recommendation/current holdings.

## Top Recommendations

| Ticker | Weight | Current Weight | Action | Trade Delta | Price | Shares per $100k | Logic |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- |
| MU | 50.00% | 0.00% | BUY | 371,542 | 803.63 | 62 | concentrated_selection_source=monster_extreme_early; concentrated_preferred_sleeve=True; portfolio_sleeve_label=future_winner; portfolio_defensive_rotation_action=promote_monster_early; theme_holding_profile_primary=long_duration |
| WDC | 25.00% | 0.00% | BUY | 185,771 | 494.09 | 50 | concentrated_selection_source=monster_extreme_early; concentrated_preferred_sleeve=True; portfolio_sleeve_label=future_winner; portfolio_defensive_rotation_action=promote_monster_early; theme_holding_profile_primary=long_duration |
| GLW | 25.00% | 0.00% | BUY | 185,771 | 206.51 | 121 | concentrated_selection_source=monster_extreme_early; concentrated_preferred_sleeve=True; portfolio_sleeve_label=future_winner; portfolio_defensive_rotation_action=promote_monster_early; theme_holding_profile_primary=neutral |
| CASH | 0.00% | 0.00% | DEPLOY_CASH | 0 | 1.00 | 0 | residual cash after target stock weights |

## Current Holdings

| Ticker | Current Weight | Target Weight | Action | Trade Delta | Shares | Current Price | Entry Date | Entry Price | Return Since Entry | Entry Reason |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- | ---: | ---: | --- |
| PR | 53.34% | 0.00% | SELL | -396,360 | 19583.00 | 20.24 | 2026-03-02 | 18.63 | 8.62% | target_rebalance |
| ETR | 26.13% | 0.00% | SELL | -194,141 | 1728.00 | 112.35 | 2026-03-02 | 106.05 | 5.94% | target_rebalance |
| THC | 20.53% | 0.00% | SELL | -152,575 | 779.00 | 195.86 | 2026-03-02 | 235.12 | -16.70% | target_rebalance |
| CASH | 0.00% | 0.00% | DEPLOY_CASH | 0 | 0.00 | 1.00 |  | 1.00 | 0.00% | uninvested_cash |
