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
| main | `main_v2_position_aware_risk_proxy` | 36.47% | 0.00pp | -12.73% | 0.00pp | true | `target_pass_review` |
| concentrated | `concentrated_position_risk_proxy` | 51.62% | 0.00pp | -15.41% | 0.00pp | true | `target_pass_review` |

## Best Production-Compatible Candidates

| Portfolio | Candidate | CAGR | Gap | MaxDD | Gap | Target Pass | Action |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| main | `main_broker_crisis_reentry_fast_reentry` | 18.55% | 11.45pp | -30.03% | 15.03pp | false | `blocked_both` |
| concentrated | `concentrated_broker_ledger_replay` | 36.41% | 13.59pp | -38.45% | 20.45pp | false | `blocked_both` |

## Main Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `main_v2_position_aware_risk_proxy` | 36.47% | 0.00pp | -12.73% | 0.00pp | 1.773 | true | sidecar:outputs/position_aware_risk_replay/metrics.json#with_position_risk |
| `orchestrator_replay_main_proxy` | 33.26% | 0.00pp | -15.19% | 0.19pp | 1.926 | false | sidecar:outputs/orchestrator_replay/concentrated_balanced/metrics.json#metrics.main_proxy |
| `main_rebalance_interval_fixed_interval_I1` | 29.28% | 0.72pp | -17.20% | 2.20pp | 1.727 | false | latest_run_report:outputs/reports/rebalance_interval_comparison.csv |
| `main_latest_champion` | 29.19% | 0.81pp | -17.46% | 2.46pp | 1.725 | false | latest_run:outputs/backtest_metrics.json |
| `main_rebalance_interval_adaptive_I1` | 29.19% | 0.81pp | -17.46% | 2.46pp | 1.725 | false | latest_run_report:outputs/reports/rebalance_interval_comparison.csv |

## Concentrated Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `concentrated_position_risk_proxy` | 51.62% | 0.00pp | -15.41% | 0.00pp | 1.813 | true | sidecar:outputs/concentrated_position_risk_replay/metrics.json |
| `concentrated_latest_champion` | 48.94% | 1.06pp | -16.67% | 0.00pp | 1.741 | false | latest_run:outputs/concentrated_backtest_metrics.json |
| `concentrated_grid_N3_score_power_I1` | 48.94% | 1.06pp | -16.67% | 0.00pp | 1.741 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `concentrated_grid_N2_conviction_curve_I1` | 50.63% | 0.00pp | -20.57% | 2.57pp | 1.581 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `concentrated_grid_N2_winner_take_all_I1` | 50.63% | 0.00pp | -20.57% | 2.57pp | 1.581 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |

## Next Actions

- Main: research/proxy target-pass exists, but no production-compatible account replay passes; convert the rule to broker-ledger evidence before promotion.
- Concentrated: research/proxy target-pass exists, but broker-ledger conversion does not pass; do not promote until next-close replay supports it.
