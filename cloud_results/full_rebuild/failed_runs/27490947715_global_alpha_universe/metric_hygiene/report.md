# Metric Hygiene Report

Official performance evidence is broker-ledger only: next-close fills, integer shares, cash, and costs.
Legacy/proxy/weight-level metrics are retained as deprecated research context and cannot produce a production verdict.

## Official Metrics

| Portfolio | CAGR | Target | MDD | Target | Sharpe | Avg Cash | Target Pass | Production Valid | Cash Trap |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 21.87% | 35.00% | -26.37% | -25.00% | 1.042 | 5.93% | false | true | false |
| concentrated | 28.54% | 50.00% | -42.96% | -25.00% | 1.002 | 0.05% | false | true | false |

## Deprecated Metrics

- `backtest_metrics.json` -> `deprecated_legacy_backtest_metrics.json`: DO_NOT_USE_FOR_PRODUCTION=true, production_valid=false
- `concentrated_backtest_metrics.json` -> `deprecated_concentrated_weight_level_metrics.json`: DO_NOT_USE_FOR_PRODUCTION=true, production_valid=false

## Cash Trap Guard

- `main`: severity=`ok`, reasons=none
- `concentrated`: severity=`ok`, reasons=none
