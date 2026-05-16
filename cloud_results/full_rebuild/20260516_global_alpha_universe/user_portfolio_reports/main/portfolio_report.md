# Main Portfolio Report

This report separates latest target recommendations from the current simulated operating account.
- Recommendation date: `2026-05-15`
- Current account last replay trade date: `2026-05-15`
- Current account stale days versus recommendation date: `0`
- Pending orders needed to match recommendation: `0`

## Performance Scorecard

| Horizon | Return | CAGR | Sharpe | MaxDD | Turnover | Trades | End Cash |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1M | 2.03% | 27.77% | 1.795 | -2.10% | 1.39x | 50 | 1.82% |
| 3M | 2.97% | 13.10% | 0.900 | -7.83% | 2.74x | 98 | 1.82% |
| 6M | 4.69% | 9.81% | 0.683 | -11.76% | 5.98x | 212 | 1.82% |
| 1Y | 14.97% | 14.98% | 0.976 | -11.76% | 11.50x | 391 | 1.82% |
| 2Y | 31.08% | 14.50% | 0.937 | -19.62% | 23.29x | 811 | 1.82% |
| 3Y | 57.58% | 16.36% | 1.085 | -19.62% | 35.57x | 1223 | 1.82% |
| 5Y | 57.91% | 9.58% | 0.650 | -27.07% | 58.36x | 1946 | 1.82% |
| FULL | 131.83% | 12.86% | 0.635 | -27.07% | 55.49x | 2624 | 1.82% |

## Files

- `recommendation_latest.csv`: latest target recommendation, formatted as what to buy/hold to target from the latest close.
- `current_operating_holdings_latest.csv`: actual simulated broker-ledger holdings marked to market, including cash.
- `performance_scorecard.csv`: broker-ledger performance by horizon.
- `*_pie.svg` and `*_bar.svg`: visual weights for recommendation/current holdings.

## Top Recommendations

| Ticker | Weight | Current Weight | Action | Trade Delta | Price | Shares per $100k | Logic |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- |
| GOOG | 14.00% | 13.91% | BUY | 0 | 393.32 | 35 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| APP | 10.48% | 10.37% | BUY | 0 | 501.00 | 20 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=cyclical_recovery |
| CAT | 10.36% | 10.35% | BUY | 0 | 888.31 | 11 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| GEV | 8.86% | 8.60% | BUY | 0 | 1049.23 | 8 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| AMZN | 7.80% | 7.75% | BUY | 0 | 264.14 | 29 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| PLTR | 5.18% | 5.14% | BUY | 0 | 133.99 | 38 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| VRT | 5.18% | 5.12% | BUY | 0 | 370.94 | 13 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| NVT | 5.18% | 5.18% | BUY | 0 | 169.01 | 30 | portfolio_sleeve_label=future_winner; dominant_archetype_label=emerging_growth |
| FIX | 5.10% | 4.30% | BUY | 0 | 1992.74 | 2 | portfolio_sleeve_label=core_compounder; dominant_archetype_label=emerging_growth |
| PR | 4.00% | 4.00% | BUY | 0 | 20.84 | 191 | portfolio_sleeve_label=early_scout; dominant_archetype_label=compounder |
| MLI | 4.00% | 4.00% | BUY | 0 | 136.44 | 29 | portfolio_sleeve_label=future_winner; dominant_archetype_label=emerging_growth |
| ON | 3.90% | 3.90% | BUY | 0 | 113.11 | 34 | portfolio_sleeve_label=early_scout; dominant_archetype_label=emerging_growth |

## Current Holdings

| Ticker | Current Weight | Target Weight | Action | Trade Delta | Shares | Current Price | Entry Date | Entry Price | Return Since Entry | Entry Reason |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- | ---: | ---: | --- |
| GOOG | 13.91% | 14.00% | HOLD | 0 | 82.00 | 393.32 | 2026-01-02 | 354.70 | 10.89% | target_rebalance |
| APP | 10.37% | 10.48% | HOLD | 0 | 48.00 | 501.00 | 2026-05-15 | 501.00 | 0.00% | target_rebalance |
| CAT | 10.35% | 10.36% | HOLD | 0 | 27.00 | 888.31 | 2026-05-15 | 888.31 | 0.00% | target_rebalance |
| GEV | 8.60% | 8.86% | HOLD | 0 | 19.00 | 1049.23 | 2026-03-02 | 978.25 | 7.26% | target_rebalance |
| AMZN | 7.75% | 7.80% | HOLD | 0 | 68.00 | 264.14 | 2026-05-15 | 264.14 | 0.00% | target_rebalance |
| NVT | 5.18% | 5.18% | HOLD | 0 | 71.00 | 169.01 | 2026-05-15 | 169.01 | 0.00% | target_rebalance |
| PLTR | 5.14% | 5.18% | HOLD | 0 | 89.00 | 133.99 | 2026-05-15 | 133.99 | 0.00% | target_rebalance |
| VRT | 5.12% | 5.18% | HOLD | 0 | 32.00 | 370.94 | 2026-05-15 | 370.94 | 0.00% | target_rebalance |
| FIX | 4.30% | 5.10% | HOLD | 0 | 5.00 | 1992.74 | 2026-05-15 | 1992.74 | 0.00% | target_rebalance |
| MLI | 4.00% | 4.00% | HOLD | 0 | 68.00 | 136.44 | 2026-05-15 | 136.44 | 0.00% | target_rebalance |
| PR | 4.00% | 4.00% | HOLD | 0 | 445.00 | 20.84 | 2026-03-02 | 19.18 | 8.66% | target_rebalance |
| ON | 3.90% | 3.90% | HOLD | 0 | 80.00 | 113.11 | 2026-05-15 | 113.11 | 0.00% | target_rebalance |
| FTI | 3.66% | 3.66% | HOLD | 0 | 119.00 | 71.28 | 2026-03-02 | 67.96 | 4.88% | target_rebalance |
| NXPI | 3.27% | 3.37% | HOLD | 0 | 26.00 | 291.50 | 2026-05-15 | 291.50 | 0.00% | target_rebalance |
| PWR | 2.99% | 3.23% | HOLD | 0 | 9.00 | 769.99 | 2026-05-15 | 769.99 | 0.00% | target_rebalance |
| UMC | 2.83% | 2.82% | HOLD | 0 | 381.00 | 17.20 | 2026-05-15 | 17.20 | 0.00% | target_rebalance |
| CBOE | 2.82% | 2.86% | HOLD | 0 | 18.00 | 363.02 | 2026-05-15 | 363.02 | 0.00% | target_rebalance |
| CASH | 1.82% | 0.00% | HOLD_CASH | 0 | 0.00 | 1.00 |  | 1.00 | 0.00% | uninvested_cash |
