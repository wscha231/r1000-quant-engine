# Concentrated Portfolio Report

This report separates latest target recommendations from the current simulated operating account.
- Recommendation date: `2026-05-12`
- Current account last replay trade date: `2026-03-02`
- Current account stale days versus recommendation date: `71`
- Pending orders needed to match recommendation: `8`

## Performance Scorecard

| Horizon | Return | CAGR | Sharpe | MaxDD | Turnover | Trades | End Cash |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1M | -3.40% | -35.32% | -2.274 | -6.53% | 0.00x | 0 | 0.00% |
| 3M | 6.11% | 27.57% | 1.579 | -6.53% | 1.94x | 8 | 0.00% |
| 6M | 37.19% | 89.29% | 2.545 | -11.97% | 5.75x | 28 | 0.00% |
| 1Y | 64.48% | 64.54% | 2.281 | -14.06% | 13.00x | 67 | 0.00% |
| 2Y | 110.96% | 45.36% | 1.791 | -18.46% | 24.89x | 139 | 0.00% |
| 3Y | 226.80% | 48.38% | 1.679 | -18.46% | 37.71x | 214 | 0.00% |
| 5Y | 314.54% | 32.90% | 1.273 | -28.15% | 65.27x | 364 | 0.00% |
| FULL | 831.18% | 37.35% | 1.278 | -37.89% | 35.17x | 525 | 0.00% |

## Files

- `recommendation_latest.csv`: latest target recommendation, formatted as what to buy/hold to target from the latest close.
- `current_operating_holdings_latest.csv`: actual simulated broker-ledger holdings marked to market, including cash.
- `performance_scorecard.csv`: broker-ledger performance by horizon.
- `*_pie.svg` and `*_bar.svg`: visual weights for recommendation/current holdings.

## Top Recommendations

| Ticker | Weight | Current Weight | Action | Trade Delta | Price | Shares per $100k | Logic |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- |
| VRT | 30.79% | 0.00% | BUY | 286,730 | 367.13 | 83 | concentrated_selection_source=preferred_final_label; concentrated_preferred_sleeve=True; portfolio_sleeve_label=future_winner; portfolio_defensive_rotation_action=promote_monster_early; theme_holding_profile_primary=long_duration |
| GLW | 26.88% | 0.00% | BUY | 250,323 | 198.24 | 135 | concentrated_selection_source=monster_extreme_early; concentrated_preferred_sleeve=True; portfolio_sleeve_label=future_winner; portfolio_defensive_rotation_action=promote_monster_early; theme_holding_profile_primary=neutral |
| WDC | 23.23% | 0.00% | BUY | 216,286 | 488.74 | 47 | concentrated_selection_source=monster_extreme_early; concentrated_preferred_sleeve=True; portfolio_sleeve_label=future_winner; portfolio_defensive_rotation_action=promote_monster_early; theme_holding_profile_primary=long_duration |
| MU | 19.10% | 0.00% | BUY | 177,837 | 766.58 | 24 | concentrated_selection_source=monster_extreme_early; concentrated_preferred_sleeve=True; portfolio_sleeve_label=future_winner; portfolio_defensive_rotation_action=promote_monster_early; theme_holding_profile_primary=long_duration |
| CASH | 0.00% | 0.00% | DEPLOY_CASH | 0 | 1.00 | 0 | residual cash after target stock weights |

## Current Holdings

| Ticker | Current Weight | Target Weight | Action | Trade Delta | Shares | Current Price | Entry Date | Entry Price | Return Since Entry | Entry Reason |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- | ---: | ---: | --- |
| PR | 34.20% | 0.00% | SELL | -318,424 | 15787.00 | 20.17 | 2026-03-02 | 18.63 | 8.24% | target_rebalance |
| ETR | 32.54% | 0.00% | SELL | -302,991 | 2683.00 | 112.93 | 2026-03-02 | 106.05 | 6.49% | target_rebalance |
| BKNG | 17.48% | 0.00% | SELL | -162,808 | 1014.00 | 160.56 | 2026-03-02 | 166.81 | -3.75% | target_rebalance |
| PEG | 15.78% | 0.00% | SELL | -146,941 | 1869.00 | 78.62 | 2026-03-02 | 83.83 | -6.21% | target_rebalance |
| CASH | 0.00% | 0.00% | DEPLOY_CASH | 0 | 0.00 | 1.00 |  | 1.00 | 0.00% | uninvested_cash |
