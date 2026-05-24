# Concentrated Portfolio Report

This report separates latest target recommendations from the current simulated operating account.
- Recommendation date: `2026-05-22`
- Current account last replay trade date: `2026-03-02`
- Current account stale days versus recommendation date: `81`
- Pending orders needed to match recommendation: `5`

## Performance Scorecard

| Horizon | Return | CAGR | Sharpe | MaxDD | Turnover | Trades | End Cash |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1M | 9.85% | 213.98% | 2.836 | -6.07% | 0.00x | 0 | 0.00% |
| 3M | 37.75% | 277.84% | 3.271 | -9.87% | 1.70x | 4 | 0.00% |
| 6M | 111.93% | 363.04% | 3.575 | -9.87% | 6.11x | 15 | 0.00% |
| 1Y | 127.50% | 127.63% | 2.178 | -19.99% | 13.09x | 34 | 0.00% |
| 2Y | 186.97% | 69.46% | 1.639 | -29.30% | 28.42x | 74 | 0.00% |
| 3Y | 365.09% | 66.90% | 1.729 | -29.30% | 43.33x | 113 | 0.00% |
| 5Y | 372.67% | 36.48% | 1.155 | -42.58% | 75.51x | 194 | 0.00% |
| FULL | 779.17% | 36.61% | 1.100 | -42.58% | 30.34x | 276 | 0.00% |

## Files

- `recommendation_latest.csv`: latest target recommendation, formatted as what to buy/hold to target from the latest close.
- `current_operating_holdings_latest.csv`: actual simulated broker-ledger holdings marked to market, including cash.
- `performance_scorecard.csv`: broker-ledger performance by horizon.
- `*_pie.svg` and `*_bar.svg`: visual weights for recommendation/current holdings.

## Top Recommendations

| Ticker | Weight | Current Weight | Action | Trade Delta | Price | Shares per $100k | Logic |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- |
| MRVL | 42.42% | 0.00% | BUY | 372,899 | 196.33 | 216 | concentrated_selection_source=monster_extreme_early; concentrated_preferred_sleeve=True; portfolio_sleeve_label=future_winner; portfolio_defensive_rotation_action=promote_monster_early; theme_holding_profile_primary=long_duration |
| ARM | 42.18% | 0.00% | BUY | 370,817 | 306.51 | 137 | concentrated_selection_source=monster_extreme_early; concentrated_preferred_sleeve=True; portfolio_sleeve_label=future_winner; portfolio_defensive_rotation_action=promote_monster_early; theme_holding_profile_primary=long_duration |
| MTSI | 15.41% | 0.00% | BUY | 135,451 | 385.98 | 39 | concentrated_selection_source=monster_extreme_early; concentrated_preferred_sleeve=True; portfolio_sleeve_label=future_winner; portfolio_defensive_rotation_action=promote_monster_early; theme_holding_profile_primary=neutral |
| CASH | 0.00% | 0.00% | DEPLOY_CASH | 0 | 1.00 | 0 | residual cash after target stock weights |

## Current Holdings

| Ticker | Current Weight | Target Weight | Action | Trade Delta | Shares | Current Price | Entry Date | Entry Price | Return Since Entry | Entry Reason |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- | ---: | ---: | --- |
| CIEN | 60.16% | 0.00% | SELL | -528,868 | 906.00 | 583.74 | 2026-03-02 | 353.73 | 65.02% | target_rebalance |
| PR | 39.84% | 0.00% | SELL | -350,280 | 17137.00 | 20.44 | 2026-03-02 | 18.63 | 9.69% | target_rebalance |
| CASH | 0.00% | 0.00% | DEPLOY_CASH | 0 | 0.00 | 1.00 |  | 1.00 | 0.00% | uninvested_cash |
