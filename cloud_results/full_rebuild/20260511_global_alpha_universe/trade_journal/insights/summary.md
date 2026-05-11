# Trade Insights Summary

- trades analyzed: **967**
- generated: 2026-05-11 11:59 UTC

## 1. Signal IC by regime (rank correlation)
Top actionable findings:

**Worst signal x regime cells (potential gate candidates)**:
- `entry_quality_score` in **deep_bear**: IC = -0.582
- `theme_phase_multiplier_max` in **deep_bear**: IC = -0.156
- `theme_phase_multiplier_primary` in **deep_bear**: IC = -0.156

**Best signal x regime cells (amplify candidates)**:
- `rs_acceleration_score` in **deep_bear**: IC = +0.619
- `h6_dynamic_leader_score` in **strong_bull**: IC = +0.574
- `entry_quality_score` in **strong_bull**: IC = +0.200

Full matrix in `ic_matrix.csv`.

## 2. Trade pattern clusters
**Worst pattern clusters (block candidates)**:
- cluster 7: win_rate=0.51, n=158, signature: rs_acceleration_score=+0.72, theme_phase_multiplier_primary=+0.55, theme_phase_multiplier_max=+0.54
- cluster 0: win_rate=0.53, n=254, signature: entry_quality_score=+1.31, selection_confirmation_score=+0.60, theme_phase_multiplier_primary=+0.51

**Best pattern clusters (amplify candidates)**:
- cluster 5: win_rate=0.67, n=109, signature: h6_dynamic_leader_score=+2.00, rs_acceleration_score=+1.02, selection_confirmation_score=+0.71
- cluster 4: win_rate=0.62, n=138, signature: portfolio_risk_entry_block_score=+2.28, portfolio_monster_early_score=+1.96, theme_phase_multiplier_max=-1.83

Full table in `cluster_winrate.csv`.

## 3. SHAP / model importance
_(no SHAP - no data)_

---

**Phase 18c next**: feed `ic_matrix.csv` + `cluster_winrate.csv` to `tools/feature_gate_proposal.py` to auto-draft `research/auto_feature_gates.yaml`.