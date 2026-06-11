# Metric Hygiene Report

Official performance evidence is broker-ledger only: next-close fills, integer shares, cash, and costs.
Legacy/proxy/weight-level metrics are retained as deprecated research context and cannot produce a production verdict.

## Official Metrics

| Portfolio | CAGR | Target | MDD | Target | Sharpe | Avg Cash | Target Pass | Production Valid | Cash Trap |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 27.28% | 30.00% | -38.95% | -20.00% | 1.031 | 19.27% | false | true | true |
| concentrated | 26.87% | 50.00% | -48.02% | -25.00% | 0.898 | 29.79% | false | true | true |

## Deprecated Metrics

- `backtest_metrics.json` -> `deprecated_legacy_backtest_metrics.json`: DO_NOT_USE_FOR_PRODUCTION=true, production_valid=false
- `concentrated_backtest_metrics.json` -> `deprecated_concentrated_weight_level_metrics.json`: DO_NOT_USE_FOR_PRODUCTION=true, production_valid=false

## Cash Trap Guard

- `main`: severity=`warn`, reasons=latest_cash_above_50pct_requires_crisis_state_review
- `concentrated`: severity=`warn`, reasons=avg_cash_high_without_mdd_target_pass, latest_cash_above_50pct_requires_crisis_state_review, cash_drag_with_cagr_gap
