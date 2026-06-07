# Metric Hygiene Report

Official performance evidence is broker-ledger only: next-close fills, integer shares, cash, and costs.
Legacy/proxy/weight-level metrics are retained as deprecated research context and cannot produce a production verdict.

## Official Metrics

| Portfolio | CAGR | Target | MDD | Target | Sharpe | Avg Cash | Target Pass | Production Valid | Cash Trap |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 32.38% | 35.00% | -28.45% | -25.00% | 1.183 | 23.36% | false | true | false |
| concentrated | 37.34% | 50.00% | -31.72% | -25.00% | 1.271 | 44.25% | false | true | true |

## Deprecated Metrics

- `backtest_metrics.json` -> `deprecated_legacy_backtest_metrics.json`: DO_NOT_USE_FOR_PRODUCTION=true, production_valid=false
- `concentrated_backtest_metrics.json` -> `deprecated_concentrated_weight_level_metrics.json`: DO_NOT_USE_FOR_PRODUCTION=true, production_valid=false

## Cash Trap Guard

- `main`: severity=`ok`, reasons=cash_drag_with_cagr_gap
- `concentrated`: severity=`warn`, reasons=avg_cash_high_without_mdd_target_pass, cash_drag_with_cagr_gap
