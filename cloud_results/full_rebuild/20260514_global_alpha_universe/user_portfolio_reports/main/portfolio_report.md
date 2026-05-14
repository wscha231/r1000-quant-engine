# Main Portfolio Report

This report separates latest target recommendations from the current simulated operating account.
- Recommendation date: `2026-05-13`
- Current account last replay trade date: `2026-03-02`
- Current account stale days versus recommendation date: `72`
- Pending orders needed to match recommendation: `32`

## Performance Scorecard

| Horizon | Return | CAGR | Sharpe | MaxDD | Turnover | Trades | End Cash |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1M | 11.99% | 296.97% | 7.135 | -2.07% | 0.00x | 0 | 24.64% |
| 3M | 16.98% | 90.36% | 3.123 | -9.39% | 1.27x | 47 | 24.64% |
| 6M | 36.70% | 87.91% | 2.786 | -10.88% | 4.69x | 156 | 24.64% |
| 1Y | 49.59% | 49.64% | 1.986 | -10.97% | 10.12x | 351 | 24.64% |
| 2Y | 79.91% | 34.16% | 1.538 | -20.81% | 21.40x | 807 | 24.64% |
| 3Y | 143.69% | 34.63% | 1.612 | -20.81% | 32.46x | 1223 | 24.64% |
| 5Y | 136.35% | 18.77% | 1.029 | -32.02% | 53.92x | 2024 | 24.64% |
| FULL | 264.87% | 20.20% | 1.057 | -32.02% | 37.56x | 2791 | 24.64% |

## Files

- `recommendation_latest.csv`: latest target recommendation, formatted as what to buy/hold to target from the latest close.
- `current_operating_holdings_latest.csv`: actual simulated broker-ledger holdings marked to market, including cash.
- `performance_scorecard.csv`: broker-ledger performance by horizon.
- `*_pie.svg` and `*_bar.svg`: visual weights for recommendation/current holdings.

## Top Recommendations

| Ticker | Weight | Current Weight | Action | Trade Delta | Price | Shares per $100k | Logic |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- |
| GOOG | 14.00% | 7.66% | BUY | 23,149 | 399.04 | 35 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| GEV | 11.93% | 0.00% | BUY | 43,533 | 1062.57 | 11 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| AMD | 5.70% | 0.00% | BUY | 20,802 | 445.50 | 12 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| MRVL | 5.70% | 0.00% | BUY | 20,802 | 177.95 | 32 | portfolio_sleeve_label=future_winner; dominant_archetype_label=emerging_growth |
| VRT | 5.70% | 3.45% | BUY | 8,222 | 369.99 | 15 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| WDC | 5.25% | 0.00% | BUY | 19,166 | 494.09 | 10 | portfolio_sleeve_label=future_winner; dominant_archetype_label=emerging_growth |
| FIX | 5.10% | 0.00% | BUY | 18,591 | 2034.63 | 2 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| UMC | 4.94% | 0.00% | BUY | 18,017 | 15.92 | 310 | portfolio_sleeve_label=future_winner; dominant_archetype_label=emerging_growth |
| FTI | 4.88% | 2.91% | BUY | 7,180 | 72.68 | 67 | portfolio_sleeve_label=future_winner; dominant_archetype_label=emerging_growth |
| CBOE | 4.80% | 0.00% | BUY | 17,527 | 366.70 | 13 | portfolio_sleeve_label=future_winner; dominant_archetype_label=emerging_growth |
| ON | 4.00% | 0.00% | BUY | 14,595 | 115.71 | 34 | portfolio_sleeve_label=early_scout; dominant_archetype_label=emerging_growth |
| NXPI | 4.00% | 0.00% | BUY | 14,595 | 298.41 | 13 | portfolio_sleeve_label=future_winner; dominant_archetype_label=emerging_growth |

## Current Holdings

| Ticker | Current Weight | Target Weight | Action | Trade Delta | Shares | Current Price | Entry Date | Entry Price | Return Since Entry | Entry Reason |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- | ---: | ---: | --- |
| MU | 11.89% | 0.00% | SELL | -43,396 | 54.00 | 803.63 | 2025-12-01 | 240.26 | 234.48% | target_rebalance |
| LRCX | 8.34% | 0.00% | SELL | -30,430 | 103.00 | 295.44 | 2025-11-03 | 173.39 | 70.39% | target_rebalance |
| GOOG | 7.66% | 14.00% | BUY | 23,149 | 70.00 | 399.04 | 2026-01-02 | 309.73 | 28.84% | target_rebalance |
| AMAT | 6.58% | 0.00% | SELL | -24,014 | 55.00 | 436.61 | 2026-02-02 | 350.49 | 24.57% | target_rebalance |
| BE | 4.84% | 0.00% | SELL | -17,675 | 61.00 | 289.76 | 2026-02-02 | 156.13 | 85.59% | target_rebalance |
| KO | 4.51% | 0.00% | SELL | -16,453 | 205.00 | 80.26 | 2026-03-02 | 79.67 | 0.74% | target_rebalance |
| ETR | 3.60% | 0.00% | SELL | -13,145 | 117.00 | 112.35 | 2026-03-02 | 106.05 | 5.94% | target_rebalance |
| VRT | 3.45% | 5.70% | BUY | 8,222 | 34.00 | 369.99 | 2026-03-02 | 257.69 | 43.58% | target_rebalance |
| FTI | 2.91% | 4.88% | BUY | 7,180 | 146.00 | 72.68 | 2026-03-02 | 67.45 | 7.76% | target_rebalance |
| SCCO | 2.73% | 0.00% | SELL | -9,978 | 52.00 | 191.89 | 2026-03-02 | 215.55 | -10.98% | target_rebalance |
| APH | 2.73% | 0.00% | SELL | -9,971 | 80.00 | 124.64 | 2025-09-02 | 134.57 | -7.38% | target_rebalance |
| PR | 2.72% | 4.00% | BUY | 4,657 | 491.00 | 20.24 | 2026-03-02 | 18.63 | 8.62% | target_rebalance |
| ADI | 2.61% | 0.00% | SELL | -9,513 | 22.00 | 432.39 | 2026-03-02 | 351.31 | 23.08% | target_rebalance |
| ATI | 2.48% | 0.00% | SELL | -9,066 | 55.00 | 164.83 | 2026-03-02 | 166.42 | -0.96% | target_rebalance |
| BKNG | 2.29% | 0.00% | SELL | -8,372 | 54.00 | 155.03 | 2025-07-01 | 167.94 | -7.69% | target_rebalance |
| RGLD | 2.15% | 0.00% | SELL | -7,840 | 32.00 | 244.99 | 2026-03-02 | 303.74 | -19.34% | target_rebalance |
| THC | 2.04% | 0.00% | SELL | -7,443 | 38.00 | 195.86 | 2026-03-02 | 235.12 | -16.70% | target_rebalance |
| VZ | 1.81% | 0.00% | SELL | -6,609 | 140.00 | 47.21 | 2026-03-02 | 49.24 | -4.12% | target_rebalance |
| CASH | 24.64% | 0.00% | DEPLOY_CASH | 0 | 0.00 | 1.00 |  | 1.00 | 0.00% | uninvested_cash |
