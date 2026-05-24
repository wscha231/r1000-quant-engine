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
| main | `main_v2_position_aware_risk_proxy` | 35.72% | 0.00pp | -14.73% | 0.00pp | true | `target_pass_review` |
| concentrated | `concentrated_position_risk_proxy` | 50.52% | 0.00pp | -21.49% | 3.49pp | false | `needs_drawdown_reduction` |

## Best Production-Compatible Candidates

| Portfolio | Candidate | CAGR | Gap | MaxDD | Gap | Target Pass | Action |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| main | `main_broker_execution_policy_replay` | 21.22% | 8.78pp | -31.65% | 16.65pp | false | `blocked_both` |
| concentrated | `concentrated_broker_ledger_replay` | 36.61% | 13.39pp | -42.58% | 24.58pp | false | `blocked_both` |

## Main Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `main_v2_position_aware_risk_proxy` | 35.72% | 0.00pp | -14.73% | 0.00pp | 1.832 | true | sidecar:outputs/position_aware_risk_replay/metrics.json#with_position_risk |
| `orchestrator_replay_main_proxy` | 32.50% | 0.00pp | -15.84% | 0.84pp | 1.917 | false | sidecar:outputs/orchestrator_replay/concentrated_balanced/metrics.json#metrics.main_proxy |
| `main_latest_champion` | 28.45% | 1.55pp | -18.05% | 3.05pp | 1.714 | false | latest_run:outputs/backtest_metrics.json |
| `main_rebalance_interval_adaptive_I1` | 28.45% | 1.55pp | -18.05% | 3.05pp | 1.714 | false | latest_run_report:outputs/reports/rebalance_interval_comparison.csv |
| `main_rebalance_interval_fixed_interval_I1` | 28.90% | 1.10pp | -18.81% | 3.81pp | 1.733 | false | latest_run_report:outputs/reports/rebalance_interval_comparison.csv |

## Concentrated Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `concentrated_position_risk_proxy` | 50.52% | 0.00pp | -21.49% | 3.49pp | 1.866 | false | sidecar:outputs/concentrated_position_risk_replay/metrics.json |
| `concentrated_grid_N1_conviction_curve_I3` | 45.03% | 4.97pp | -15.74% | 0.00pp | 1.135 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `concentrated_grid_N1_winner_take_all_I3` | 45.03% | 4.97pp | -15.74% | 0.00pp | 1.135 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `concentrated_grid_N1_score_power_I3` | 45.03% | 4.97pp | -15.74% | 0.00pp | 1.135 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `concentrated_grid_N3_winner_take_all_I3` | 42.65% | 7.35pp | -13.81% | 0.00pp | 1.542 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |

## Next Actions

- Main: research/proxy target-pass exists, but no production-compatible account replay passes; convert the rule to broker-ledger evidence before promotion.
- Concentrated: production-compatible candidate exists but misses target; improve staged sizing, replacement, and distribution exits in broker-ledger replay.
