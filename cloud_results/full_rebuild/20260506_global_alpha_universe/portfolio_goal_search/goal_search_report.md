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
| main | `main_v2_position_aware_risk_proxy` | 35.90% | 0.00pp | -8.74% | 0.00pp | true | `target_pass_review` |
| concentrated | `experiment_E4_concentrated_balanced` | 34.85% | 5.15pp | -22.94% | 0.94pp | false | `blocked_both` |

## Main Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `main_v2_position_aware_risk_proxy` | 35.90% | 0.00pp | -8.74% | 0.00pp | 1.767 | true | sidecar:outputs/position_aware_risk_replay/metrics.json#with_position_risk |
| `orchestrator_replay_main_proxy` | 33.91% | 0.00pp | -14.05% | 0.00pp | 1.881 | true | sidecar:outputs/orchestrator_replay/concentrated_balanced/metrics.json#metrics.main_proxy |
| `main_rebalance_interval_fixed_interval_I1` | 30.12% | 0.00pp | -16.32% | 0.00pp | 1.707 | true | latest_run_report:outputs/reports/rebalance_interval_comparison.csv |
| `main_latest_champion` | 29.90% | 0.00pp | -16.42% | 0.00pp | 1.693 | true | latest_run:outputs/backtest_metrics.json |
| `main_rebalance_interval_adaptive_I1` | 29.90% | 0.00pp | -16.42% | 0.00pp | 1.693 | true | latest_run_report:outputs/reports/rebalance_interval_comparison.csv |

## Concentrated Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `experiment_E4_concentrated_balanced` | 34.85% | 5.15pp | -22.94% | 0.94pp | 1.429 | false | experiment:outputs/experiments/E4_concentrated_balanced/metrics.json |
| `orchestrator_replay_concentrated_leg` | 26.01% | 13.99pp | -27.63% | 5.63pp | 1.311 | false | sidecar:outputs/orchestrator_replay/concentrated_balanced/metrics.json#metrics.concentrated |
| `concentrated_policy_replay` | 12.91% | 27.09pp | -48.72% | 26.72pp | 0.550 | false | sidecar:outputs/concentrated_policy_replay/metrics.json |
| `monster_lifecycle_review_concentrated` | 5.24% | 34.76pp | -43.68% | 21.68pp | 0.351 | false | sidecar:outputs/monster_lifecycle_review_concentrated/metrics.json |
| `monster_lifecycle_replay` | 1.67% | 38.33pp | -40.80% | 18.80pp | 0.185 | false | sidecar:outputs/monster_lifecycle_replay/metrics.json |

## Next Actions

- Main: target-pass candidate exists; require strict gate, stress windows, turnover, and human approval.
- Concentrated: run full concentrated grid replay from concentrated_strategy_monthly and reject proxy-only evidence.
