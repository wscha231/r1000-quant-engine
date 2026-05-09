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
| main | `main_v2_position_aware_risk_proxy` | 35.62% | 0.00pp | -12.72% | 0.00pp | true | `target_pass_review` |
| concentrated | `concentrated_position_risk_proxy` | 48.75% | 1.25pp | -11.85% | 0.00pp | false | `needs_alpha_boost` |

## Best Production-Compatible Candidates

| Portfolio | Candidate | CAGR | Gap | MaxDD | Gap | Target Pass | Action |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| main | `main_broker_execution_policy_replay` | 20.46% | 9.54pp | -32.03% | 17.03pp | false | `blocked_both` |
| concentrated | `concentrated_broker_ledger_replay` | 36.42% | 13.58pp | -37.38% | 19.38pp | false | `blocked_both` |

## Main Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `main_v2_position_aware_risk_proxy` | 35.62% | 0.00pp | -12.72% | 0.00pp | 1.736 | true | sidecar:outputs/position_aware_risk_replay/metrics.json#with_position_risk |
| `orchestrator_replay_main_proxy` | 31.86% | 0.00pp | -14.52% | 0.00pp | 1.848 | true | sidecar:outputs/orchestrator_replay/concentrated_balanced/metrics.json#metrics.main_proxy |
| `main_rebalance_interval_fixed_interval_I1` | 28.50% | 1.50pp | -16.62% | 1.62pp | 1.683 | false | latest_run_report:outputs/reports/rebalance_interval_comparison.csv |
| `main_latest_champion` | 27.86% | 2.14pp | -16.84% | 1.84pp | 1.650 | false | latest_run:outputs/backtest_metrics.json |
| `main_rebalance_interval_adaptive_I1` | 27.86% | 2.14pp | -16.84% | 1.84pp | 1.650 | false | latest_run_report:outputs/reports/rebalance_interval_comparison.csv |

## Concentrated Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `concentrated_position_risk_proxy` | 48.75% | 1.25pp | -11.85% | 0.00pp | 1.892 | false | sidecar:outputs/concentrated_position_risk_replay/metrics.json |
| `concentrated_grid_N4_score_power_I1` | 46.14% | 3.86pp | -12.87% | 0.00pp | 1.812 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `orchestrator_replay_concentrated_leg` | 45.90% | 4.10pp | -13.46% | 0.00pp | 1.904 | false | sidecar:outputs/orchestrator_replay/concentrated_balanced/metrics.json#metrics.concentrated |
| `concentrated_latest_champion` | 45.90% | 4.10pp | -13.46% | 0.00pp | 1.904 | false | latest_run:outputs/concentrated_backtest_metrics.json |
| `concentrated_grid_N5_score_power_I1` | 45.90% | 4.10pp | -13.46% | 0.00pp | 1.904 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |

## Next Actions

- Main: research/proxy target-pass exists, but no production-compatible account replay passes; convert the rule to broker-ledger evidence before promotion.
- Concentrated: production-compatible candidate exists but misses target; improve staged sizing, replacement, and distribution exits in broker-ledger replay.
