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
| main | `main_v2_position_aware_risk_proxy` | 34.35% | 0.00pp | -8.38% | 0.00pp | true | `target_pass_review` |
| concentrated | `experiment_E4_concentrated_balanced` | 34.85% | 5.15pp | -22.94% | 0.94pp | false | `blocked_both` |

## Main Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `main_v2_position_aware_risk_proxy` | 34.35% | 0.00pp | -8.38% | 0.00pp | 1.661 | true | sidecar:outputs/position_aware_risk_replay/metrics.json#with_position_risk |
| `orchestrator_replay_main_proxy` | 34.62% | 0.00pp | -14.77% | 0.00pp | 1.867 | true | sidecar:outputs/orchestrator_replay/concentrated_balanced/metrics.json#metrics.main_proxy |
| `main_rebalance_interval_fixed_interval_I1` | 30.47% | 0.00pp | -16.73% | 0.00pp | 1.669 | true | latest_run_report:outputs/reports/rebalance_interval_comparison.csv |
| `main_latest_champion` | 30.46% | 0.00pp | -16.85% | 0.00pp | 1.678 | true | latest_run:outputs/backtest_metrics.json |
| `main_rebalance_interval_adaptive_I1` | 30.46% | 0.00pp | -16.85% | 0.00pp | 1.678 | true | latest_run_report:outputs/reports/rebalance_interval_comparison.csv |

## Concentrated Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `experiment_E4_concentrated_balanced` | 34.85% | 5.15pp | -22.94% | 0.94pp | 1.429 | false | experiment:outputs/experiments/E4_concentrated_balanced/metrics.json |
| `orchestrator_replay_concentrated_leg` | 29.97% | 10.03pp | -25.62% | 3.62pp | 1.531 | false | sidecar:outputs/orchestrator_replay/concentrated_balanced/metrics.json#metrics.concentrated |
| `concentrated_policy_replay` | 11.82% | 28.18pp | -48.76% | 26.76pp | 0.519 | false | sidecar:outputs/concentrated_policy_replay/metrics.json |
| `monster_lifecycle_replay` | 3.13% | 36.87pp | -40.80% | 18.80pp | 0.256 | false | sidecar:outputs/monster_lifecycle_replay/metrics.json |
| `monster_lifecycle_review_concentrated` | 4.20% | 35.80pp | -43.68% | 21.68pp | 0.302 | false | sidecar:outputs/monster_lifecycle_review_concentrated/metrics.json |

## Next Actions

- Main: target-pass candidate exists; require strict gate, stress windows, turnover, and human approval.
- Concentrated: run full concentrated grid replay from concentrated_strategy_monthly and reject proxy-only evidence.
