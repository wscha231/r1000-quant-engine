# Metric Hygiene Report

Official performance evidence is broker-ledger only: next-close fills, integer shares, cash, and costs.
Legacy/proxy/weight-level metrics are retained as deprecated research context and cannot produce a production verdict.

## Official Metrics

| Portfolio | CAGR | Target | MDD | Target | Sharpe | Avg Cash | Target Pass | Production Valid | Cash Trap |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 34.51% | 35.00% | -26.01% | -25.00% | 1.275 | 26.61% | false | true | false |
| concentrated | 44.86% | 50.00% | -25.83% | -25.00% | 1.406 | 42.31% | false | true | false |

## Deprecated Metrics

- `backtest_metrics.json` -> `deprecated_legacy_backtest_metrics.json`: DO_NOT_USE_FOR_PRODUCTION=true, production_valid=false
- `concentrated_backtest_metrics.json` -> `deprecated_concentrated_weight_level_metrics.json`: DO_NOT_USE_FOR_PRODUCTION=true, production_valid=false

## Cash Trap Guard

- `main`: severity=`ok`, reasons=cash_drag_with_cagr_gap
- `concentrated`: severity=`ok`, reasons=cash_drag_with_cagr_gap
