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
| main | `main_v2_position_aware_risk_proxy` | 37.36% | 0.00pp | -12.71% | 0.00pp | true | `target_pass_review` |
| concentrated | `concentrated_position_risk_proxy` | 52.56% | 0.00pp | -15.23% | 0.00pp | true | `target_pass_review` |

## Main Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `main_v2_position_aware_risk_proxy` | 37.36% | 0.00pp | -12.71% | 0.00pp | 1.794 | true | sidecar:outputs/position_aware_risk_replay/metrics.json#with_position_risk |
| `orchestrator_replay_main_proxy` | 35.07% | 0.00pp | -14.03% | 0.00pp | 1.889 | true | sidecar:outputs/orchestrator_replay/concentrated_balanced/metrics.json#metrics.main_proxy |
| `main_ai_four_sleeve_ai_four_sleeve_adaptive_I1` | 31.24% | 0.00pp | -15.89% | 0.89pp | 1.737 | false | latest_run_report:outputs/reports/ai_four_sleeve_adaptive_comparison.csv |
| `main_rebalance_interval_fixed_interval_I1` | 31.28% | 0.00pp | -16.20% | 1.20pp | 1.721 | false | latest_run_report:outputs/reports/rebalance_interval_comparison.csv |
| `main_latest_champion` | 30.91% | 0.00pp | -16.38% | 1.38pp | 1.700 | false | latest_run:outputs/backtest_metrics.json |

## Concentrated Top 5

| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `concentrated_position_risk_proxy` | 52.56% | 0.00pp | -15.23% | 0.00pp | 1.834 | true | sidecar:outputs/concentrated_position_risk_replay/metrics.json |
| `concentrated_latest_champion` | 49.80% | 0.20pp | -17.24% | 0.00pp | 1.761 | false | latest_run:outputs/concentrated_backtest_metrics.json |
| `concentrated_grid_N3_conviction_curve_I1` | 49.80% | 0.20pp | -17.24% | 0.00pp | 1.761 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `concentrated_grid_N3_winner_take_all_I1` | 49.76% | 0.24pp | -17.43% | 0.00pp | 1.738 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |
| `concentrated_grid_N3_score_power_I1` | 49.75% | 0.25pp | -16.43% | 0.00pp | 1.712 | false | latest_run_report:outputs/reports/concentrated_strategy_comparison.csv |

## Next Actions

- Main: target-pass candidate exists; require strict gate, stress windows, turnover, and human approval.
- Concentrated: target-pass candidate exists; validate caps, timing, turnover, and production promotion gates.
