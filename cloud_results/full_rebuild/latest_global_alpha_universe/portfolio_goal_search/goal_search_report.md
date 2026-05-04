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
| main | `experiment_E6_risk_sensing_on` | 18.47% | 6.53pp | -21.63% | 1.63pp | false | `blocked_both` |
| concentrated | `experiment_E4_concentrated_balanced` | 34.85% | 5.15pp | -22.94% | 0.94pp | false | `blocked_both` |

## Main Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `experiment_E6_risk_sensing_on` | 18.47% | 6.53pp | -21.63% | 1.63pp | 1.119 | false | experiment:outputs/experiments/E6_risk_sensing_on/metrics.json |
| `main_latest_champion` | 19.17% | 5.83pp | -24.91% | 4.91pp | 1.084 | false | latest_run:outputs/backtest_metrics.json |
| `main_rebalance_interval_adaptive_I1` | 19.17% | 5.83pp | -24.91% | 4.91pp | 1.084 | false | latest_run_report:outputs/reports/rebalance_interval_comparison.csv |
| `main_rebalance_interval_fixed_interval_I1` | 19.24% | 5.76pp | -25.01% | 5.01pp | 1.088 | false | latest_run_report:outputs/reports/rebalance_interval_comparison.csv |
| `experiment_E0_baseline_latest` | 21.40% | 3.60pp | -27.27% | 7.27pp | 1.183 | false | experiment:outputs/experiments/E0_baseline_latest/metrics.json |

## Concentrated Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `experiment_E4_concentrated_balanced` | 34.85% | 5.15pp | -22.94% | 0.94pp | 1.429 | false | experiment:outputs/experiments/E4_concentrated_balanced/metrics.json |
| `concentrated_latest_champion` | 34.94% | 5.06pp | -25.74% | 3.74pp | 1.376 | false | latest_run:outputs/concentrated_backtest_metrics.json |
| `concentrated_grid_N5_score_power_I1` | 34.94% | 5.06pp | -25.74% | 3.74pp | 1.376 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `concentrated_grid_N4_score_power_I1` | 32.66% | 7.34pp | -26.81% | 4.81pp | 1.259 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `concentrated_grid_N7_score_power_I1` | 29.97% | 10.03pp | -25.23% | 3.23pp | 1.293 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |

## Next Actions

- Main: run true Main v2 historical challenger; current artifacts do not meet both CAGR and MaxDD targets.
- Concentrated: run full concentrated grid replay from concentrated_strategy_monthly and reject proxy-only evidence.
