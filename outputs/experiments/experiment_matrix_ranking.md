# Aggressive Lab Matrix Ranking

This ranking is discovery-only. Passing discovery is not production approval.

| Rank | Experiment | Status | Discovery | CAGR delta pp | MaxDD delta pp | Sharpe delta | Backtest | Notes |
| ---: | --- | --- | --- | ---: | ---: | ---: | --- | --- |
| 1 | `E4_concentrated_balanced` | `standalone_sleeve_policy_audit` | `True` | 13.45 | 4.33 | 0.246 | `False` | needs full challenger |
| 2 | `E6_risk_sensing_on` | `simplified_layer2_backtest` | `True` | -2.94 | 5.65 | -0.064 | `True` |  |
| 3 | `E1_auto_feature_gates_on` | `candidate_only` | `False` | -1.24 | -0.04 | -0.086 | `False` | needs full challenger |
| 4 | `E0_baseline_latest` | `completed` | `False` | 0.00 | 0.00 | 0.000 | `None` |  |
| 5 | `E2_main_v2_balanced` | `snapshot_report_only` | `False` | 0.00 | 0.00 | 0.000 | `False` | needs full challenger |
| 6 | `E3_main_v2_aggressive` | `snapshot_report_only` | `False` | 0.00 | 0.00 | 0.000 | `False` | needs full challenger |
| 7 | `E5_orchestrator_balanced` | `snapshot_report_only` | `False` | 0.00 | 0.00 | 0.000 | `False` | needs full challenger |
| 8 | `E7_tactical_bull_only` | `sidecar_latest_only` | `False` |  |  |  | `False` | needs full challenger |
| 9 | `E8_alpha_sprint_sidecar` | `sidecar_latest_only` | `False` |  |  |  | `False` | needs full challenger |
| 10 | `E9_kitchen_sink_all_on` | `snapshot_discovery_only` | `False` | 0.00 | 0.00 | 0.000 | `False` | needs full challenger |

## Interpretation

Most experiments are still snapshot/proxy adapters. The ranking is useful for prioritization, not promotion.
E6 can pass discovery on drawdown improvement while still needing a position-aware risk replay.
