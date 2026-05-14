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
| main | `main_v2_position_aware_risk_proxy` | 36.13% | 0.00pp | -12.68% | 0.00pp | true | `target_pass_review` |
| concentrated | `concentrated_position_risk_proxy` | 50.59% | 0.00pp | -17.99% | 0.00pp | true | `target_pass_review` |

## Best Production-Compatible Candidates

| Portfolio | Candidate | CAGR | Gap | MaxDD | Gap | Target Pass | Action |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| main | `main_broker_ledger_replay` | 23.10% | 6.90pp | -29.98% | 14.98pp | false | `blocked_both` |
| concentrated | `concentrated_broker_ledger_replay` | 33.00% | 17.00pp | -41.82% | 23.82pp | false | `blocked_both` |

## Main Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `main_v2_position_aware_risk_proxy` | 36.13% | 0.00pp | -12.68% | 0.00pp | 1.764 | true | sidecar:outputs/position_aware_risk_replay/metrics.json#with_position_risk |
| `orchestrator_replay_main_proxy` | 33.91% | 0.00pp | -14.36% | 0.00pp | 1.907 | true | sidecar:outputs/orchestrator_replay/concentrated_balanced/metrics.json#metrics.main_proxy |
| `main_rebalance_interval_fixed_interval_I1` | 29.79% | 0.21pp | -16.07% | 1.07pp | 1.714 | false | latest_run_report:outputs/reports/rebalance_interval_comparison.csv |
| `main_latest_champion` | 29.79% | 0.21pp | -16.65% | 1.65pp | 1.711 | false | latest_run:outputs/backtest_metrics.json |
| `main_rebalance_interval_adaptive_I1` | 29.79% | 0.21pp | -16.65% | 1.65pp | 1.711 | false | latest_run_report:outputs/reports/rebalance_interval_comparison.csv |

## Concentrated Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `concentrated_position_risk_proxy` | 50.59% | 0.00pp | -17.99% | 0.00pp | 1.819 | true | sidecar:outputs/concentrated_position_risk_replay/metrics.json |
| `concentrated_grid_N4_score_power_I1` | 46.58% | 3.42pp | -18.32% | 0.32pp | 1.804 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `concentrated_grid_N3_conviction_curve_I1` | 47.71% | 2.29pp | -19.97% | 1.97pp | 1.739 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `concentrated_grid_N4_conviction_curve_I1` | 46.13% | 3.87pp | -18.40% | 0.40pp | 1.823 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `concentrated_latest_champion` | 48.62% | 1.38pp | -21.05% | 3.05pp | 1.734 | false | latest_run:outputs/concentrated_backtest_metrics.json |

## Next Actions

- Main: research/proxy target-pass exists, but no production-compatible account replay passes; convert the rule to broker-ledger evidence before promotion.
- Concentrated: research/proxy target-pass exists, but broker-ledger conversion does not pass; do not promote until next-close replay supports it.
