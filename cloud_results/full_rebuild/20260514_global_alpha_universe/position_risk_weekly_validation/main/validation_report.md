# Position-Risk Weekly Validation

Daily stop checks and weekly relative-performance checks on monthly holding books.

- Portfolio: `main`
- CAGR: 12.57%
- Sharpe: 0.744
- MaxDD: -29.19%
- Price coverage: 100.00%
- Exits: 596
- Trims: 178
- Trade log: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/position_risk_weekly_validation/main/trade_log.csv`

This validates whether monthly proxy exits are observable on cached daily prices. It is stricter than a month-end cap, but still not live execution evidence.
