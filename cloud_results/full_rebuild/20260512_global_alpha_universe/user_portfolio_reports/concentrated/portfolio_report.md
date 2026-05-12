# Concentrated Portfolio Report

This report separates latest target recommendations from the current simulated operating account.
- Recommendation date: `2026-05-08`
- Current account last replay trade date: `2026-03-02`
- Current account stale days versus recommendation date: `67`
- Pending orders needed to match recommendation: `8`

## Performance Scorecard

| Horizon | Return | CAGR | Sharpe | MaxDD | Turnover | Trades | End Cash |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1M | -4.76% | -44.76% | -3.324 | -6.31% | 0.00x | 0 | 0.00% |
| 3M | 4.56% | 20.35% | 1.294 | -6.31% | 1.94x | 8 | 0.00% |
| 6M | 41.64% | 103.46% | 2.517 | -14.11% | 5.79x | 28 | 0.00% |
| 1Y | 85.75% | 85.83% | 2.597 | -14.11% | 13.06x | 67 | 0.00% |
| 2Y | 117.75% | 47.60% | 1.805 | -19.90% | 25.05x | 139 | 0.00% |
| 3Y | 233.19% | 49.35% | 1.672 | -19.90% | 38.25x | 215 | 0.00% |
| 5Y | 255.43% | 28.91% | 1.116 | -35.93% | 66.49x | 368 | 0.00% |
| FULL | 755.01% | 35.76% | 1.204 | -36.74% | 35.65x | 532 | 0.00% |

## Files

- `recommendation_latest.csv`: latest target recommendation, formatted as what to buy/hold to target from the latest close.
- `current_operating_holdings_latest.csv`: actual simulated broker-ledger holdings marked to market, including cash.
- `performance_scorecard.csv`: broker-ledger performance by horizon.
- `*_pie.svg` and `*_bar.svg`: visual weights for recommendation/current holdings.

## Top Recommendations

| Ticker | Weight | Current Weight | Action | Trade Delta | Price | Shares per $100k | Logic |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- |
| ON | 33.51% | 0.00% | BUY | 286,516 | 103.20 | 324 | concentrated_selection_source=preferred_final_label; concentrated_preferred_sleeve=True; portfolio_sleeve_label=early_scout; portfolio_defensive_rotation_action=promote_monster_early; theme_holding_profile_primary=neutral |
| WDC | 26.57% | 0.00% | BUY | 227,184 | 480.00 | 55 | concentrated_selection_source=monster_extreme_early; concentrated_preferred_sleeve=True; portfolio_sleeve_label=future_winner; portfolio_defensive_rotation_action=promote_monster_early; theme_holding_profile_primary=long_duration |
| MU | 22.93% | 0.00% | BUY | 196,027 | 746.81 | 30 | concentrated_selection_source=monster_extreme_early; concentrated_preferred_sleeve=True; portfolio_sleeve_label=future_winner; portfolio_defensive_rotation_action=promote_monster_early; theme_holding_profile_primary=long_duration |
| SNDK | 16.99% | 0.00% | BUY | 145,285 | 1562.34 | 10 | concentrated_selection_source=monster_extreme_early; concentrated_preferred_sleeve=True; portfolio_sleeve_label=future_winner; portfolio_defensive_rotation_action=promote_monster_early; theme_holding_profile_primary=long_duration |
| CASH | 0.00% | 0.00% | DEPLOY_CASH | 0 | 1.00 | 0 | residual cash after target stock weights |

## Current Holdings

| Ticker | Current Weight | Target Weight | Action | Trade Delta | Shares | Current Price | Entry Date | Entry Price | Return Since Entry | Entry Reason |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- | ---: | ---: | --- |
| ETR | 32.62% | 0.00% | SELL | -278,863 | 2499.00 | 111.59 | 2026-03-02 | 106.05 | 5.22% | target_rebalance |
| PR | 31.57% | 0.00% | SELL | -269,927 | 13688.00 | 19.72 | 2026-03-02 | 18.63 | 5.83% | target_rebalance |
| BKNG | 19.58% | 0.00% | SELL | -167,423 | 1009.00 | 165.93 | 2026-03-02 | 166.81 | -0.53% | target_rebalance |
| PEG | 16.23% | 0.00% | SELL | -138,757 | 1799.00 | 77.13 | 2026-03-02 | 83.83 | -7.99% | target_rebalance |
| CASH | 0.00% | 0.00% | DEPLOY_CASH | 0 | 0.00 | 1.00 |  | 1.00 | 0.00% | uninvested_cash |
