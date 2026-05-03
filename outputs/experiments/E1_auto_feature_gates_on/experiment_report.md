# Aggressive Lab Experiment Report

- Experiment: `E1_auto_feature_gates_on`
- Status: `candidate_only`
- Category: `feature_gates`
- Description: Apply current auto feature gate candidate in challenger mode only.
- Backtest executed: `False`
- Production activation allowed: `False`

## Metrics Source

- Metric mode: `auto_learning_dry_run_metrics_when_available`
- CAGR: 0.20165834588806963
- Sharpe: 1.0971959712745438
- MaxDD: -0.27307967491398366
- Monthly turnover: None

## Artifact Status

| Artifact | Source | Status |
| --- | --- | --- |
| `feature_gate_candidate.yaml` | `cloud_results/full_rebuild/latest_global_alpha_universe/auto_learning/auto_feature_gates_candidate.yaml` | `copied` |
| `promotion_decision.json` | `cloud_results/full_rebuild/latest_global_alpha_universe/auto_learning/promotion_decision.json` | `copied` |
| `feature_gate_candidates.csv` | `` | `derived` |
| `equity_curve.csv` | `` | `report_only_placeholder` |
| `monthly_allocations.csv` | `` | `report_only_placeholder` |
| `sleeve_returns.csv` | `` | `report_only_placeholder` |
| `turnover.csv` | `` | `report_only_placeholder` |
| `stress_windows.csv` | `` | `report_only_placeholder` |
| `trade_journal_summary.md` | `cloud_results/full_rebuild/latest_global_alpha_universe/trade_journal/insights/summary.md` | `copied` |
| `trade_journal_ic_matrix.csv` | `cloud_results/full_rebuild/latest_global_alpha_universe/trade_journal/insights/ic_matrix.csv` | `copied` |
| `trade_journal_cluster_winrate.csv` | `cloud_results/full_rebuild/latest_global_alpha_universe/trade_journal/insights/cluster_winrate.csv` | `copied` |
| `trade_journal_proposal_diff.md` | `cloud_results/full_rebuild/latest_global_alpha_universe/trade_journal/insights/proposal_diff.md` | `copied` |
| `metrics.json` | `` | `derived` |

## Interpretation

E1 is not ready for promotion. The candidate gates are useful research hypotheses, but the latest promotion decision rejected the dry-run because main CAGR, Sharpe, and MaxDD floors failed.

Next code stage should route these gates through the historical scoring/backtest path as an isolated challenger, then compare 20260430/latest attribution before any active gate file changes.
