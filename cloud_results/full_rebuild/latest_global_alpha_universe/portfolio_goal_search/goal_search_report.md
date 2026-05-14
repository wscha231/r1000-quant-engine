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
| main | `main_v2_position_aware_risk_proxy` | 37.05% | 0.00pp | -12.69% | 0.00pp | true | `target_pass_review` |
| concentrated | `concentrated_position_risk_proxy` | 61.96% | 0.00pp | -14.78% | 0.00pp | true | `target_pass_review` |

## Best Production-Compatible Candidates

| Portfolio | Candidate | CAGR | Gap | MaxDD | Gap | Target Pass | Action |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| main | `main_broker_execution_policy_replay` | 20.08% | 9.92pp | -31.66% | 16.66pp | false | `blocked_both` |
| concentrated | `concentrated_broker_execution_policy_replay` | 39.56% | 10.44pp | -28.69% | 10.69pp | false | `blocked_both` |

## Main Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `main_v2_position_aware_risk_proxy` | 37.05% | 0.00pp | -12.69% | 0.00pp | 1.777 | true | sidecar:outputs/position_aware_risk_replay/metrics.json#with_position_risk |
| `orchestrator_replay_main_proxy` | 35.17% | 0.00pp | -15.20% | 0.20pp | 1.898 | false | sidecar:outputs/orchestrator_replay/concentrated_balanced/metrics.json#metrics.main_proxy |
| `main_rebalance_interval_fixed_interval_I1` | 31.23% | 0.00pp | -17.23% | 2.23pp | 1.716 | false | latest_run_report:outputs/reports/rebalance_interval_comparison.csv |
| `main_latest_champion` | 30.99% | 0.00pp | -17.41% | 2.41pp | 1.707 | false | latest_run:outputs/backtest_metrics.json |
| `main_rebalance_interval_adaptive_I1` | 30.99% | 0.00pp | -17.41% | 2.41pp | 1.707 | false | latest_run_report:outputs/reports/rebalance_interval_comparison.csv |

## Concentrated Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `concentrated_position_risk_proxy` | 61.96% | 0.00pp | -14.78% | 0.00pp | 1.673 | true | sidecar:outputs/concentrated_position_risk_replay/metrics.json |
| `concentrated_grid_N2_conviction_curve_I1` | 58.65% | 0.00pp | -15.01% | 0.00pp | 1.606 | true | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `concentrated_grid_N2_winner_take_all_I1` | 58.65% | 0.00pp | -15.01% | 0.00pp | 1.606 | true | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `concentrated_grid_N2_score_power_I1` | 58.65% | 0.00pp | -15.01% | 0.00pp | 1.606 | true | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `concentrated_latest_champion` | 55.12% | 0.00pp | -14.00% | 0.00pp | 1.717 | true | latest_run:outputs/concentrated_backtest_metrics.json |

## Next Actions

- Main: research/proxy target-pass exists, but no production-compatible account replay passes; convert the rule to broker-ledger evidence before promotion.
- Concentrated: research/proxy target-pass exists, but broker-ledger conversion does not pass; do not promote until next-close replay supports it.
