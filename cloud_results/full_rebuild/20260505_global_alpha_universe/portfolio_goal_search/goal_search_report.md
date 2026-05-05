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
| main | `main_v2_position_aware_risk_proxy` | 38.06% | 0.00pp | -7.99% | 0.00pp | true | `target_pass_review` |
| concentrated | `concentrated_position_risk_proxy` | 43.42% | 0.00pp | -15.58% | 0.00pp | true | `target_pass_review` |

## Main Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `main_v2_position_aware_risk_proxy` | 38.06% | 0.00pp | -7.99% | 0.00pp | 1.857 | true | sidecar:outputs/position_aware_risk_replay/metrics.json#with_position_risk |
| `orchestrator_replay_main_proxy` | 24.73% | 0.27pp | -24.12% | 4.12pp | 1.306 | false | sidecar:outputs/orchestrator_replay/concentrated_balanced/metrics.json#metrics.main_proxy |
| `experiment_E6_risk_sensing_on` | 18.47% | 6.53pp | -21.63% | 1.63pp | 1.119 | false | experiment:outputs/experiments/E6_risk_sensing_on/metrics.json |
| `main_v2_historical_replay` | 19.65% | 5.35pp | -24.25% | 4.25pp | 0.933 | false | sidecar:outputs/main_v2_backtest/metrics.json |
| `main_latest_champion` | 21.10% | 3.90pp | -25.90% | 5.90pp | 1.143 | false | latest_run:outputs/backtest_metrics.json |

## Concentrated Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `concentrated_position_risk_proxy` | 43.42% | 0.00pp | -15.58% | 0.00pp | 1.752 | true | sidecar:outputs/concentrated_position_risk_replay/metrics.json |
| `experiment_E4_concentrated_balanced` | 34.85% | 5.15pp | -22.94% | 0.94pp | 1.429 | false | experiment:outputs/experiments/E4_concentrated_balanced/metrics.json |
| `concentrated_latest_champion` | 34.99% | 5.01pp | -24.39% | 2.39pp | 1.350 | false | latest_run:outputs/concentrated_backtest_metrics.json |
| `concentrated_grid_N4_score_power_I1` | 34.99% | 5.01pp | -24.39% | 2.39pp | 1.350 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `concentrated_grid_N7_score_power_I1` | 32.44% | 7.56pp | -24.81% | 2.81pp | 1.368 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |

## Next Actions

- Main: target-pass candidate exists; require strict gate, stress windows, turnover, and human approval.
- Concentrated: target-pass candidate exists; validate caps, timing, turnover, and production promotion gates.
