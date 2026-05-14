# Main Portfolio Report

This report separates latest target recommendations from the current simulated operating account.
- Recommendation date: `2026-05-13`
- Current account last replay trade date: `2026-05-13`
- Current account stale days versus recommendation date: `0`
- Pending orders needed to match recommendation: `0`

## Performance Scorecard

| Horizon | Return | CAGR | Sharpe | MaxDD | Turnover | Trades | End Cash |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1M | 12.40% | 314.94% | 7.073 | -2.10% | 1.54x | 40 | 0.77% |
| 3M | 16.04% | 84.15% | 2.853 | -9.96% | 2.98x | 73 | 0.77% |
| 6M | 38.19% | 92.07% | 2.882 | -11.01% | 6.28x | 189 | 0.77% |
| 1Y | 55.47% | 55.51% | 2.176 | -11.14% | 11.94x | 388 | 0.77% |
| 2Y | 82.11% | 34.98% | 1.569 | -21.22% | 23.52x | 859 | 0.77% |
| 3Y | 156.10% | 36.88% | 1.712 | -21.22% | 34.71x | 1276 | 0.77% |
| 5Y | 138.90% | 19.03% | 1.047 | -32.13% | 56.41x | 2091 | 0.77% |
| FULL | 257.44% | 19.85% | 0.916 | -32.13% | 37.95x | 2836 | 0.77% |

## Files

- `recommendation_latest.csv`: latest target recommendation, formatted as what to buy/hold to target from the latest close.
- `current_operating_holdings_latest.csv`: actual simulated broker-ledger holdings marked to market, including cash.
- `performance_scorecard.csv`: broker-ledger performance by horizon.
- `*_pie.svg` and `*_bar.svg`: visual weights for recommendation/current holdings.

## Top Recommendations

| Ticker | Weight | Current Weight | Action | Trade Delta | Price | Shares per $100k | Logic |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- |
| GOOG | 12.00% | 0.00% | BUY | 0 | 399.04 | 30 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| GEV | 12.00% | 0.00% | BUY | 0 | 1062.57 | 11 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| MRVL | 6.21% | 0.00% | BUY | 0 | 177.95 | 34 | portfolio_sleeve_label=future_winner; dominant_archetype_label=emerging_growth |
| LRCX | 6.21% | 0.00% | BUY | 0 | 295.44 | 21 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| VRT | 6.21% | 0.00% | BUY | 0 | 369.99 | 16 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| WDC | 5.85% | 0.00% | BUY | 0 | 494.09 | 11 | portfolio_sleeve_label=future_winner; dominant_archetype_label=emerging_growth |
| FIX | 5.63% | 0.00% | BUY | 0 | 2034.63 | 2 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| FTI | 5.50% | 0.00% | BUY | 0 | 72.68 | 75 | portfolio_sleeve_label=future_winner; dominant_archetype_label=emerging_growth |
| NXPI | 5.48% | 0.00% | BUY | 0 | 298.41 | 18 | portfolio_sleeve_label=future_winner; dominant_archetype_label=emerging_growth |
| UMC | 5.47% | 0.00% | BUY | 0 | 15.92 | 343 | portfolio_sleeve_label=future_winner; dominant_archetype_label=emerging_growth |
| CBOE | 5.45% | 0.00% | BUY | 0 | 366.70 | 14 | portfolio_sleeve_label=future_winner; dominant_archetype_label=emerging_growth |
| ON | 4.00% | 0.00% | BUY | 0 | 115.71 | 34 | portfolio_sleeve_label=early_scout; dominant_archetype_label=emerging_growth |

## Current Holdings

| Ticker | Current Weight | Target Weight | Action | Trade Delta | Shares | Current Price | Entry Date | Entry Price | Return Since Entry | Entry Reason |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- | ---: | ---: | --- |
| GOOG | 11.95% | 0.00% | HOLD | 0 | 107.00 | 399.04 | 2026-05-13 | 399.04 | 0.00% | target_rebalance |
| GEV | 11.89% | 0.00% | HOLD | 0 | 40.00 | 1062.57 | 2026-05-13 | 1062.57 | 0.00% | target_rebalance |
| LRCX | 6.28% | 0.00% | HOLD | 0 | 76.00 | 295.44 | 2025-11-03 | 179.26 | 64.81% | target_rebalance |
| VRT | 6.21% | 0.00% | HOLD | 0 | 60.00 | 369.99 | 2026-03-02 | 295.12 | 25.37% | target_rebalance |
| MRVL | 6.17% | 0.00% | HOLD | 0 | 124.00 | 177.95 | 2026-05-13 | 177.95 | 0.00% | target_rebalance |
| WDC | 5.81% | 0.00% | HOLD | 0 | 42.00 | 494.09 | 2026-05-13 | 494.09 | 0.00% | target_rebalance |
| FTI | 5.49% | 0.00% | HOLD | 0 | 270.00 | 72.68 | 2026-03-02 | 69.95 | 3.91% | target_rebalance |
| UMC | 5.48% | 0.00% | HOLD | 0 | 1231.00 | 15.92 | 2026-05-13 | 15.92 | 0.00% | target_rebalance |
| CBOE | 5.44% | 0.00% | HOLD | 0 | 53.00 | 366.70 | 2026-05-13 | 366.70 | 0.00% | target_rebalance |
| NXPI | 5.43% | 0.00% | HOLD | 0 | 65.00 | 298.41 | 2026-05-13 | 298.41 | 0.00% | target_rebalance |
| FIX | 5.12% | 0.00% | HOLD | 0 | 9.00 | 2034.63 | 2026-05-13 | 2034.63 | 0.00% | target_rebalance |
| STM | 4.01% | 0.00% | HOLD | 0 | 226.00 | 63.39 | 2026-05-13 | 63.39 | 0.00% | target_rebalance |
| PR | 4.00% | 0.00% | HOLD | 0 | 707.00 | 20.24 | 2026-03-02 | 19.14 | 5.75% | target_rebalance |
| HPE | 4.00% | 0.00% | HOLD | 0 | 446.00 | 32.07 | 2026-05-13 | 32.07 | 0.00% | target_rebalance |
| TKR | 3.98% | 0.00% | HOLD | 0 | 123.00 | 115.74 | 2026-05-13 | 115.74 | 0.00% | target_rebalance |
| MLI | 3.98% | 0.00% | HOLD | 0 | 102.00 | 139.55 | 2026-05-13 | 139.55 | 0.00% | target_rebalance |
| ON | 3.98% | 0.00% | HOLD | 0 | 123.00 | 115.71 | 2026-05-13 | 115.71 | 0.00% | target_rebalance |
| CASH | 0.77% | 0.00% | HOLD_CASH | 0 | 0.00 | 1.00 |  | 1.00 | 0.00% | uninvested_cash |
