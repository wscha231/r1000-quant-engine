# Portfolio Goal Search

Artifact-only ranking against explicit portfolio targets. Production defaults are unchanged.

## Targets

| Portfolio | CAGR Target | MaxDD Target |
| --- | ---: | ---: |
| main | 30.00% | -15.00% |
| concentrated | 50.00% | -18.00% |

## Best Candidates

| Portfolio | Candidate | CAGR | Gap | MaxDD | Gap | Target Pass | Action |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| main | `main_v2_position_aware_risk_proxy` | 37.96% | 0.00pp | -12.66% | 0.00pp | true | `target_pass_review` |
| concentrated | `concentrated_position_risk_proxy` | 52.66% | 0.00pp | -16.39% | 0.00pp | true | `target_pass_review` |

## Best Production-Compatible Candidates

| Portfolio | Candidate | CAGR | Gap | MaxDD | Gap | Target Pass | Action |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| main | `main_broker_execution_policy_replay` | 22.17% | 7.83pp | -30.12% | 15.12pp | false | `blocked_both` |
| concentrated | `concentrated_broker_ledger_replay` | 29.42% | 20.59pp | -32.56% | 14.56pp | false | `blocked_both` |

## Main Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `main_v2_position_aware_risk_proxy` | 37.96% | 0.00pp | -12.66% | 0.00pp | 1.805 | true | sidecar:outputs/position_aware_risk_replay/metrics.json#with_position_risk |
| `orchestrator_replay_main_proxy` | 35.12% | 0.00pp | -16.29% | 1.29pp | 1.917 | false | sidecar:outputs/orchestrator_replay/concentrated_balanced/metrics.json#metrics.main_proxy |
| `main_sleeve_cap_policy_sleeve_cap_policy_I1` | 28.70% | 1.30pp | -16.95% | 1.95pp | 1.674 | false | latest_run_report:outputs/reports/sleeve_cap_policy_comparison.csv |
| `main_rebalance_interval_fixed_interval_I1` | 31.20% | 0.00pp | -18.35% | 3.35pp | 1.728 | false | latest_run_report:outputs/reports/rebalance_interval_comparison.csv |
| `main_latest_champion` | 30.87% | 0.00pp | -18.51% | 3.51pp | 1.720 | false | latest_run:outputs/backtest_metrics.json |

## Concentrated Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `concentrated_position_risk_proxy` | 52.66% | 0.00pp | -16.39% | 0.00pp | 1.782 | true | sidecar:outputs/concentrated_position_risk_replay/metrics.json |
| `concentrated_grid_N3_conviction_curve_I1` | 49.89% | 0.11pp | -18.26% | 0.26pp | 1.710 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `concentrated_grid_N3_winner_take_all_I1` | 48.63% | 1.37pp | -18.08% | 0.08pp | 1.708 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `concentrated_grid_N3_score_power_I1` | 48.24% | 1.76pp | -17.13% | 0.00pp | 1.718 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `concentrated_grid_N2_winner_take_all_I1` | 55.68% | 0.00pp | -20.08% | 2.08pp | 1.591 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |

## Next Actions

- Main: research/proxy target-pass exists, but no production-compatible account replay passes; convert the rule to broker-ledger evidence before promotion.
- Concentrated: research/proxy target-pass exists, but broker-ledger conversion does not pass; do not promote until next-close replay supports it.
