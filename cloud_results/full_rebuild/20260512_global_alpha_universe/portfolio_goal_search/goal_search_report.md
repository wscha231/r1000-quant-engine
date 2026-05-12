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
| main | `main_v2_position_aware_risk_proxy` | 36.06% | 0.00pp | -12.73% | 0.00pp | true | `target_pass_review` |
| concentrated | `concentrated_position_risk_proxy` | 49.31% | 0.69pp | -17.34% | 0.00pp | false | `needs_alpha_boost` |

## Best Production-Compatible Candidates

| Portfolio | Candidate | CAGR | Gap | MaxDD | Gap | Target Pass | Action |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| main | `main_broker_ledger_replay` | 21.84% | 8.16pp | -28.62% | 13.62pp | false | `blocked_both` |
| concentrated | `concentrated_broker_ledger_replay` | 35.76% | 14.24pp | -36.74% | 18.74pp | false | `blocked_both` |

## Main Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `main_v2_position_aware_risk_proxy` | 36.06% | 0.00pp | -12.73% | 0.00pp | 1.751 | true | sidecar:outputs/position_aware_risk_replay/metrics.json#with_position_risk |
| `orchestrator_replay_main_proxy` | 32.78% | 0.00pp | -11.41% | 0.00pp | 1.939 | true | sidecar:outputs/orchestrator_replay/concentrated_balanced/metrics.json#metrics.main_proxy |
| `main_rebalance_interval_fixed_interval_I1` | 29.18% | 0.82pp | -13.49% | 0.00pp | 1.753 | false | latest_run_report:outputs/reports/rebalance_interval_comparison.csv |
| `main_latest_champion` | 28.91% | 1.09pp | -13.56% | 0.00pp | 1.744 | false | latest_run:outputs/backtest_metrics.json |
| `main_rebalance_interval_adaptive_I1` | 28.91% | 1.09pp | -13.56% | 0.00pp | 1.744 | false | latest_run_report:outputs/reports/rebalance_interval_comparison.csv |

## Concentrated Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `concentrated_position_risk_proxy` | 49.31% | 0.69pp | -17.34% | 0.00pp | 1.820 | false | sidecar:outputs/concentrated_position_risk_replay/metrics.json |
| `concentrated_latest_champion` | 46.68% | 3.32pp | -18.57% | 0.57pp | 1.745 | false | latest_run:outputs/concentrated_backtest_metrics.json |
| `concentrated_grid_N4_score_power_I1` | 46.68% | 3.32pp | -18.57% | 0.57pp | 1.745 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `concentrated_grid_N4_conviction_curve_I1` | 45.93% | 4.07pp | -17.94% | 0.00pp | 1.781 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `concentrated_grid_N2_winner_take_all_I1` | 47.18% | 2.82pp | -21.69% | 3.69pp | 1.552 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |

## Next Actions

- Main: research/proxy target-pass exists, but no production-compatible account replay passes; convert the rule to broker-ledger evidence before promotion.
- Concentrated: production-compatible candidate exists but misses target; improve staged sizing, replacement, and distribution exits in broker-ledger replay.
