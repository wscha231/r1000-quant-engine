# Main Portfolio Report

This report separates latest target recommendations from the current simulated operating account.
- Recommendation date: `2026-05-13`
- Current account last replay trade date: `2026-03-02`
- Current account stale days versus recommendation date: `72`
- Pending orders needed to match recommendation: `33`

## Performance Scorecard

| Horizon | Return | CAGR | Sharpe | MaxDD | Turnover | Trades | End Cash |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1M | 12.39% | 314.56% | 6.967 | -2.26% | 0.00x | 0 | 24.42% |
| 3M | 17.03% | 90.66% | 3.024 | -8.86% | 1.26x | 47 | 24.42% |
| 6M | 33.90% | 80.22% | 2.599 | -11.89% | 4.73x | 159 | 24.42% |
| 1Y | 61.08% | 61.13% | 2.339 | -11.89% | 10.03x | 347 | 24.42% |
| 2Y | 100.11% | 41.50% | 1.764 | -23.31% | 21.66x | 791 | 24.42% |
| 3Y | 169.75% | 39.28% | 1.777 | -23.31% | 32.89x | 1183 | 24.42% |
| 5Y | 168.47% | 21.84% | 1.109 | -29.98% | 57.13x | 2008 | 24.42% |
| FULL | 331.23% | 23.10% | 1.090 | -29.98% | 36.25x | 2727 | 24.42% |

## Files

- `recommendation_latest.csv`: latest target recommendation, formatted as what to buy/hold to target from the latest close.
- `current_operating_holdings_latest.csv`: actual simulated broker-ledger holdings marked to market, including cash.
- `performance_scorecard.csv`: broker-ledger performance by horizon.
- `*_pie.svg` and `*_bar.svg`: visual weights for recommendation/current holdings.

## Top Recommendations

| Ticker | Weight | Current Weight | Action | Trade Delta | Price | Shares per $100k | Logic |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- |
| GOOGL | 14.00% | 0.00% | BUY | 60,372 | 402.62 | 34 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| GEV | 14.00% | 0.00% | BUY | 60,372 | 1062.57 | 13 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| MRVL | 5.68% | 0.00% | BUY | 24,491 | 177.95 | 31 | portfolio_sleeve_label=future_winner; dominant_archetype_label=emerging_growth |
| ARM | 5.68% | 0.00% | BUY | 24,491 | 221.21 | 25 | portfolio_sleeve_label=future_winner; dominant_archetype_label=emerging_growth |
| VRT | 5.68% | 4.89% | BUY | 3,402 | 369.99 | 15 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| FIX | 5.68% | 0.00% | BUY | 24,491 | 2034.63 | 2 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| RKLB | 5.45% | 0.00% | BUY | 23,492 | 124.15 | 43 | portfolio_sleeve_label=future_winner; dominant_archetype_label=emerging_growth |
| UMC | 5.31% | 0.00% | BUY | 22,887 | 15.92 | 333 | portfolio_sleeve_label=future_winner; dominant_archetype_label=emerging_growth |
| FTI | 5.28% | 0.00% | BUY | 22,773 | 72.68 | 72 | portfolio_sleeve_label=future_winner; dominant_archetype_label=emerging_growth |
| CBOE | 5.25% | 0.00% | BUY | 22,624 | 366.70 | 14 | portfolio_sleeve_label=future_winner; dominant_archetype_label=emerging_growth |
| ON | 4.00% | 0.00% | BUY | 17,249 | 115.71 | 34 | portfolio_sleeve_label=early_scout; dominant_archetype_label=emerging_growth |
| NXPI | 4.00% | 0.00% | BUY | 17,249 | 298.41 | 13 | portfolio_sleeve_label=future_winner; dominant_archetype_label=emerging_growth |

## Current Holdings

| Ticker | Current Weight | Target Weight | Action | Trade Delta | Shares | Current Price | Entry Date | Entry Price | Return Since Entry | Entry Reason |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- | ---: | ---: | --- |
| MU | 10.44% | 0.00% | SELL | -45,003 | 56.00 | 803.63 | 2025-12-01 | 240.26 | 234.48% | target_rebalance |
| AMAT | 6.28% | 0.00% | SELL | -27,070 | 62.00 | 436.61 | 2026-02-02 | 351.51 | 24.21% | target_rebalance |
| LRCX | 5.62% | 0.00% | SELL | -24,226 | 82.00 | 295.44 | 2025-11-03 | 160.78 | 83.75% | target_rebalance |
| BE | 5.31% | 0.00% | SELL | -22,891 | 79.00 | 289.76 | 2026-02-02 | 156.13 | 85.59% | target_rebalance |
| WDC | 5.27% | 0.00% | SELL | -22,728 | 46.00 | 494.09 | 2025-12-01 | 228.23 | 116.49% | target_rebalance |
| VRT | 4.89% | 5.68% | BUY | 3,402 | 57.00 | 369.99 | 2026-03-02 | 257.69 | 43.58% | target_rebalance |
| GOOG | 4.81% | 0.00% | SELL | -20,750 | 52.00 | 399.04 | 2026-01-02 | 311.83 | 27.97% | target_rebalance |
| PR | 4.74% | 4.00% | SELL | -3,193 | 1010.00 | 20.24 | 2026-03-02 | 18.63 | 8.62% | target_rebalance |
| ETR | 4.38% | 0.00% | SELL | -18,875 | 168.00 | 112.35 | 2026-03-02 | 106.05 | 5.94% | target_rebalance |
| SCCO | 3.29% | 0.00% | SELL | -14,200 | 74.00 | 191.89 | 2026-03-02 | 215.54 | -10.97% | target_rebalance |
| KO | 3.16% | 0.00% | SELL | -13,644 | 170.00 | 80.26 | 2026-03-02 | 79.67 | 0.74% | target_rebalance |
| RGLD | 2.84% | 0.00% | SELL | -12,250 | 50.00 | 244.99 | 2026-03-02 | 303.74 | -19.34% | target_rebalance |
| APH | 2.80% | 0.00% | SELL | -12,090 | 97.00 | 124.64 | 2025-09-02 | 134.62 | -7.42% | target_rebalance |
| VZ | 2.75% | 0.00% | SELL | -11,850 | 251.00 | 47.21 | 2026-03-02 | 49.24 | -4.12% | target_rebalance |
| ATI | 2.45% | 0.00% | SELL | -10,549 | 64.00 | 164.83 | 2026-03-02 | 166.42 | -0.96% | target_rebalance |
| BKNG | 2.30% | 0.00% | SELL | -9,922 | 64.00 | 155.03 | 2026-03-02 | 166.81 | -7.06% | target_rebalance |
| ADI | 2.21% | 0.00% | SELL | -9,513 | 22.00 | 432.39 | 2026-03-02 | 351.31 | 23.08% | target_rebalance |
| THC | 2.04% | 0.00% | SELL | -8,814 | 45.00 | 195.86 | 2026-03-02 | 235.12 | -16.70% | target_rebalance |
| CASH | 24.42% | 0.00% | DEPLOY_CASH | 0 | 0.00 | 1.00 |  | 1.00 | 0.00% | uninvested_cash |
