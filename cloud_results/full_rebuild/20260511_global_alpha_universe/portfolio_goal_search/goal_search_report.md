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
| main | `main_v2_position_aware_risk_proxy` | 36.40% | 0.00pp | -12.81% | 0.00pp | true | `target_pass_review` |
| concentrated | `concentrated_position_risk_proxy` | 49.31% | 0.69pp | -17.87% | 0.00pp | false | `needs_alpha_boost` |

## Best Production-Compatible Candidates

| Portfolio | Candidate | CAGR | Gap | MaxDD | Gap | Target Pass | Action |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| main | `main_broker_ledger_replay` | 21.09% | 8.91pp | -31.69% | 16.69pp | false | `blocked_both` |
| concentrated | `concentrated_broker_ledger_replay` | 31.31% | 18.69pp | -39.23% | 21.23pp | false | `blocked_both` |

## Main Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `main_v2_position_aware_risk_proxy` | 36.40% | 0.00pp | -12.81% | 0.00pp | 1.735 | true | sidecar:outputs/position_aware_risk_replay/metrics.json#with_position_risk |
| `orchestrator_replay_main_proxy` | 33.76% | 0.00pp | -13.33% | 0.00pp | 1.982 | true | sidecar:outputs/orchestrator_replay/concentrated_balanced/metrics.json#metrics.main_proxy |
| `main_rebalance_interval_fixed_interval_I1` | 29.91% | 0.09pp | -15.19% | 0.19pp | 1.792 | false | latest_run_report:outputs/reports/rebalance_interval_comparison.csv |
| `main_latest_champion` | 29.66% | 0.34pp | -15.66% | 0.66pp | 1.778 | false | latest_run:outputs/backtest_metrics.json |
| `main_rebalance_interval_adaptive_I1` | 29.66% | 0.34pp | -15.66% | 0.66pp | 1.778 | false | latest_run_report:outputs/reports/rebalance_interval_comparison.csv |

## Concentrated Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `concentrated_position_risk_proxy` | 49.31% | 0.69pp | -17.87% | 0.00pp | 1.621 | false | sidecar:outputs/concentrated_position_risk_replay/metrics.json |
| `concentrated_grid_N3_score_power_I1` | 45.93% | 4.07pp | -18.21% | 0.21pp | 1.682 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `concentrated_grid_N2_winner_take_all_I1` | 46.32% | 3.68pp | -19.95% | 1.95pp | 1.545 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `concentrated_grid_N2_score_power_I1` | 46.32% | 3.68pp | -19.95% | 1.95pp | 1.545 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `concentrated_grid_N2_conviction_curve_I1` | 46.32% | 3.68pp | -19.95% | 1.95pp | 1.545 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |

## Next Actions

- Main: research/proxy target-pass exists, but no production-compatible account replay passes; convert the rule to broker-ledger evidence before promotion.
- Concentrated: production-compatible candidate exists but misses target; improve staged sizing, replacement, and distribution exits in broker-ledger replay.
