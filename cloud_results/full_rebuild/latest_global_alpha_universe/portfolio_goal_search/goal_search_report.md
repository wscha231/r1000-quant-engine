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
| main | `main_v2_position_aware_risk_proxy` | 36.37% | 0.00pp | -12.74% | 0.00pp | true | `target_pass_review` |
| concentrated | `concentrated_position_risk_proxy` | 47.20% | 0.00pp | -20.10% | 0.00pp | true | `target_pass_review` |

## Main Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `main_v2_position_aware_risk_proxy` | 36.37% | 0.00pp | -12.74% | 0.00pp | 1.786 | true | sidecar:outputs/position_aware_risk_replay/metrics.json#with_position_risk |
| `orchestrator_replay_main_proxy` | 33.55% | 0.00pp | -13.90% | 0.00pp | 1.913 | true | sidecar:outputs/orchestrator_replay/concentrated_balanced/metrics.json#metrics.main_proxy |
| `main_rebalance_interval_fixed_interval_I1` | 29.79% | 0.00pp | -15.81% | 0.00pp | 1.731 | true | latest_run_report:outputs/reports/rebalance_interval_comparison.csv |
| `main_latest_champion` | 29.42% | 0.00pp | -16.25% | 0.00pp | 1.714 | true | latest_run:outputs/backtest_metrics.json |
| `main_rebalance_interval_adaptive_I1` | 29.42% | 0.00pp | -16.25% | 0.00pp | 1.714 | true | latest_run_report:outputs/reports/rebalance_interval_comparison.csv |

## Concentrated Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `concentrated_position_risk_proxy` | 47.20% | 0.00pp | -20.10% | 0.00pp | 1.676 | true | sidecar:outputs/concentrated_position_risk_replay/metrics.json |
| `concentrated_latest_champion` | 47.20% | 0.00pp | -20.10% | 0.00pp | 1.676 | true | latest_run:outputs/concentrated_backtest_metrics.json |
| `concentrated_grid_N3_score_power_I1` | 47.20% | 0.00pp | -20.10% | 0.00pp | 1.676 | true | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `concentrated_grid_N3_winner_take_all_I1` | 46.55% | 0.00pp | -19.31% | 0.00pp | 1.653 | true | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `concentrated_grid_N3_conviction_curve_I1` | 45.94% | 0.00pp | -19.50% | 0.00pp | 1.661 | true | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |

## Next Actions

- Main: target-pass candidate exists; require strict gate, stress windows, turnover, and human approval.
- Concentrated: target-pass candidate exists; validate caps, timing, turnover, and production promotion gates.
