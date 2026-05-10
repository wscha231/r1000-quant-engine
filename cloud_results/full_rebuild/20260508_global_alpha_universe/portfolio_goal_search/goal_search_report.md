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
| main | `main_v2_position_aware_risk_proxy` | 36.10% | 0.00pp | -12.63% | 0.00pp | true | `target_pass_review` |
| concentrated | `concentrated_position_risk_weekly_validation` | 168778917831421347233792.00% | 0.00pp | 0.00% | 0.00pp | true | `target_pass_review` |

## Main Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `main_v2_position_aware_risk_proxy` | 36.10% | 0.00pp | -12.63% | 0.00pp | 1.726 | true | sidecar:outputs/position_aware_risk_replay/metrics.json#with_position_risk |
| `orchestrator_replay_main_proxy` | 32.16% | 0.00pp | -13.60% | 0.00pp | 1.813 | true | sidecar:outputs/orchestrator_replay/concentrated_balanced/metrics.json#metrics.main_proxy |
| `main_rebalance_interval_fixed_interval_I1` | 28.48% | 1.52pp | -14.92% | 0.00pp | 1.635 | false | latest_run_report:outputs/reports/rebalance_interval_comparison.csv |
| `main_latest_champion` | 28.12% | 1.88pp | -15.92% | 0.92pp | 1.620 | false | latest_run:outputs/backtest_metrics.json |
| `main_rebalance_interval_adaptive_I1` | 28.12% | 1.88pp | -15.92% | 0.92pp | 1.620 | false | latest_run_report:outputs/reports/rebalance_interval_comparison.csv |

## Concentrated Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `concentrated_position_risk_weekly_validation` | 168778917831421347233792.00% | 0.00pp | 0.00% | 0.00pp | 31.177 | true | sidecar:outputs/position_risk_weekly_validation/concentrated/metrics.json |
| `concentrated_position_risk_proxy` | 50.38% | 0.00pp | -17.82% | 0.00pp | 1.825 | true | sidecar:outputs/concentrated_position_risk_replay/metrics.json |
| `concentrated_latest_champion` | 47.71% | 2.29pp | -19.72% | 1.72pp | 1.750 | false | latest_run:outputs/concentrated_backtest_metrics.json |
| `concentrated_grid_N3_score_power_I1` | 47.71% | 2.29pp | -19.72% | 1.72pp | 1.750 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `concentrated_grid_N3_winner_take_all_I1` | 47.16% | 2.84pp | -20.39% | 2.39pp | 1.710 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |

## Next Actions

- Main: target-pass candidate exists; require strict gate, stress windows, turnover, and human approval.
- Concentrated: target-pass candidate exists; validate caps, timing, turnover, and production promotion gates.
