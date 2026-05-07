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
| main | `main_v2_position_aware_risk_proxy` | 37.34% | 0.00pp | -12.73% | 0.00pp | true | `target_pass_review` |
| concentrated | `experiment_E4_concentrated_balanced` | 34.85% | 5.15pp | -22.94% | 0.94pp | false | `blocked_both` |

## Main Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `main_v2_position_aware_risk_proxy` | 37.34% | 0.00pp | -12.73% | 0.00pp | 1.799 | true | sidecar:outputs/position_aware_risk_replay/metrics.json#with_position_risk |
| `orchestrator_replay_main_proxy` | 32.30% | 0.00pp | -15.89% | 0.00pp | 1.770 | true | sidecar:outputs/orchestrator_replay/concentrated_balanced/metrics.json#metrics.main_proxy |
| `main_rebalance_interval_fixed_interval_I1` | 28.35% | 0.00pp | -18.17% | 0.00pp | 1.587 | true | latest_run_report:outputs/reports/rebalance_interval_comparison.csv |
| `main_latest_champion` | 28.16% | 0.00pp | -18.19% | 0.00pp | 1.577 | true | latest_run:outputs/backtest_metrics.json |
| `main_rebalance_interval_adaptive_I1` | 28.16% | 0.00pp | -18.19% | 0.00pp | 1.577 | true | latest_run_report:outputs/reports/rebalance_interval_comparison.csv |

## Concentrated Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `experiment_E4_concentrated_balanced` | 34.85% | 5.15pp | -22.94% | 0.94pp | 1.429 | false | experiment:outputs/experiments/E4_concentrated_balanced/metrics.json |
| `orchestrator_replay_concentrated_leg` | 31.01% | 8.99pp | -22.67% | 0.67pp | 1.550 | false | sidecar:outputs/orchestrator_replay/concentrated_balanced/metrics.json#metrics.concentrated |
| `monster_lifecycle_review_concentrated` | 10.46% | 29.54pp | -39.37% | 17.37pp | 0.542 | false | sidecar:outputs/monster_lifecycle_review_concentrated/metrics.json |
| `concentrated_policy_replay` | 15.56% | 24.44pp | -48.77% | 26.77pp | 0.613 | false | sidecar:outputs/concentrated_policy_replay/metrics.json |
| `monster_lifecycle_replay` | 8.36% | 31.64pp | -44.52% | 22.52pp | 0.462 | false | sidecar:outputs/monster_lifecycle_replay/metrics.json |

## Next Actions

- Main: target-pass candidate exists; require strict gate, stress windows, turnover, and human approval.
- Concentrated: run full concentrated grid replay from concentrated_strategy_monthly and reject proxy-only evidence.
