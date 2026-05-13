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
| main | `main_v2_position_aware_risk_proxy` | 36.21% | 0.00pp | -12.78% | 0.00pp | true | `target_pass_review` |
| concentrated | `concentrated_position_risk_proxy` | 50.80% | 0.00pp | -15.81% | 0.00pp | true | `target_pass_review` |

## Best Production-Compatible Candidates

| Portfolio | Candidate | CAGR | Gap | MaxDD | Gap | Target Pass | Action |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| main | `main_broker_execution_policy_replay` | 20.31% | 9.69pp | -31.91% | 16.91pp | false | `blocked_both` |
| concentrated | `concentrated_broker_ledger_replay` | 37.35% | 12.65pp | -37.89% | 19.89pp | false | `blocked_both` |

## Main Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `main_v2_position_aware_risk_proxy` | 36.21% | 0.00pp | -12.78% | 0.00pp | 1.771 | true | sidecar:outputs/position_aware_risk_replay/metrics.json#with_position_risk |
| `orchestrator_replay_main_proxy` | 32.28% | 0.00pp | -13.98% | 0.00pp | 1.879 | true | sidecar:outputs/orchestrator_replay/concentrated_balanced/metrics.json#metrics.main_proxy |
| `main_rebalance_interval_fixed_interval_I1` | 28.36% | 1.64pp | -15.19% | 0.19pp | 1.685 | false | latest_run_report:outputs/reports/rebalance_interval_comparison.csv |
| `main_latest_champion` | 28.31% | 1.69pp | -16.24% | 1.24pp | 1.683 | false | latest_run:outputs/backtest_metrics.json |
| `main_rebalance_interval_adaptive_I1` | 28.31% | 1.69pp | -16.24% | 1.24pp | 1.683 | false | latest_run_report:outputs/reports/rebalance_interval_comparison.csv |

## Concentrated Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `concentrated_position_risk_proxy` | 50.80% | 0.00pp | -15.81% | 0.00pp | 1.913 | true | sidecar:outputs/concentrated_position_risk_replay/metrics.json |
| `concentrated_latest_champion` | 48.19% | 1.80pp | -16.36% | 0.00pp | 1.837 | false | latest_run:outputs/concentrated_backtest_metrics.json |
| `concentrated_grid_N4_score_power_I1` | 48.19% | 1.80pp | -16.36% | 0.00pp | 1.837 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `concentrated_grid_N4_conviction_curve_I1` | 47.81% | 2.19pp | -15.67% | 0.00pp | 1.823 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `concentrated_grid_N3_score_power_I1` | 47.14% | 2.86pp | -18.46% | 0.46pp | 1.680 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |

## Next Actions

- Main: research/proxy target-pass exists, but no production-compatible account replay passes; convert the rule to broker-ledger evidence before promotion.
- Concentrated: research/proxy target-pass exists, but broker-ledger conversion does not pass; do not promote until next-close replay supports it.
