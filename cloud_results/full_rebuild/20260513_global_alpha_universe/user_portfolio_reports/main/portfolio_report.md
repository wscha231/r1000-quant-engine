# Main Portfolio Report

This report separates latest target recommendations from the current simulated operating account.
- Recommendation date: `2026-05-12`
- Current account last replay trade date: `2026-03-02`
- Current account stale days versus recommendation date: `71`
- Pending orders needed to match recommendation: `24`

## Performance Scorecard

| Horizon | Return | CAGR | Sharpe | MaxDD | Turnover | Trades | End Cash |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1M | 8.57% | 181.76% | 5.392 | -1.97% | 0.00x | 0 | 25.04% |
| 3M | 12.27% | 60.81% | 2.285 | -9.28% | 1.19x | 36 | 25.04% |
| 6M | 23.17% | 52.28% | 1.980 | -11.20% | 4.61x | 117 | 25.04% |
| 1Y | 48.37% | 48.41% | 2.082 | -11.20% | 9.80x | 250 | 25.04% |
| 2Y | 84.57% | 35.94% | 1.626 | -21.43% | 21.64x | 607 | 25.04% |
| 3Y | 154.19% | 36.46% | 1.709 | -21.43% | 32.67x | 886 | 25.04% |
| 5Y | 144.63% | 19.59% | 1.015 | -33.19% | 57.01x | 1519 | 25.04% |
| FULL | 290.57% | 21.38% | 1.026 | -33.19% | 38.58x | 2091 | 25.04% |

## Files

- `recommendation_latest.csv`: latest target recommendation, formatted as what to buy/hold to target from the latest close.
- `current_operating_holdings_latest.csv`: actual simulated broker-ledger holdings marked to market, including cash.
- `performance_scorecard.csv`: broker-ledger performance by horizon.
- `*_pie.svg` and `*_bar.svg`: visual weights for recommendation/current holdings.

## Top Recommendations

| Ticker | Weight | Current Weight | Action | Trade Delta | Price | Shares per $100k | Logic |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- |
| GOOG | 17.53% | 0.00% | BUY | 68,458 | 383.82 | 45 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| GEV | 13.17% | 0.00% | BUY | 51,431 | 1071.98 | 12 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| AMZN | 11.95% | 0.00% | BUY | 46,655 | 265.82 | 44 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| PLTR | 8.31% | 0.00% | BUY | 32,462 | 136.00 | 61 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| VRT | 8.31% | 6.11% | BUY | 8,598 | 367.13 | 22 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| GLW | 7.11% | 0.00% | BUY | 27,765 | 198.24 | 35 | portfolio_sleeve_label=future_winner; dominant_archetype_label=emerging_growth |
| LRCX | 6.57% | 8.00% | SELL | -5,579 | 289.24 | 22 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| RKLB | 5.92% | 0.00% | BUY | 23,120 | 117.56 | 50 | portfolio_sleeve_label=future_winner; dominant_archetype_label=emerging_growth |
| FTI | 5.14% | 4.68% | BUY | 1,772 | 73.19 | 70 | portfolio_sleeve_label=future_winner; dominant_archetype_label=emerging_growth |
| ON | 4.00% | 0.00% | BUY | 15,623 | 104.11 | 38 | portfolio_sleeve_label=early_scout; dominant_archetype_label=emerging_growth |
| NXPI | 4.00% | 0.00% | BUY | 15,623 | 294.23 | 13 | portfolio_sleeve_label=future_winner; dominant_archetype_label=emerging_growth |
| AKAM | 4.00% | 0.00% | BUY | 15,623 | 149.56 | 26 | portfolio_sleeve_label=early_scout; dominant_archetype_label=emerging_growth |

## Current Holdings

| Ticker | Current Weight | Target Weight | Action | Trade Delta | Shares | Current Price | Entry Date | Entry Price | Return Since Entry | Entry Reason |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- | ---: | ---: | --- |
| MU | 12.17% | 0.00% | SELL | -47,528 | 62.00 | 766.58 | 2025-12-01 | 240.26 | 219.06% | target_rebalance |
| AMAT | 8.17% | 0.00% | SELL | -31,909 | 74.00 | 431.20 | 2026-02-02 | 344.71 | 25.09% | target_rebalance |
| LRCX | 8.00% | 6.57% | SELL | -5,579 | 108.00 | 289.24 | 2025-11-03 | 183.59 | 57.54% | target_rebalance |
| GOOGL | 7.93% | 0.00% | SELL | -30,988 | 80.00 | 387.35 | 2026-02-02 | 343.45 | 12.78% | target_rebalance |
| VRT | 6.11% | 8.31% | BUY | 8,598 | 65.00 | 367.13 | 2026-03-02 | 257.69 | 42.47% | target_rebalance |
| VZ | 4.85% | 0.00% | SELL | -18,932 | 395.00 | 47.93 | 2026-03-02 | 49.24 | -2.66% | target_rebalance |
| FTI | 4.68% | 5.14% | BUY | 1,772 | 250.00 | 73.19 | 2026-03-02 | 67.45 | 8.51% | target_rebalance |
| SCCO | 4.55% | 0.00% | SELL | -17,752 | 94.00 | 188.85 | 2026-03-02 | 215.54 | -12.38% | target_rebalance |
| APH | 4.39% | 0.00% | SELL | -17,135 | 134.00 | 127.87 | 2025-10-01 | 134.81 | -5.15% | target_rebalance |
| RGLD | 3.64% | 0.00% | SELL | -14,230 | 58.00 | 245.35 | 2026-03-02 | 303.74 | -19.22% | target_rebalance |
| PR | 2.79% | 0.00% | SELL | -10,892 | 540.00 | 20.17 | 2026-03-02 | 18.63 | 8.24% | target_rebalance |
| ETR | 2.75% | 0.00% | SELL | -10,728 | 95.00 | 112.93 | 2026-03-02 | 106.05 | 6.49% | target_rebalance |
| ATI | 2.47% | 0.00% | SELL | -9,661 | 60.00 | 161.01 | 2026-03-02 | 166.42 | -3.25% | target_rebalance |
| BKNG | 2.47% | 0.00% | SELL | -9,634 | 60.00 | 160.56 | 2026-03-02 | 166.81 | -3.75% | target_rebalance |
| CASH | 25.04% | 0.00% | DEPLOY_CASH | 0 | 0.00 | 1.00 |  | 1.00 | 0.00% | uninvested_cash |
