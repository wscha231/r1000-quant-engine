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
| main | `main_rebalance_interval_fixed_interval_I1` | 34.03% | 0.00pp | -14.89% | 0.00pp | true | `target_pass_review` |
| concentrated | `concentrated_latest_champion` | 50.95% | 0.00pp | -18.52% | 0.00pp | true | `target_pass_review` |

## Best Production-Compatible Candidates

| Portfolio | Candidate | CAGR | Gap | MaxDD | Gap | Target Pass | Action |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| main | `main_broker_ledger_replay` | 34.28% | 0.00pp | -27.18% | 2.18pp | false | `needs_drawdown_reduction` |
| concentrated | `concentrated_broker_ledger_replay` | 44.37% | 5.63pp | -24.70% | 0.00pp | false | `needs_alpha_boost` |

## Main Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `main_rebalance_interval_fixed_interval_I1` | 34.03% | 0.00pp | -14.89% | 0.00pp | 1.877 | true | latest_run_report:outputs/reports/rebalance_interval_comparison.csv |
| `main_latest_champion` | 33.07% | 0.00pp | -15.84% | 0.00pp | 1.845 | true | latest_run:outputs/backtest_metrics.json |
| `main_rebalance_interval_adaptive_I1` | 33.07% | 0.00pp | -15.84% | 0.00pp | 1.845 | true | latest_run_report:outputs/reports/rebalance_interval_comparison.csv |
| `main_sleeve_cap_policy_sleeve_cap_policy_I1` | 31.72% | 0.00pp | -15.07% | 0.00pp | 1.674 | true | latest_run_report:outputs/reports/sleeve_cap_policy_comparison.csv |
| `main_sleeve_cap_policy_sleeve_cap_policy_I1` | 31.56% | 0.00pp | -16.25% | 0.00pp | 1.801 | true | latest_run_report:outputs/reports/sleeve_cap_policy_comparison.csv |

## Concentrated Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `concentrated_latest_champion` | 50.95% | 0.00pp | -18.52% | 0.00pp | 1.591 | true | latest_run:outputs/concentrated_backtest_metrics.json |
| `concentrated_grid_N3_score_power_I1` | 50.95% | 0.00pp | -18.52% | 0.00pp | 1.591 | true | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `concentrated_grid_N4_score_power_I1` | 49.60% | 0.40pp | -18.44% | 0.00pp | 1.731 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `concentrated_grid_N3_conviction_curve_I1` | 49.28% | 0.72pp | -16.48% | 0.00pp | 1.616 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `concentrated_grid_N3_winner_take_all_I1` | 48.46% | 1.54pp | -15.97% | 0.00pp | 1.646 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |

## Next Actions

- Main: research/proxy target-pass exists, but no production-compatible account replay passes; convert the rule to broker-ledger evidence before promotion.
- Concentrated: research/proxy target-pass exists, but broker-ledger conversion does not pass; do not promote until next-close replay supports it.
