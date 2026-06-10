# Main Portfolio Report

This report separates latest target recommendations from the current simulated operating account.
- Recommendation date: `2026-05-12`
- Current account last replay trade date: `2026-03-02`
- Current account stale days versus recommendation date: `71`
- Pending orders needed to match recommendation: `45`

## Performance Scorecard

| Horizon | Return | CAGR | Sharpe | MaxDD | Turnover | Trades | End Cash |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1M | 6.09% | 110.45% | 4.891 | -1.81% | 0.00x | 0 | 26.03% |
| 3M | 9.88% | 47.19% | 2.316 | -7.28% | 1.32x | 43 | 26.03% |
| 6M | 22.24% | 49.98% | 1.993 | -9.11% | 4.68x | 157 | 26.03% |
| 1Y | 38.69% | 38.72% | 1.831 | -11.23% | 10.30x | 328 | 26.03% |
| 2Y | 63.35% | 27.87% | 1.364 | -21.71% | 22.18x | 773 | 26.03% |
| 3Y | 127.01% | 31.42% | 1.564 | -21.71% | 33.61x | 1172 | 26.03% |
| 5Y | 125.45% | 17.66% | 0.947 | -33.45% | 57.46x | 1997 | 26.03% |
| FULL | 267.75% | 20.35% | 0.991 | -33.45% | 41.75x | 2737 | 26.03% |

## Files

- `recommendation_latest.csv`: latest target recommendation, formatted as what to buy/hold to target from the latest close.
- `current_operating_holdings_latest.csv`: actual simulated broker-ledger holdings marked to market, including cash.
- `performance_scorecard.csv`: broker-ledger performance by horizon.
- `*_pie.svg` and `*_bar.svg`: visual weights for recommendation/current holdings.

## Top Recommendations

| Ticker | Weight | Current Weight | Action | Trade Delta | Price | Shares per $100k | Logic |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- |
| GOOG | 17.89% | 3.75% | BUY | 52,009 | 382.95 | 46 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| PLTR | 6.10% | 0.00% | BUY | 22,420 | 134.10 | 45 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| LRCX | 6.10% | 5.64% | BUY | 1,663 | 288.29 | 21 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| VRT | 6.10% | 4.30% | BUY | 6,609 | 367.70 | 16 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| GLW | 5.95% | 0.00% | BUY | 21,889 | 196.16 | 30 | portfolio_sleeve_label=future_winner; dominant_archetype_label=emerging_growth |
| FTI | 5.69% | 2.99% | BUY | 9,937 | 73.25 | 77 | portfolio_sleeve_label=future_winner; dominant_archetype_label=emerging_growth |
| FIX | 5.66% | 0.00% | BUY | 20,832 | 2014.47 | 2 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| PWR | 5.66% | 0.00% | BUY | 20,801 | 765.88 | 7 | portfolio_sleeve_label=future_winner; dominant_archetype_label=emerging_growth |
| UMC | 5.63% | 0.00% | BUY | 20,701 | 15.98 | 352 | portfolio_sleeve_label=future_winner; dominant_archetype_label=emerging_growth |
| OKE | 5.62% | 0.00% | BUY | 20,651 | 88.64 | 63 | portfolio_sleeve_label=future_winner; dominant_archetype_label=emerging_growth |
| SU | 5.61% | 0.00% | BUY | 20,634 | 66.50 | 84 | portfolio_sleeve_label=future_winner; dominant_archetype_label=emerging_growth |
| ON | 4.00% | 0.00% | BUY | 14,710 | 103.33 | 38 | portfolio_sleeve_label=early_scout; dominant_archetype_label=emerging_growth |

## Current Holdings

| Ticker | Current Weight | Target Weight | Action | Trade Delta | Shares | Current Price | Entry Date | Entry Price | Return Since Entry | Entry Reason |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- | ---: | ---: | --- |
| MU | 8.78% | 0.00% | SELL | -32,303 | 43.00 | 751.24 | 2025-12-01 | 247.24 | 203.85% | target_rebalance |
| AMAT | 8.62% | 0.00% | SELL | -31,691 | 74.00 | 428.26 | 2026-02-02 | 353.07 | 21.30% | target_rebalance |
| LRCX | 5.64% | 6.10% | BUY | 1,663 | 72.00 | 288.29 | 2025-11-03 | 156.58 | 84.11% | target_rebalance |
| APH | 4.68% | 0.00% | SELL | -17,221 | 135.00 | 127.56 | 2025-10-01 | 134.81 | -5.38% | target_rebalance |
| ETR | 4.61% | 0.00% | SELL | -16,943 | 150.00 | 112.96 | 2026-03-02 | 106.05 | 6.51% | target_rebalance |
| VRT | 4.30% | 6.10% | BUY | 6,609 | 43.00 | 367.70 | 2026-03-02 | 257.69 | 42.69% | target_rebalance |
| VZ | 3.75% | 0.00% | SELL | -13,798 | 287.00 | 48.08 | 2026-03-02 | 49.24 | -2.36% | target_rebalance |
| GOOG | 3.75% | 17.89% | BUY | 52,009 | 36.00 | 382.95 | 2026-01-02 | 312.11 | 22.70% | target_rebalance |
| KO | 3.25% | 0.00% | SELL | -11,945 | 149.00 | 80.17 | 2026-03-02 | 79.67 | 0.62% | target_rebalance |
| ADI | 3.07% | 0.00% | SELL | -11,275 | 27.00 | 417.58 | 2026-03-02 | 351.31 | 18.86% | target_rebalance |
| FTI | 2.99% | 5.69% | BUY | 9,937 | 150.00 | 73.25 | 2026-03-02 | 67.45 | 8.60% | target_rebalance |
| SCCO | 2.79% | 0.00% | SELL | -10,268 | 54.00 | 190.14 | 2026-03-02 | 218.85 | -13.12% | target_rebalance |
| COST | 2.78% | 0.00% | SELL | -10,213 | 10.00 | 1021.31 | 2026-03-02 | 1001.32 | 2.00% | target_rebalance |
| PR | 2.69% | 4.00% | BUY | 4,834 | 490.00 | 20.16 | 2026-03-02 | 18.63 | 8.16% | target_rebalance |
| GTLS | 2.48% | 0.00% | SELL | -9,124 | 44.00 | 207.38 | 2026-03-02 | 207.06 | 0.15% | target_rebalance |
| BKNG | 2.36% | 0.00% | SELL | -8,666 | 54.00 | 160.48 | 2025-09-02 | 167.78 | -4.35% | target_rebalance |
| RGLD | 2.34% | 0.00% | SELL | -8,617 | 35.00 | 246.21 | 2026-03-02 | 303.74 | -18.94% | target_rebalance |
| PEG | 1.99% | 0.00% | SELL | -7,333 | 93.00 | 78.85 | 2026-03-02 | 83.83 | -5.94% | target_rebalance |
| TPR | 0.54% | 0.00% | SELL | -1,980 | 15.00 | 131.98 | 2026-02-02 | 129.32 | 2.05% | target_rebalance |
| AEM | 0.32% | 0.00% | SELL | -1,182 | 6.00 | 197.06 | 2026-02-02 | 190.48 | 3.46% | target_rebalance |
