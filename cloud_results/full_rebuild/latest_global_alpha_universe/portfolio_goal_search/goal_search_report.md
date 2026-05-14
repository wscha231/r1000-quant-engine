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
| main | `main_v2_position_aware_risk_proxy` | 37.23% | 0.00pp | -12.70% | 0.00pp | true | `target_pass_review` |
| concentrated | `concentrated_position_risk_proxy` | 59.11% | 0.00pp | -13.70% | 0.00pp | true | `target_pass_review` |

## Best Production-Compatible Candidates

| Portfolio | Candidate | CAGR | Gap | MaxDD | Gap | Target Pass | Action |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| main | `main_broker_crisis_reentry_fast_reentry` | 19.68% | 10.32pp | -31.91% | 16.91pp | false | `blocked_both` |
| concentrated | `concentrated_broker_ledger_replay` | 35.10% | 14.90pp | -22.68% | 4.68pp | false | `blocked_both` |

## Main Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `main_v2_position_aware_risk_proxy` | 37.23% | 0.00pp | -12.70% | 0.00pp | 1.783 | true | sidecar:outputs/position_aware_risk_replay/metrics.json#with_position_risk |
| `orchestrator_replay_main_proxy` | 34.87% | 0.00pp | -14.62% | 0.00pp | 1.881 | true | sidecar:outputs/orchestrator_replay/concentrated_balanced/metrics.json#metrics.main_proxy |
| `main_rebalance_interval_fixed_interval_I1` | 31.92% | 0.00pp | -15.46% | 0.46pp | 1.741 | false | latest_run_report:outputs/reports/rebalance_interval_comparison.csv |
| `main_latest_champion` | 30.62% | 0.00pp | -16.88% | 1.88pp | 1.687 | false | latest_run:outputs/backtest_metrics.json |
| `main_rebalance_interval_adaptive_I1` | 30.62% | 0.00pp | -16.88% | 1.88pp | 1.687 | false | latest_run_report:outputs/reports/rebalance_interval_comparison.csv |

## Concentrated Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `concentrated_position_risk_proxy` | 59.11% | 0.00pp | -13.70% | 0.00pp | 1.955 | true | sidecar:outputs/concentrated_position_risk_replay/metrics.json |
| `concentrated_latest_champion` | 56.30% | 0.00pp | -14.83% | 0.00pp | 1.884 | true | latest_run:outputs/concentrated_backtest_metrics.json |
| `concentrated_grid_N5_winner_take_all_I1` | 56.30% | 0.00pp | -14.83% | 0.00pp | 1.884 | true | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `concentrated_grid_N4_winner_take_all_I1` | 56.12% | 0.00pp | -14.06% | 0.00pp | 1.784 | true | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `concentrated_grid_N3_winner_take_all_I1` | 55.14% | 0.00pp | -15.35% | 0.00pp | 1.728 | true | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |

## Next Actions

- Main: research/proxy target-pass exists, but no production-compatible account replay passes; convert the rule to broker-ledger evidence before promotion.
- Concentrated: research/proxy target-pass exists, but broker-ledger conversion does not pass; do not promote until next-close replay supports it.
