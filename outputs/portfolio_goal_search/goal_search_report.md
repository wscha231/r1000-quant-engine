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
| concentrated | `concentrated_position_risk_proxy` | 50.38% | 0.00pp | -17.82% | 0.00pp | true | `target_pass_review` |

## Main Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `main_v2_position_aware_risk_proxy` | 36.10% | 0.00pp | -12.63% | 0.00pp | 1.726 | true | sidecar:cloud_results/full_rebuild/latest_global_alpha_universe/position_aware_risk_replay/metrics.json#with_position_risk |
| `orchestrator_replay_main_proxy` | 32.16% | 0.00pp | -13.60% | 0.00pp | 1.813 | true | sidecar:cloud_results/full_rebuild/latest_global_alpha_universe/orchestrator_replay/concentrated_balanced/metrics.json#metrics.main_proxy |
| `main_latest_champion` | 28.12% | 1.88pp | -15.92% | 0.92pp | 1.620 | false | latest_run:cloud_results/full_rebuild/latest_global_alpha_universe/backtest_metrics.json |
| `lifecycle_review_overlay_main` | 23.10% | 6.90pp | -21.61% | 6.61pp | 1.155 | false | sidecar:cloud_results/full_rebuild/latest_global_alpha_universe/lifecycle_review_overlay_main/metrics.json |
| `experiment_E6_risk_sensing_on` | 18.47% | 11.53pp | -21.63% | 6.63pp | 1.119 | false | experiment:outputs/experiments/E6_risk_sensing_on/metrics.json |

## Concentrated Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `concentrated_position_risk_proxy` | 50.38% | 0.00pp | -17.82% | 0.00pp | 1.825 | true | sidecar:cloud_results/full_rebuild/latest_global_alpha_universe/concentrated_position_risk_replay/metrics.json |
| `concentrated_latest_champion` | 47.71% | 2.29pp | -19.72% | 1.72pp | 1.750 | false | latest_run:cloud_results/full_rebuild/latest_global_alpha_universe/concentrated_backtest_metrics.json |
| `concentrated_grid_N3_score_power_I1` | 47.71% | 2.29pp | -19.72% | 1.72pp | 1.750 | false | latest_run_report:cloud_results/full_rebuild/latest_global_alpha_universe/reports/concentrated_strategy_comparison.csv |
| `concentrated_grid_N3_winner_take_all_I1` | 47.16% | 2.84pp | -20.39% | 2.39pp | 1.710 | false | latest_run_report:cloud_results/full_rebuild/latest_global_alpha_universe/reports/concentrated_strategy_comparison.csv |
| `concentrated_grid_N4_conviction_curve_I1` | 44.29% | 5.71pp | -15.38% | 0.00pp | 1.748 | false | latest_run_report:cloud_results/full_rebuild/latest_global_alpha_universe/reports/concentrated_strategy_comparison.csv |

## Next Actions

- Main: target-pass candidate exists; require strict gate, stress windows, turnover, and human approval.
- Concentrated: target-pass candidate exists; validate caps, timing, turnover, and production promotion gates.
