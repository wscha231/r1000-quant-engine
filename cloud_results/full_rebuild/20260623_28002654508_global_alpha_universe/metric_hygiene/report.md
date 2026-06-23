# Metric Hygiene Report

Official performance evidence is broker-ledger only: next-close fills, integer shares, cash, and costs.
Legacy/proxy/weight-level metrics are retained as deprecated research context and cannot produce a production verdict.

## Official Metrics

| Portfolio | CAGR | Target | MDD | Target | Sharpe | Avg Cash | Target Pass | Production Valid | Cash Trap |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 35.02% | 30.00% | -26.03% | -25.00% | 1.276 | 26.36% | false | true | false |
| concentrated | 45.96% | 50.00% | -24.60% | -28.00% | 1.434 | 41.33% | false | true | false |

## Deprecated Metrics

- `backtest_metrics.json` -> `deprecated_legacy_backtest_metrics.json`: DO_NOT_USE_FOR_PRODUCTION=true, production_valid=false
- `concentrated_backtest_metrics.json` -> `deprecated_concentrated_weight_level_metrics.json`: DO_NOT_USE_FOR_PRODUCTION=true, production_valid=false

## Cash Trap Guard

- `main`: severity=`ok`, reasons=none
- `concentrated`: severity=`ok`, reasons=cash_drag_with_cagr_gap
