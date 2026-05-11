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
| main | `main_v2_position_aware_risk_proxy` | 34.04% | 0.00pp | -12.51% | 0.00pp | true | `target_pass_review` |
| concentrated | `concentrated_position_risk_proxy` | 42.45% | 7.55pp | -15.07% | 0.00pp | false | `needs_alpha_boost` |

## Best Production-Compatible Candidates

| Portfolio | Candidate | CAGR | Gap | MaxDD | Gap | Target Pass | Action |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| main | `main_broker_execution_policy_replay` | 19.07% | 10.93pp | -33.05% | 18.05pp | false | `blocked_both` |
| concentrated | `concentrated_broker_ledger_replay` | 27.07% | 22.93pp | -39.18% | 21.18pp | false | `blocked_both` |

## Main Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `main_v2_position_aware_risk_proxy` | 34.04% | 0.00pp | -12.51% | 0.00pp | 1.722 | true | sidecar:outputs/position_aware_risk_replay/metrics.json#with_position_risk |
| `orchestrator_replay_main_proxy` | 31.29% | 0.00pp | -15.69% | 0.69pp | 1.839 | false | sidecar:outputs/orchestrator_replay/concentrated_balanced/metrics.json#metrics.main_proxy |
| `main_sleeve_cap_policy_sleeve_cap_policy_I1` | 26.36% | 3.64pp | -16.19% | 1.19pp | 1.659 | false | latest_run_report:outputs/reports/sleeve_cap_policy_comparison.csv |
| `main_rebalance_interval_fixed_interval_I1` | 27.41% | 2.59pp | -17.90% | 2.90pp | 1.644 | false | latest_run_report:outputs/reports/rebalance_interval_comparison.csv |
| `main_latest_champion` | 27.32% | 2.68pp | -17.87% | 2.87pp | 1.640 | false | latest_run:outputs/backtest_metrics.json |

## Concentrated Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `concentrated_position_risk_proxy` | 42.45% | 7.55pp | -15.07% | 0.00pp | 1.781 | false | sidecar:outputs/concentrated_position_risk_replay/metrics.json |
| `concentrated_grid_N5_winner_take_all_I1` | 39.99% | 10.01pp | -17.29% | 0.00pp | 1.699 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `orchestrator_replay_concentrated_leg` | 39.86% | 10.14pp | -16.58% | 0.00pp | 1.705 | false | sidecar:outputs/orchestrator_replay/concentrated_balanced/metrics.json#metrics.concentrated |
| `concentrated_latest_champion` | 39.86% | 10.14pp | -16.58% | 0.00pp | 1.705 | false | latest_run:outputs/concentrated_backtest_metrics.json |
| `concentrated_grid_N5_score_power_I1` | 39.86% | 10.14pp | -16.58% | 0.00pp | 1.705 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |

## Next Actions

- Main: research/proxy target-pass exists, but no production-compatible account replay passes; convert the rule to broker-ledger evidence before promotion.
- Concentrated: production-compatible candidate exists but misses target; improve staged sizing, replacement, and distribution exits in broker-ledger replay.
