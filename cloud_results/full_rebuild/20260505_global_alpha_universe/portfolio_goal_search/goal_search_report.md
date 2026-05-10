# Portfolio Goal Search

Artifact-only ranking against explicit portfolio targets. Production defaults are unchanged.

## Targets

| Portfolio | CAGR Target | MaxDD Target |
| --- | ---: | ---: |
| main | 25.00% | -20.00% |
| concentrated | 40.00% | -22.00% |

## Best Candidates

| Portfolio | Candidate | CAGR | Gap | MaxDD | Gap | Target Pass | Action |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| main | `main_v2_position_aware_risk_proxy` | 35.95% | 0.00pp | -7.95% | 0.00pp | true | `target_pass_review` |
| concentrated | `concentrated_position_risk_proxy` | 45.16% | 0.00pp | -19.87% | 0.00pp | true | `target_pass_review` |

## Main Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `main_v2_position_aware_risk_proxy` | 35.95% | 0.00pp | -7.95% | 0.00pp | 1.771 | true | sidecar:outputs/position_aware_risk_replay/metrics.json#with_position_risk |
| `orchestrator_replay_main_proxy` | 34.42% | 0.00pp | -16.61% | 0.00pp | 1.847 | true | sidecar:outputs/orchestrator_replay/concentrated_balanced/metrics.json#metrics.main_proxy |
| `main_rebalance_interval_fixed_interval_I1` | 30.44% | 0.00pp | -19.05% | 0.00pp | 1.676 | true | latest_run_report:outputs/reports/rebalance_interval_comparison.csv |
| `main_latest_champion` | 30.29% | 0.00pp | -18.90% | 0.00pp | 1.659 | true | latest_run:outputs/backtest_metrics.json |
| `main_rebalance_interval_adaptive_I1` | 30.29% | 0.00pp | -18.90% | 0.00pp | 1.659 | true | latest_run_report:outputs/reports/rebalance_interval_comparison.csv |

## Concentrated Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `concentrated_position_risk_proxy` | 45.16% | 0.00pp | -19.87% | 0.00pp | 1.653 | true | sidecar:outputs/concentrated_position_risk_replay/metrics.json |
| `concentrated_latest_champion` | 45.16% | 0.00pp | -19.87% | 0.00pp | 1.653 | true | latest_run:outputs/concentrated_backtest_metrics.json |
| `concentrated_grid_N3_score_power_I1` | 45.16% | 0.00pp | -19.87% | 0.00pp | 1.653 | true | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `concentrated_grid_N4_score_power_I1` | 43.02% | 0.00pp | -17.91% | 0.00pp | 1.749 | true | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `concentrated_grid_N3_conviction_curve_I1` | 43.32% | 0.00pp | -20.36% | 0.00pp | 1.606 | true | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |

## Next Actions

- Main: target-pass candidate exists; require strict gate, stress windows, turnover, and human approval.
- Concentrated: target-pass candidate exists; validate caps, timing, turnover, and production promotion gates.
