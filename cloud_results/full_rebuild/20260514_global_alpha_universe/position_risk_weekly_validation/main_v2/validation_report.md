# Position-Risk Weekly Validation

Daily stop checks and weekly relative-performance checks on monthly holding books.

- Portfolio: `main`
- CAGR: 12.27%
- Sharpe: 0.695
- MaxDD: -32.48%
- Price coverage: 100.00%
- Exits: 310
- Trims: 64
- Trade log: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/position_risk_weekly_validation/main_v2/trade_log.csv`

This validates whether monthly proxy exits are observable on cached daily prices. It is stricter than a month-end cap, but still not live execution evidence.
