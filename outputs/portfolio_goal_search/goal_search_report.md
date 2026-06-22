# Portfolio Goal Search

Artifact-only ranking against explicit portfolio targets. Production defaults are unchanged.

## Targets

| Portfolio | CAGR Target | MaxDD Target |
| --- | ---: | ---: |
| main | 30.00% | -25.00% |
| concentrated | 50.00% | -28.00% |

## Best Candidates

| Portfolio | Candidate | CAGR | Gap | MaxDD | Gap | Target Pass | Action |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| main | `main_rebalance_interval_fixed_interval_I1` | 33.89% | 0.00pp | -13.95% | 0.00pp | true | `target_pass_review` |
| concentrated | `concentrated_latest_champion` | 50.60% | 0.00pp | -16.49% | 0.00pp | true | `target_pass_review` |

## Best Production-Compatible Candidates

| Portfolio | Candidate | CAGR | Gap | MaxDD | Gap | Target Pass | Action |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| main | `main_broker_position_risk_replay` | 30.12% | 0.00pp | -25.89% | 0.89pp | false | `needs_drawdown_reduction` |
| concentrated | `concentrated_broker_ledger_replay` | 44.67% | 5.33pp | -25.87% | 0.00pp | false | `needs_alpha_boost` |

## Main Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `main_rebalance_interval_fixed_interval_I1` | 33.89% | 0.00pp | -13.95% | 0.00pp | 1.865 | true | latest_run_report:outputs/reports/rebalance_interval_comparison.csv |
| `main_latest_champion` | 33.19% | 0.00pp | -14.46% | 0.00pp | 1.844 | true | latest_run:outputs/backtest_metrics.json |
| `main_rebalance_interval_adaptive_I1` | 33.19% | 0.00pp | -14.46% | 0.00pp | 1.844 | true | latest_run_report:outputs/reports/rebalance_interval_comparison.csv |
| `main_sleeve_cap_policy_sleeve_cap_policy_I1` | 31.53% | 0.00pp | -15.22% | 0.00pp | 1.719 | true | latest_run_report:outputs/reports/sleeve_cap_policy_comparison.csv |
| `main_sleeve_cap_policy_sleeve_cap_policy_I1` | 31.17% | 0.00pp | -14.88% | 0.00pp | 1.818 | true | latest_run_report:outputs/reports/sleeve_cap_policy_comparison.csv |

## Concentrated Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `concentrated_latest_champion` | 50.60% | 0.00pp | -16.49% | 0.00pp | 1.743 | true | latest_run:outputs/concentrated_backtest_metrics.json |
| `concentrated_grid_N4_score_power_I1` | 50.60% | 0.00pp | -16.49% | 0.00pp | 1.743 | true | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `concentrated_grid_N3_score_power_I1` | 51.69% | 0.00pp | -23.96% | 0.00pp | 1.594 | true | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `concentrated_grid_N4_conviction_curve_I1` | 49.68% | 0.32pp | -16.21% | 0.00pp | 1.718 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `concentrated_grid_N3_conviction_curve_I1` | 49.65% | 0.35pp | -21.20% | 0.00pp | 1.610 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |

## Next Actions

- Main: research/proxy target-pass exists, but no production-compatible account replay passes; convert the rule to broker-ledger evidence before promotion.
- Concentrated: research/proxy target-pass exists, but broker-ledger conversion does not pass; do not promote until next-close replay supports it.
