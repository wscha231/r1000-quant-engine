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
| main | `main_v2_position_aware_risk_proxy` | 28.38% | 1.62pp | -11.05% | 0.00pp | false | `needs_alpha_boost` |
| concentrated | `concentrated_position_risk_proxy` | 31.68% | 18.32pp | -17.99% | 0.00pp | false | `needs_alpha_boost` |

## Best Production-Compatible Candidates

| Portfolio | Candidate | CAGR | Gap | MaxDD | Gap | Target Pass | Action |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| main | `main_alpha_selector_market_circuit_grid_best` | 23.25% | 6.75pp | -22.88% | 7.88pp | false | `blocked_both` |
| concentrated | `concentrated_alpha_selector_market_circuit_grid_best` | 23.25% | 26.75pp | -22.88% | 4.88pp | false | `blocked_both` |

## Main Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `main_v2_position_aware_risk_proxy` | 28.38% | 1.62pp | -11.05% | 0.00pp | 1.653 | false | sidecar:outputs/position_aware_risk_replay/metrics.json#with_position_risk |
| `orchestrator_replay_main_proxy` | 24.07% | 5.93pp | -13.20% | 0.00pp | 1.722 | false | sidecar:outputs/orchestrator_replay/concentrated_balanced/metrics.json#metrics.main_proxy |
| `main_latest_champion` | 20.29% | 9.71pp | -15.28% | 0.28pp | 1.485 | false | latest_run:outputs/backtest_metrics.json |
| `main_rebalance_interval_adaptive_I1` | 20.29% | 9.71pp | -15.28% | 0.28pp | 1.485 | false | latest_run_report:outputs/reports/rebalance_interval_comparison.csv |
| `main_rebalance_interval_fixed_interval_I1` | 20.15% | 9.85pp | -15.29% | 0.29pp | 1.474 | false | latest_run_report:outputs/reports/rebalance_interval_comparison.csv |

## Concentrated Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `concentrated_position_risk_proxy` | 31.68% | 18.32pp | -17.99% | 0.00pp | 1.319 | false | sidecar:outputs/concentrated_position_risk_replay/metrics.json |
| `experiment_E4_concentrated_balanced` | 34.85% | 15.15pp | -22.94% | 4.94pp | 1.429 | false | experiment:outputs/experiments/E4_concentrated_balanced/metrics.json |
| `concentrated_latest_champion` | 28.11% | 21.89pp | -11.45% | 0.00pp | 1.584 | false | latest_run:outputs/concentrated_backtest_metrics.json |
| `concentrated_grid_N7_score_power_I1` | 28.11% | 21.89pp | -11.45% | 0.00pp | 1.584 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `concentrated_grid_N2_winner_take_all_I1` | 29.03% | 20.97pp | -18.95% | 0.95pp | 1.230 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |

## Next Actions

- Main: production-compatible candidate exists but misses target; inspect broker-ledger trades, cash drag, and MDD before changing live policy.
- Concentrated: production-compatible candidate exists but misses target; improve staged sizing, replacement, and distribution exits in broker-ledger replay.
