# Main Portfolio Report

This report separates latest target recommendations from the current simulated operating account.
- Recommendation date: `2026-05-08`
- Current account last replay trade date: `2026-03-02`
- Current account stale days versus recommendation date: `67`
- Pending orders needed to match recommendation: `40`

## Performance Scorecard

| Horizon | Return | CAGR | Sharpe | MaxDD | Turnover | Trades | End Cash |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1M | 7.75% | 148.06% | 5.777 | -1.84% | 0.00x | 0 | 26.15% |
| 3M | 8.56% | 40.65% | 1.890 | -7.37% | 1.29x | 31 | 26.15% |
| 6M | 21.17% | 47.96% | 2.028 | -8.92% | 4.44x | 147 | 26.15% |
| 1Y | 47.78% | 47.82% | 2.242 | -10.50% | 9.81x | 309 | 26.15% |
| 2Y | 73.98% | 31.93% | 1.560 | -21.20% | 21.35x | 696 | 26.15% |
| 3Y | 133.75% | 32.71% | 1.643 | -21.20% | 32.14x | 1068 | 26.15% |
| 5Y | 135.54% | 18.71% | 1.006 | -28.62% | 54.66x | 1760 | 26.15% |
| FULL | 300.19% | 21.84% | 1.056 | -28.62% | 37.90x | 2464 | 26.15% |

## Files

- `recommendation_latest.csv`: latest target recommendation, formatted as what to buy/hold to target from the latest close.
- `current_operating_holdings_latest.csv`: actual simulated broker-ledger holdings marked to market, including cash.
- `performance_scorecard.csv`: broker-ledger performance by horizon.
- `*_pie.svg` and `*_bar.svg`: visual weights for recommendation/current holdings.

## Top Recommendations

| Ticker | Weight | Current Weight | Action | Trade Delta | Price | Shares per $100k | Logic |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- |
| GOOGL | 12.00% | 0.00% | BUY | 48,023 | 400.80 | 29 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| AMZN | 11.26% | 0.00% | BUY | 45,042 | 272.68 | 41 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| GEV | 9.92% | 0.00% | BUY | 39,679 | 1040.15 | 9 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| TSM | 7.75% | 0.00% | BUY | 31,019 | 411.68 | 18 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| VRT | 6.03% | 4.08% | BUY | 7,815 | 339.97 | 17 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| TXN | 5.09% | 0.00% | BUY | 20,372 | 287.80 | 17 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| GLW | 5.07% | 0.00% | BUY | 20,309 | 186.94 | 27 | portfolio_sleeve_label=future_winner; dominant_archetype_label=emerging_growth |
| FIX | 5.01% | 0.00% | BUY | 20,040 | 1952.37 | 2 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| FTI | 4.64% | 3.35% | BUY | 5,155 | 70.15 | 66 | portfolio_sleeve_label=future_winner; dominant_archetype_label=emerging_growth |
| LRCX | 4.63% | 6.17% | SELL | -6,186 | 294.05 | 15 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| PWR | 4.52% | 0.00% | BUY | 18,087 | 745.00 | 6 | portfolio_sleeve_label=future_winner; dominant_archetype_label=emerging_growth |
| CBOE | 4.34% | 0.00% | BUY | 17,388 | 348.56 | 12 | portfolio_sleeve_label=future_winner; dominant_archetype_label=emerging_growth |

## Current Holdings

| Ticker | Current Weight | Target Weight | Action | Trade Delta | Shares | Current Price | Entry Date | Entry Price | Return Since Entry | Entry Reason |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- | ---: | ---: | --- |
| AMAT | 9.14% | 0.00% | SELL | -36,577 | 84.00 | 435.44 | 2026-01-02 | 305.55 | 42.51% | target_rebalance |
| MU | 8.96% | 0.00% | SELL | -35,847 | 48.00 | 746.81 | 2025-12-01 | 240.26 | 210.83% | target_rebalance |
| LRCX | 6.17% | 4.63% | SELL | -6,186 | 84.00 | 294.05 | 2025-11-03 | 160.27 | 83.47% | target_rebalance |
| GOOG | 4.76% | 0.00% | SELL | -19,058 | 48.00 | 397.05 | 2026-02-02 | 344.66 | 15.20% | target_rebalance |
| ETR | 4.74% | 0.00% | SELL | -18,970 | 170.00 | 111.59 | 2026-03-02 | 106.05 | 5.22% | target_rebalance |
| VRT | 4.08% | 6.03% | BUY | 7,815 | 48.00 | 339.97 | 2026-03-02 | 257.69 | 31.93% | target_rebalance |
| VZ | 3.62% | 0.00% | SELL | -14,497 | 307.00 | 47.22 | 2026-03-02 | 49.24 | -4.10% | target_rebalance |
| SCCO | 3.47% | 0.00% | SELL | -13,897 | 75.00 | 185.29 | 2026-03-02 | 218.85 | -15.33% | target_rebalance |
| FTI | 3.35% | 4.64% | BUY | 5,155 | 191.00 | 70.15 | 2026-03-02 | 67.45 | 4.01% | target_rebalance |
| KO | 3.15% | 0.00% | SELL | -12,626 | 161.00 | 78.42 | 2026-03-02 | 79.67 | -1.57% | target_rebalance |
| APH | 3.14% | 0.00% | SELL | -12,547 | 98.00 | 128.03 | 2026-03-02 | 134.89 | -5.09% | target_rebalance |
| ADI | 3.02% | 0.00% | SELL | -12,079 | 29.00 | 416.52 | 2026-03-02 | 351.31 | 18.56% | target_rebalance |
| COST | 2.77% | 0.00% | SELL | -11,097 | 11.00 | 1008.79 | 2026-03-02 | 1001.32 | 0.75% | target_rebalance |
| PR | 2.73% | 4.00% | BUY | 5,063 | 555.00 | 19.72 | 2026-03-02 | 18.63 | 5.83% | target_rebalance |
| BKNG | 2.57% | 0.00% | SELL | -10,288 | 62.00 | 165.93 | 2026-03-02 | 166.81 | -0.53% | target_rebalance |
| GTLS | 2.54% | 0.00% | SELL | -10,164 | 49.00 | 207.43 | 2026-03-02 | 207.06 | 0.18% | target_rebalance |
| RGLD | 2.45% | 0.00% | SELL | -9,795 | 41.00 | 238.91 | 2026-03-02 | 303.74 | -21.34% | target_rebalance |
| ATI | 1.86% | 0.00% | SELL | -7,444 | 47.00 | 158.39 | 2026-03-02 | 166.42 | -4.83% | target_rebalance |
| TPR | 0.23% | 0.00% | SELL | -934 | 7.00 | 133.48 | 2026-02-02 | 129.32 | 3.21% | target_rebalance |
| PH | 0.22% | 0.00% | SELL | -879 | 1.00 | 878.83 | 2026-02-02 | 948.09 | -7.30% | target_rebalance |
