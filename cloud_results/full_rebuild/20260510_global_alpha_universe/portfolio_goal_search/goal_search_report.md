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
| main | `main_v2_position_aware_risk_proxy` | 36.42% | 0.00pp | -12.81% | 0.00pp | true | `target_pass_review` |
| concentrated | `concentrated_position_risk_proxy` | 48.16% | 1.84pp | -18.09% | 0.09pp | false | `blocked_both` |

## Best Production-Compatible Candidates

| Portfolio | Candidate | CAGR | Gap | MaxDD | Gap | Target Pass | Action |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| main | `main_broker_ledger_replay` | 20.25% | 9.74pp | -32.50% | 17.50pp | false | `blocked_both` |
| concentrated | `concentrated_broker_ledger_replay` | 31.31% | 18.69pp | -39.03% | 21.03pp | false | `blocked_both` |

## Main Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `main_v2_position_aware_risk_proxy` | 36.42% | 0.00pp | -12.81% | 0.00pp | 1.732 | true | sidecar:outputs/position_aware_risk_replay/metrics.json#with_position_risk |
| `orchestrator_replay_main_proxy` | 32.48% | 0.00pp | -13.06% | 0.00pp | 1.844 | true | sidecar:outputs/orchestrator_replay/concentrated_balanced/metrics.json#metrics.main_proxy |
| `main_sleeve_cap_policy_sleeve_cap_policy_I1` | 29.32% | 0.68pp | -14.86% | 0.00pp | 1.700 | false | latest_run_report:outputs/reports/sleeve_cap_policy_comparison.csv |
| `main_latest_champion` | 28.47% | 1.53pp | -15.42% | 0.42pp | 1.651 | false | latest_run:outputs/backtest_metrics.json |
| `main_rebalance_interval_adaptive_I1` | 28.47% | 1.53pp | -15.42% | 0.42pp | 1.651 | false | latest_run_report:outputs/reports/rebalance_interval_comparison.csv |

## Concentrated Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `concentrated_position_risk_proxy` | 48.16% | 1.84pp | -18.09% | 0.09pp | 1.743 | false | sidecar:outputs/concentrated_position_risk_replay/metrics.json |
| `concentrated_grid_N2_score_power_I1` | 51.71% | 0.00pp | -22.91% | 4.91pp | 1.543 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `concentrated_grid_N2_winner_take_all_I1` | 51.71% | 0.00pp | -22.91% | 4.91pp | 1.543 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `concentrated_grid_N2_conviction_curve_I1` | 51.71% | 0.00pp | -22.91% | 4.91pp | 1.543 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `concentrated_grid_N4_conviction_curve_I1` | 43.73% | 6.27pp | -13.63% | 0.00pp | 1.763 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |

## Next Actions

- Main: research/proxy target-pass exists, but no production-compatible account replay passes; convert the rule to broker-ledger evidence before promotion.
- Concentrated: production-compatible candidate exists but misses target; improve staged sizing, replacement, and distribution exits in broker-ledger replay.
