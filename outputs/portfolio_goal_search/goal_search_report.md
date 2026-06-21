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
| main | `main_latest_champion` | 34.87% | 0.00pp | -14.78% | 0.00pp | true | `target_pass_review` |
| concentrated | `concentrated_latest_champion` | 54.91% | 0.00pp | -14.70% | 0.00pp | true | `target_pass_review` |

## Best Production-Compatible Candidates

| Portfolio | Candidate | CAGR | Gap | MaxDD | Gap | Target Pass | Action |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| main | `main_broker_ledger_replay` | 34.68% | 0.00pp | -26.05% | 1.05pp | false | `needs_drawdown_reduction` |
| concentrated | `concentrated_broker_ledger_replay` | 44.66% | 5.34pp | -25.86% | 0.00pp | false | `needs_alpha_boost` |

## Main Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `main_latest_champion` | 34.87% | 0.00pp | -14.78% | 0.00pp | 1.868 | true | latest_run:outputs/backtest_metrics.json |
| `main_rebalance_interval_adaptive_I1` | 34.87% | 0.00pp | -14.78% | 0.00pp | 1.868 | true | latest_run_report:outputs/reports/rebalance_interval_comparison.csv |
| `main_rebalance_interval_fixed_interval_I1` | 34.60% | 0.00pp | -14.68% | 0.00pp | 1.851 | true | latest_run_report:outputs/reports/rebalance_interval_comparison.csv |
| `main_sleeve_cap_policy_sleeve_cap_policy_I1` | 32.37% | 0.00pp | -15.39% | 0.00pp | 1.858 | true | latest_run_report:outputs/reports/sleeve_cap_policy_comparison.csv |
| `main_sleeve_cap_policy_sleeve_cap_policy_I1` | 32.19% | 0.00pp | -14.40% | 0.00pp | 1.765 | true | latest_run_report:outputs/reports/sleeve_cap_policy_comparison.csv |

## Concentrated Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `concentrated_latest_champion` | 54.91% | 0.00pp | -14.70% | 0.00pp | 1.812 | true | latest_run:outputs/concentrated_backtest_metrics.json |
| `concentrated_grid_N4_score_power_I1` | 54.91% | 0.00pp | -14.70% | 0.00pp | 1.812 | true | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `concentrated_grid_N4_conviction_curve_I1` | 53.21% | 0.00pp | -14.63% | 0.00pp | 1.789 | true | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `concentrated_grid_N4_winner_take_all_I1` | 51.25% | 0.00pp | -12.52% | 0.00pp | 1.848 | true | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `concentrated_grid_N3_score_power_I1` | 54.24% | 0.00pp | -21.34% | 0.00pp | 1.667 | true | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |

## Next Actions

- Main: research/proxy target-pass exists, but no production-compatible account replay passes; convert the rule to broker-ledger evidence before promotion.
- Concentrated: research/proxy target-pass exists, but broker-ledger conversion does not pass; do not promote until next-close replay supports it.
