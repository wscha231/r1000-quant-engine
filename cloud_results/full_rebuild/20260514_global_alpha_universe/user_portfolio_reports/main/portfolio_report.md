# Main Portfolio Report

This report separates latest target recommendations from the current simulated operating account.
- Recommendation date: `2026-05-14`
- Current account last replay trade date: `2026-05-14`
- Current account stale days versus recommendation date: `0`
- Pending orders needed to match recommendation: `1`

## Performance Scorecard

| Horizon | Return | CAGR | Sharpe | MaxDD | Turnover | Trades | End Cash |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1M | 10.71% | 245.18% | 6.449 | -2.10% | 1.50x | 31 | 0.45% |
| 3M | 17.46% | 98.09% | 3.115 | -9.58% | 2.78x | 62 | 0.45% |
| 6M | 31.72% | 74.38% | 2.539 | -10.55% | 6.10x | 187 | 0.45% |
| 1Y | 36.15% | 36.18% | 1.602 | -12.48% | 11.76x | 364 | 0.45% |
| 2Y | 58.35% | 25.86% | 1.217 | -20.87% | 23.32x | 815 | 0.45% |
| 3Y | 126.48% | 31.35% | 1.493 | -20.87% | 34.58x | 1246 | 0.45% |
| 5Y | 114.90% | 16.53% | 0.924 | -31.93% | 56.12x | 2107 | 0.45% |
| FULL | 228.97% | 18.44% | 0.848 | -31.93% | 42.03x | 2873 | 0.45% |

## Files

- `recommendation_latest.csv`: latest target recommendation, formatted as what to buy/hold to target from the latest close.
- `current_operating_holdings_latest.csv`: actual simulated broker-ledger holdings marked to market, including cash.
- `performance_scorecard.csv`: broker-ledger performance by horizon.
- `*_pie.svg` and `*_bar.svg`: visual weights for recommendation/current holdings.

## Top Recommendations

| Ticker | Weight | Current Weight | Action | Trade Delta | Price | Shares per $100k | Logic |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- |
| GOOG | 16.01% | 0.00% | BUY | 0 | 397.24 | 40 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| MRVL | 6.70% | 0.00% | BUY | 0 | 184.61 | 36 | portfolio_sleeve_label=future_winner; dominant_archetype_label=emerging_growth |
| VRT | 6.70% | 0.00% | BUY | 0 | 373.98 | 17 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| LRCX | 6.58% | 6.67% | SELL | -304 | 300.49 | 21 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| FIX | 6.45% | 0.00% | BUY | 0 | 2043.24 | 3 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| FTI | 6.41% | 0.00% | BUY | 0 | 72.94 | 87 | portfolio_sleeve_label=future_winner; dominant_archetype_label=emerging_growth |
| PWR | 6.40% | 0.00% | BUY | 0 | 775.49 | 8 | portfolio_sleeve_label=future_winner; dominant_archetype_label=emerging_growth |
| UMC | 6.38% | 0.00% | BUY | 0 | 17.30 | 368 | portfolio_sleeve_label=future_winner; dominant_archetype_label=emerging_growth |
| CBOE | 6.37% | 0.00% | BUY | 0 | 364.87 | 17 | portfolio_sleeve_label=future_winner; dominant_archetype_label=emerging_growth |
| AMD | 4.00% | 0.00% | BUY | 0 | 449.58 | 8 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| ON | 4.00% | 0.00% | BUY | 0 | 118.92 | 33 | portfolio_sleeve_label=early_scout; dominant_archetype_label=emerging_growth |
| NXPI | 4.00% | 0.00% | BUY | 0 | 293.86 | 13 | portfolio_sleeve_label=future_winner; dominant_archetype_label=emerging_growth |

## Current Holdings

| Ticker | Current Weight | Target Weight | Action | Trade Delta | Shares | Current Price | Entry Date | Entry Price | Return Since Entry | Entry Reason |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- | ---: | ---: | --- |
| GOOG | 15.94% | 0.00% | HOLD | 0 | 132.00 | 397.24 | 2026-05-14 | 397.24 | 0.00% | target_rebalance |
| VRT | 6.71% | 0.00% | HOLD | 0 | 59.00 | 373.98 | 2026-03-02 | 304.99 | 22.62% | target_rebalance |
| MRVL | 6.68% | 0.00% | HOLD | 0 | 119.00 | 184.61 | 2026-05-14 | 184.61 | 0.00% | target_rebalance |
| LRCX | 6.67% | 6.58% | SELL | -304 | 73.00 | 300.49 | 2025-10-01 | 150.69 | 99.41% | target_rebalance |
| FTI | 6.41% | 0.00% | HOLD | 0 | 289.00 | 72.94 | 2026-03-02 | 69.39 | 5.12% | target_rebalance |
| UMC | 6.38% | 0.00% | HOLD | 0 | 1214.00 | 17.30 | 2026-05-14 | 17.30 | 0.00% | target_rebalance |
| PWR | 6.36% | 0.00% | HOLD | 0 | 27.00 | 775.49 | 2026-05-14 | 775.49 | 0.00% | target_rebalance |
| CBOE | 6.32% | 0.00% | HOLD | 0 | 57.00 | 364.87 | 2026-05-14 | 364.87 | 0.00% | target_rebalance |
| FIX | 6.21% | 0.00% | HOLD | 0 | 10.00 | 2043.24 | 2026-05-14 | 2043.24 | 0.00% | target_rebalance |
| HPE | 4.01% | 0.00% | HOLD | 0 | 393.00 | 33.53 | 2026-05-14 | 33.53 | 0.00% | target_rebalance |
| PR | 4.01% | 0.00% | HOLD | 0 | 650.00 | 20.27 | 2026-03-02 | 19.15 | 5.82% | target_rebalance |
| MLI | 4.00% | 0.00% | HOLD | 0 | 94.00 | 140.13 | 2026-05-14 | 140.13 | 0.00% | target_rebalance |
| STM | 4.00% | 0.00% | HOLD | 0 | 203.00 | 64.79 | 2026-05-14 | 64.79 | 0.00% | target_rebalance |
| TKR | 3.98% | 0.00% | HOLD | 0 | 112.00 | 117.00 | 2026-05-14 | 117.00 | 0.00% | target_rebalance |
| ON | 3.98% | 0.00% | HOLD | 0 | 110.00 | 118.92 | 2026-05-14 | 118.92 | 0.00% | target_rebalance |
| AMD | 3.96% | 0.00% | HOLD | 0 | 29.00 | 449.58 | 2026-05-14 | 449.58 | 0.00% | target_rebalance |
| NXPI | 3.93% | 0.00% | HOLD | 0 | 44.00 | 293.86 | 2026-05-14 | 293.86 | 0.00% | target_rebalance |
| CASH | 0.45% | 93.42% | DEPLOY_CASH | 0 | 0.00 | 1.00 |  | 1.00 | 0.00% | uninvested_cash |
