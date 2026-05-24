# Main Portfolio Report

This report separates latest target recommendations from the current simulated operating account.
- Recommendation date: `2026-05-22`
- Current account last replay trade date: `2026-03-02`
- Current account stale days versus recommendation date: `81`
- Pending orders needed to match recommendation: `27`

## Performance Scorecard

| Horizon | Return | CAGR | Sharpe | MaxDD | Turnover | Trades | End Cash |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1M | 8.95% | 183.99% | 3.927 | -5.22% | 0.00x | 0 | 24.80% |
| 3M | 14.33% | 74.36% | 2.240 | -9.34% | 1.33x | 29 | 24.80% |
| 6M | 31.03% | 73.58% | 2.380 | -11.49% | 4.82x | 114 | 24.80% |
| 1Y | 54.87% | 54.91% | 2.011 | -12.04% | 10.06x | 257 | 24.80% |
| 2Y | 80.84% | 34.50% | 1.483 | -20.86% | 21.69x | 618 | 24.80% |
| 3Y | 146.52% | 35.08% | 1.615 | -20.86% | 33.24x | 939 | 24.80% |
| 5Y | 120.97% | 17.21% | 0.906 | -32.45% | 57.88x | 1591 | 24.80% |
| FULL | 287.34% | 21.45% | 1.044 | -32.45% | 39.58x | 2127 | 24.80% |

## Files

- `recommendation_latest.csv`: latest target recommendation, formatted as what to buy/hold to target from the latest close.
- `current_operating_holdings_latest.csv`: actual simulated broker-ledger holdings marked to market, including cash.
- `performance_scorecard.csv`: broker-ledger performance by horizon.
- `*_pie.svg` and `*_bar.svg`: visual weights for recommendation/current holdings.

## Top Recommendations

| Ticker | Weight | Current Weight | Action | Trade Delta | Price | Shares per $100k | Logic |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- |
| GOOG | 19.80% | 0.00% | BUY | 76,707 | 379.38 | 52 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| VRT | 12.44% | 7.19% | BUY | 20,365 | 327.46 | 38 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| GEV | 11.53% | 0.00% | BUY | 44,661 | 1038.74 | 11 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| AMD | 7.44% | 0.00% | BUY | 28,829 | 467.51 | 15 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| MRVL | 7.44% | 0.00% | BUY | 28,829 | 196.33 | 37 | portfolio_sleeve_label=future_winner; dominant_archetype_label=emerging_growth |
| ARM | 7.44% | 0.00% | BUY | 28,829 | 306.51 | 24 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| UMC | 5.59% | 0.00% | BUY | 21,660 | 18.22 | 306 | portfolio_sleeve_label=early_scout; dominant_archetype_label=emerging_growth |
| RKLB | 4.92% | 0.00% | BUY | 19,064 | 135.76 | 36 | portfolio_sleeve_label=future_winner; dominant_archetype_label=emerging_growth |
| NXPI | 4.60% | 0.00% | BUY | 17,834 | 316.47 | 14 | portfolio_sleeve_label=future_winner; dominant_archetype_label=emerging_growth |
| TKR | 3.86% | 0.00% | BUY | 14,943 | 119.95 | 32 | portfolio_sleeve_label=early_scout; dominant_archetype_label=emerging_growth |
| MLI | 3.86% | 0.00% | BUY | 14,943 | 133.39 | 28 | portfolio_sleeve_label=future_winner; dominant_archetype_label=emerging_growth |
| ON | 3.84% | 0.00% | BUY | 14,857 | 116.20 | 33 | portfolio_sleeve_label=early_scout; dominant_archetype_label=emerging_growth |

## Current Holdings

| Ticker | Current Weight | Target Weight | Action | Trade Delta | Shares | Current Price | Entry Date | Entry Price | Return Since Entry | Entry Reason |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- | ---: | ---: | --- |
| MU | 9.11% | 0.00% | SELL | -35,297 | 47.00 | 751.00 | 2025-12-01 | 240.26 | 212.58% | target_rebalance |
| BE | 8.98% | 0.00% | SELL | -34,786 | 115.00 | 302.49 | 2026-03-02 | 166.00 | 82.22% | target_rebalance |
| KO | 7.93% | 0.00% | SELL | -30,718 | 377.00 | 81.48 | 2026-03-02 | 79.67 | 2.27% | target_rebalance |
| LRCX | 7.41% | 0.00% | SELL | -28,703 | 94.00 | 305.35 | 2026-01-02 | 199.88 | 52.76% | target_rebalance |
| VRT | 7.19% | 12.44% | BUY | 20,365 | 85.00 | 327.46 | 2026-03-02 | 257.69 | 27.08% | target_rebalance |
| AMAT | 5.69% | 0.00% | SELL | -22,040 | 51.00 | 432.16 | 2026-02-02 | 341.43 | 26.57% | target_rebalance |
| FTI | 5.52% | 0.00% | SELL | -21,368 | 301.00 | 70.99 | 2026-03-02 | 67.40 | 5.32% | target_rebalance |
| VZ | 4.77% | 0.00% | SELL | -18,470 | 382.00 | 48.35 | 2026-03-02 | 49.24 | -1.81% | target_rebalance |
| SCCO | 4.73% | 0.00% | SELL | -18,326 | 102.00 | 179.67 | 2026-03-02 | 215.55 | -16.65% | target_rebalance |
| LITE | 4.16% | 0.00% | SELL | -16,097 | 17.00 | 946.90 | 2025-12-01 | 591.65 | 60.04% | target_rebalance |
| PR | 2.78% | 0.00% | SELL | -10,751 | 526.00 | 20.44 | 2026-03-02 | 18.63 | 9.69% | target_rebalance |
| ETR | 2.67% | 0.00% | SELL | -10,341 | 92.00 | 112.40 | 2026-03-02 | 106.05 | 5.99% | target_rebalance |
| ATI | 2.43% | 0.00% | SELL | -9,413 | 58.00 | 162.29 | 2026-03-02 | 166.42 | -2.48% | target_rebalance |
| THC | 1.84% | 0.00% | SELL | -7,125 | 41.00 | 173.78 | 2026-03-02 | 235.12 | -26.09% | target_rebalance |
| CASH | 24.80% | 0.00% | DEPLOY_CASH | 0 | 0.00 | 1.00 |  | 1.00 | 0.00% | uninvested_cash |
