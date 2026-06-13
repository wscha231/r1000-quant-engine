# Metric Hygiene Report

Official performance evidence is broker-ledger only: next-close fills, integer shares, cash, and costs.
Legacy/proxy/weight-level metrics are retained as deprecated research context and cannot produce a production verdict.

## Official Metrics

| Portfolio | CAGR | Target | MDD | Target | Sharpe | Avg Cash | Target Pass | Production Valid | Cash Trap |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 31.36% | 30.00% | -37.45% | -25.00% | 1.136 | 19.66% | false | true | false |
| concentrated | 39.79% | 45.00% | -35.20% | -25.00% | 1.185 | 31.97% | false | true | true |

## Deprecated Metrics

- `backtest_metrics.json` -> `deprecated_legacy_backtest_metrics.json`: DO_NOT_USE_FOR_PRODUCTION=true, production_valid=false
- `concentrated_backtest_metrics.json` -> `deprecated_concentrated_weight_level_metrics.json`: DO_NOT_USE_FOR_PRODUCTION=true, production_valid=false

## Cash Trap Guard

- `main`: severity=`ok`, reasons=none
- `concentrated`: severity=`warn`, reasons=avg_cash_high_without_mdd_target_pass, cash_drag_with_cagr_gap
